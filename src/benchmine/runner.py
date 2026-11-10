"""Run an agent over the mined tasks and grade it with the hidden tests."""
import datetime
import json
import os
import re
import shlex
import shutil
import time
from concurrent.futures import ThreadPoolExecutor

from . import __version__
from . import config as cfgmod
from . import gitutil as g
from . import tasks as T


def runs_dir(root):
    return os.path.join(root, cfgmod.DIRNAME, "runs")


def new_run_id(label):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or "run"
    return "%s-%s" % (stamp, safe)


def attempt(root, task, cfg, kind, template, model, cost_regex, n, outdir, timeout, keep=False):
    log = os.path.join(outdir, "%s-%d.log" % (task["id"], n))
    rec = {"task": task["id"], "attempt": n, "passed": False, "error": None}
    try:
        tmp, tree = T.prepare_tree(root, task, cfg, log=log)
    except Exception as e:  # setup failed: count as an infra error, not an agent failure
        rec["error"] = "setup: %s" % e
        return rec
    try:
        prompt_file = os.path.join(tmp, "prompt.txt")
        with open(prompt_file, "w") as fh:
            fh.write(task["prompt"] + "\n")
        cost_file = os.path.join(tmp, "cost.txt")
        t0 = time.time()
        rc, out, timed_out = 0, "", False
        if kind == "oracle":
            T.overlay(root, task["ref"], tree, task["source_files"])
        elif kind == "cmd":
            env = dict(os.environ, BENCHMINE_PROMPT_FILE=prompt_file, BENCHMINE_TASK_ID=task["id"],
                       BENCHMINE_MODEL=model or "", BENCHMINE_COST_FILE=cost_file, BENCHMINE_WORKDIR=tree)
            cmd = T.fill(template, task, {
                "prompt_file": shlex.quote(prompt_file), "prompt": shlex.quote(task["prompt"]),
                "model": shlex.quote(model or ""), "workdir": shlex.quote(tree)})
            rc, out, timed_out, _ = T.sh(cmd, tree, timeout, env=env, log=log)
        secs = time.time() - t0
        files, add, rem, patch = g.worktree_changes(tree)
        with open(os.path.join(outdir, "%s-%d.patch" % (task["id"], n)), "wb") as fh:
            fh.write(patch)
        cost = None
        if os.path.exists(cost_file):
            try:
                cost = float(open(cost_file).read().strip())
            except ValueError:
                pass
        if cost is None and cost_regex:
            m = re.findall(cost_regex, out)
            if m:
                cost = float(m[-1])
        touched_tests = sorted(f for f in files if f in task["test_files"])
        test_rc, test_out, test_to = T.run_tests(root, task, cfg, tree, log=log)
        rec.update({
            "passed": test_rc == 0, "agent_rc": rc, "timed_out": timed_out, "secs": round(secs, 2),
            "cost": cost, "files": len(files), "add": add, "rem": rem,
            "ref_add": task["ref_add"], "ref_rem": task["ref_rem"],
            "touched_tests": touched_tests, "test_rc": test_rc, "test_timed_out": test_to,
        })
        return rec
    finally:
        if keep:
            rec["tree"] = tree
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def run(root, tasks, cfg, agent, kind, template, model=None, cost_regex=None, label=None, repeat=1, jobs=1,
        timeout=None, keep=False, progress=None):
    label = label or (agent + ("@" + model if model else ""))
    run_id = new_run_id(label)
    outdir = os.path.join(runs_dir(root), run_id)
    os.makedirs(outdir, exist_ok=True)
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    timeout = timeout or cfg.get("timeout", 1800)
    work = [(t, n) for t in tasks for n in range(1, repeat + 1)]

    def one(item):
        t, n = item
        r = attempt(root, t, cfg, kind, template, model, cost_regex, n, outdir, timeout, keep)
        if progress:
            progress(r)
        return r

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        results = list(ex.map(one, work))
    body = {
        "version": 1, "run_id": run_id, "label": label, "agent": agent, "model": model, "cmd": template,
        "started": started, "finished": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "benchmine": __version__, "taskset": T.taskset_hash(tasks), "repeat": repeat, "results": results,
    }
    path = os.path.join(runs_dir(root), run_id + ".json")
    with open(path, "w") as fh:
        json.dump(body, fh, indent=2)
        fh.write("\n")
    return path, body


def load_run(root, ref):
    """ref: a path, a run id, a unique prefix/substring of a run id, or 'latest[:label]'."""
    if os.path.isfile(ref):
        with open(ref) as fh:
            return json.load(fh)
    d = runs_dir(root)
    names = sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json")) if os.path.isdir(d) else []
    if ref.startswith("latest"):
        want = ref.split(":", 1)[1] if ":" in ref else None
        bodies = [json.load(open(os.path.join(d, n + ".json"))) for n in names]
        bodies = [b for b in bodies if not want or b["label"] == want]
        if not bodies:
            raise FileNotFoundError("no runs%s" % (" labelled " + want if want else ""))
        return bodies[-1]
    hits = [n for n in names if n == ref] or [n for n in names if n.startswith(ref)] or [n for n in names if ref in n]
    if len(hits) != 1:
        raise FileNotFoundError("run %r: %s" % (ref, "not found" if not hits else "ambiguous: " + ", ".join(hits)))
    with open(os.path.join(d, hits[0] + ".json")) as fh:
        return json.load(fh)


def list_runs(root):
    d = runs_dir(root)
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".json"):
            with open(os.path.join(d, f)) as fh:
                out.append(json.load(fh))
    return out
