"""Mine tasks from first-parent history: parent commit + message as the prompt, the change's own tests as the grader."""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time

from . import config as cfgmod
from . import gitutil as g

TRAILER = re.compile(r"^(co-authored-by|signed-off-by|reviewed-by|acked-by|change-id|cc|reported-by|tested-by):", re.I)
MERGE_PR = re.compile(r"^Merge pull request #(\d+) from \S+\s*$")
SQUASH_PR = re.compile(r"\(#(\d+)\)\s*$")
SKIP_SUBJECT = re.compile(r"^(revert|bump|chore\(deps|build\(deps|release|version|wip\b|merge branch)", re.I)


def clean_message(msg):
    lines = [ln.rstrip() for ln in msg.strip().splitlines()]
    pr = None
    if lines and MERGE_PR.match(lines[0]):
        pr = int(MERGE_PR.match(lines[0]).group(1))
        lines = lines[1:]
    elif lines:
        m = SQUASH_PR.search(lines[0])
        if m:
            pr = int(m.group(1))
            lines[0] = lines[0][: m.start()].rstrip()
    lines = [ln for ln in lines if not TRAILER.match(ln.strip())]
    text = "\n".join(lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, pr


def gh_pr_text(root, number):
    """Title + body of PR #number via the GitHub CLI, or None."""
    if not shutil.which("gh"):
        return None
    p = subprocess.run(["gh", "pr", "view", str(number), "--json", "title,body"], cwd=root,
                       capture_output=True, text=True)
    if p.returncode != 0:
        return None
    try:
        d = json.loads(p.stdout)
    except ValueError:
        return None
    body = re.sub(r"<!--.*?-->", "", d.get("body") or "", flags=re.S).strip()
    return (d.get("title", "") + ("\n\n" + body if body else "")).strip()


def merge_context(root, base, tip, text):
    """For a PR merge commit, add the messages of the branch's own commits to the PR title."""
    out = g.git(root, "log", "--reverse", "--format=%B%x00", "-n", "8", "%s..%s" % (base, tip), check=False)
    seen = {text.strip()}
    parts = [text.strip()] if text.strip() else []
    for m in out.split("\0"):
        m, _ = clean_message(m)
        if m and m not in seen and not m.lower().startswith("merge "):
            seen.add(m)
            parts.append(m)
    return "\n\n".join(parts)


def classify(files, cfg):
    tests, src, ignored = [], [], []
    for status, path in files:
        if cfgmod.is_test_path(path, cfg):
            tests.append((status, path))
        elif cfgmod.is_ignored(path, cfg):
            ignored.append(path)
        else:
            src.append((status, path))
    return tests, src, ignored


def runnable_tests(paths, cfg):
    import fnmatch
    pats = cfg.get("test_patterns", cfgmod.TEST_PATTERNS)
    return [p for p in paths if any(fnmatch.fnmatch(p.rsplit("/", 1)[-1], pat) for pat in pats)
            and p.rsplit("/", 1)[-1] != "conftest.py"]


def candidates(root, cfg, rev="HEAD", limit=200, since=None, max_files=25, min_prompt=20, use_gh=False):
    """Yield (task, None) for each usable commit or (None, reason) for skipped ones."""
    for sha in g.first_parent_commits(root, rev, limit, since):
        ps = g.parents(root, sha)
        short = sha[:10]
        if not ps:
            yield None, (short, "root commit")
            continue
        base = ps[0]
        raw = g.message(root, sha)
        text, pr = clean_message(raw)
        subject = text.splitlines()[0] if text else ""
        if SKIP_SUBJECT.match(subject):
            yield None, (short, "skipped subject: " + subject[:60])
            continue
        got_gh = False
        if use_gh and pr:
            t = gh_pr_text(root, pr)
            if t:
                text, got_gh = t, True
        if len(ps) > 1 and not got_gh:
            text = merge_context(root, base, ps[1], text)
        files = g.changed_files(root, base, sha)
        tests, src, _ = classify(files, cfg)
        if not tests:
            yield None, (short, "no test changes")
            continue
        if not src:
            yield None, (short, "tests only, no code change")
            continue
        if len(src) > max_files:
            yield None, (short, "too big (%d code files)" % len(src))
            continue
        if len(text) < min_prompt:
            yield None, (short, "message too short to be a prompt")
            continue
        test_paths = [p for _, p in tests]
        add, rem = g.numstat(root, base, sha, [p for _, p in src])
        task = {
            "id": short,
            "base": base,
            "ref": sha,
            "pr": pr,
            "date": g.commit_date(root, sha),
            "subject": subject,
            "prompt": cfg["prompt_template"].replace("{message}", text),
            "source_files": [p for _, p in src],
            "test_files": test_paths,
            "run_tests": runnable_tests([p for s, p in tests if s != "D"], cfg),
            "ref_add": add,
            "ref_rem": rem,
        }
        yield task, None


def overlay(root, rev, dest, paths):
    """Make paths in dest match their content at rev (deleting those absent at rev)."""
    for p in paths:
        target = os.path.join(dest, p)
        data = g.show_file(root, rev, p)
        if data is None:
            if os.path.isdir(target) and not os.path.islink(target):
                shutil.rmtree(target)
            elif os.path.lexists(target):
                os.remove(target)
            continue
        os.makedirs(os.path.dirname(target) or dest, exist_ok=True)
        if os.path.lexists(target) and (os.path.isdir(target) and not os.path.islink(target)):
            shutil.rmtree(target)
        with open(target, "wb") as fh:
            fh.write(data)


def fill(template, task, extra=None):
    tests = task.get("run_tests") or task["test_files"]
    dirs = sorted({os.path.dirname(t) or "." for t in tests})
    pkgs = sorted({"./" + os.path.dirname(t) if os.path.dirname(t) else "." for t in tests if t.endswith("_test.go")}) or ["./..."]
    vals = {
        "tests": " ".join(shlex.quote(t) for t in tests),
        "test_dirs": " ".join(shlex.quote(d) for d in dirs),
        "test_pkgs": " ".join(shlex.quote(p) for p in pkgs),
        "task_id": task["id"],
    }
    vals.update(extra or {})
    out = template
    for k, v in vals.items():
        out = out.replace("{" + k + "}", v)
    return out


def sh(cmd, cwd, timeout, env=None, log=None):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, env=env, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        rc, out, timed_out = p.returncode, p.stdout, False
    except subprocess.TimeoutExpired as e:
        rc, out, timed_out = 124, e.stdout or b"", True
    if log:
        with open(log, "ab") as fh:
            fh.write(("$ %s\n" % cmd).encode())
            fh.write(out)
            fh.write(("\n[exit %d%s, %.1fs]\n" % (rc, ", timed out" if timed_out else "", time.time() - t0)).encode())
    return rc, out.decode("utf-8", errors="replace"), timed_out, time.time() - t0


def prepare_tree(root, task, cfg, workroot=None, log=None):
    """Fresh tree at the task's base with no git history, after setup_cmd. Returns path."""
    tmp = tempfile.mkdtemp(prefix="bm-%s-" % task["id"], dir=workroot)
    tree = os.path.join(tmp, "repo")
    os.makedirs(tree)
    g.export_tree(root, task["base"], tree)
    if cfg.get("setup_cmd"):
        rc, out, to, _ = sh(cfg["setup_cmd"], tree, cfg.get("test_timeout", 600), log=log)
        if rc != 0:
            raise RuntimeError("setup_cmd failed (exit %d): %s" % (rc, out[-400:]))
    g.init_snapshot(tree)
    return tmp, tree


def clear_bytecode(tree):
    """Drop __pycache__ dirs: a same-size edit within the same second would otherwise run stale .pyc files."""
    for d, subdirs, _ in os.walk(tree):
        if "__pycache__" in subdirs:
            shutil.rmtree(os.path.join(d, "__pycache__"), ignore_errors=True)
            subdirs.remove("__pycache__")
        for skip in (".git", "node_modules"):
            if skip in subdirs:
                subdirs.remove(skip)


def run_tests(root, task, cfg, tree, log=None):
    overlay(root, task["ref"], tree, task["test_files"])
    clear_bytecode(tree)
    cmd = fill(cfg["test_cmd"], task)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    rc, out, to, secs = sh(cmd, tree, cfg.get("test_timeout", 600), env=env, log=log)
    return rc, out, to


def validate(root, task, cfg, keep=False):
    """A task is valid if its hidden tests fail on the base code and pass with the reference change."""
    tmp, tree = prepare_tree(root, task, cfg)
    try:
        rc_base, out_base, _ = run_tests(root, task, cfg, tree)
        if rc_base == 0:
            return False, "tests already pass before the change"
        overlay(root, task["ref"], tree, task["source_files"])
        rc_ref, out_ref, to = run_tests(root, task, cfg, tree)
        if rc_ref != 0:
            tail = out_ref.strip().splitlines()[-1:] or [""]
            return False, "tests fail even with the real change%s: %s" % (" (timeout)" if to else "", tail[0][:120])
        return True, "fail -> pass"
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


def tasks_path(root):
    return os.path.join(root, cfgmod.DIRNAME, "tasks.json")


def save_tasks(root, tasks, meta):
    os.makedirs(os.path.join(root, cfgmod.DIRNAME), exist_ok=True)
    body = {"version": 1, **meta, "tasks": tasks}
    with open(tasks_path(root), "w") as fh:
        json.dump(body, fh, indent=2)
        fh.write("\n")


def load_tasks(root):
    p = tasks_path(root)
    if not os.path.exists(p):
        raise FileNotFoundError("no tasks yet: run `benchmine mine` first (%s)" % p)
    with open(p) as fh:
        return json.load(fh)


def taskset_hash(tasks):
    h = hashlib.sha256()
    for t in sorted(tasks, key=lambda t: t["id"]):
        h.update((t["base"] + t["ref"] + t["prompt"]).encode())
    return h.hexdigest()[:12]
