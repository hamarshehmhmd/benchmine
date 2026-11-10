"""benchmine command line."""
import argparse
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor

from . import __version__
from . import agents as A
from . import config as cfgmod
from . import gitutil as g
from . import report as R
from . import runner
from . import tasks as T

COLOR = False


def c(code, s):
    return "\x1b[%sm%s\x1b[0m" % (code, s) if COLOR else s


def ok(s):
    return c("32", s)


def bad(s):
    return c("31", s)


def warn(s):
    return c("33", s)


def dim(s):
    return c("2", s)


def pct(x):
    return "%3.0f%%" % (100 * x)


def fmt_secs(s):
    if s is None:
        return "-"
    if s < 10:
        return "%.1fs" % s
    return "%.0fs" % s if s < 120 else "%.1fm" % (s / 60)


def fmt_cost(x):
    return "-" if x is None else "$%.2f" % x


def root_of(args):
    try:
        return g.toplevel(args.repo)
    except g.GitError:
        sys.exit("benchmine: %s is not inside a git repository" % args.repo)


def cmd_init(args):
    root = root_of(args)
    cfg = cfgmod.load(root)
    if args.test_cmd:
        cfg["test_cmd"] = args.test_cmd
    if args.setup_cmd:
        cfg["setup_cmd"] = args.setup_cmd
    cfgmod.save(root, cfg)
    print("wrote %s" % os.path.join(cfgmod.DIRNAME, "config.json"))
    print("  test_cmd:  %s" % (cfg["test_cmd"] or warn("(none detected: pass --test-cmd)")))
    print("  setup_cmd: %s" % (cfg.get("setup_cmd") or dim("(none)")))
    return 0


def cmd_mine(args):
    root = root_of(args)
    cfg = cfgmod.load(root)
    if args.test_cmd:
        cfg["test_cmd"] = args.test_cmd
    if args.setup_cmd:
        cfg["setup_cmd"] = args.setup_cmd
    if not cfg.get("test_cmd"):
        sys.exit("benchmine: no test command detected; pass --test-cmd 'pytest -q {tests}' or run benchmine init")
    found, skipped = [], []
    for task, why in T.candidates(root, cfg, args.rev, args.limit, args.since, args.max_files, use_gh=args.gh):
        if task:
            found.append(task)
        else:
            skipped.append(why)
    print("scanned %d first-parent commits: %d change code and tests, %d skipped"
          % (len(found) + len(skipped), len(found), len(skipped)))
    if args.verbose:
        for sha, why in skipped:
            print(dim("  - %s  %s" % (sha, why)))
    if args.no_validate:
        kept = found[: args.max_tasks] if args.max_tasks else found
    else:
        print("validating with: %s" % cfg["test_cmd"])

        def check(t):
            return t, T.validate(root, t, cfg)

        kept = []
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            for t, (good, why) in ex.map(check, found):
                mark = ok("  ✓") if good else dim("  ✗")
                line = "%s %s  %-40s %s" % (mark, t["id"], t["subject"][:40], why if good else dim(why))
                print(line)
                if good:
                    t["validated"] = why
                    kept.append(t)
        if args.max_tasks:
            kept = kept[: args.max_tasks]
    T.save_tasks(root, kept, {"repo_head": g.rev_parse(root, args.rev), "test_cmd": cfg["test_cmd"],
                              "setup_cmd": cfg.get("setup_cmd"), "taskset": T.taskset_hash(kept)})
    cfgmod.save(root, cfg)
    print("%s %d tasks -> %s" % (ok("saved") if kept else warn("saved"), len(kept),
                                 os.path.relpath(T.tasks_path(root), os.getcwd())))
    return 0 if kept else 1


def cmd_tasks(args):
    root = root_of(args)
    body = T.load_tasks(root)
    ts = body["tasks"]
    if args.id:
        for t in ts:
            if t["id"].startswith(args.id):
                print(json.dumps(t, indent=2) if args.json else t["prompt"])
                return 0
        sys.exit("benchmine: no task %s" % args.id)
    if args.json:
        print(json.dumps(body, indent=2))
        return 0
    print("%d tasks (taskset %s, tests: %s)" % (len(ts), body.get("taskset"), body.get("test_cmd")))
    for t in ts:
        print("  %s  %-48s %2d code files  +%d/-%d  hidden tests: %s" % (
            t["id"], t["subject"][:48], len(t["source_files"]), t["ref_add"], t["ref_rem"],
            ", ".join(t["run_tests"] or t["test_files"])[:60]))
    return 0


def cmd_agents(args):
    print("built in:")
    for k, v in A.BUILTIN.items():
        print("  %-12s %s" % (k, v))
    print("presets (command templates; edit with --cmd):")
    for k, v in A.PRESETS.items():
        exe = v["cmd"].split()[0]
        have = ok("found") if shutil.which(exe) else dim("not installed")
        print("  %-12s %-13s %s" % (k, have, v["cmd"].replace("{model_flag}", v["model_flag"])))
    print(dim("placeholders: {prompt} {prompt_file} {model} {task_id} {workdir}; env BENCHMINE_COST_FILE for cost"))
    return 0


def cmd_run(args):
    root = root_of(args)
    cfg = cfgmod.load(root)
    body = T.load_tasks(root)
    for k in ("test_cmd", "setup_cmd"):
        if body.get(k) and not cfg.get(k):
            cfg[k] = body[k]
    ts = body["tasks"]
    if args.tasks:
        want = args.tasks.split(",")
        ts = [t for t in ts if any(t["id"].startswith(w) for w in want)]
    if not ts:
        sys.exit("benchmine: no tasks to run")
    try:
        kind, template, cost_re = A.resolve(args.agent, args.cmd, args.model)
    except ValueError as e:
        sys.exit("benchmine: %s" % e)
    cost_re = args.cost_regex or cost_re
    label = args.label or (args.agent + ("@" + args.model if args.model else ""))
    if args.dry_run:
        t = ts[0]
        print("task %s, prompt:\n%s\n" % (t["id"], t["prompt"]))
        if template:
            print("agent command:\n  " + T.fill(template, t, {"prompt_file": "<prompt.txt>", "prompt": "<prompt>",
                                                           "model": args.model or "", "workdir": "<tree>"}))
        print("tests:\n  " + T.fill(cfg["test_cmd"], t))
        return 0
    print("running %s on %d tasks x %d (%s)" % (c("1", label), len(ts), args.repeat, "jobs=%d" % args.jobs))

    def progress(r):
        if r.get("error"):
            print("  %s %s#%d %s" % (warn("!"), r["task"], r["attempt"], r["error"][:100]))
            return
        mark = ok("✓ pass") if r["passed"] else bad("✗ fail")
        extra = []
        if r.get("timed_out"):
            extra.append(warn("agent timeout"))
        if r.get("touched_tests"):
            extra.append(warn("edited hidden tests"))
        print("  %s  %s#%d  %5s  %s  +%d/-%d (ref +%d/-%d) %s" % (
            mark, r["task"], r["attempt"], fmt_secs(r["secs"]), fmt_cost(r.get("cost")), r["add"], r["rem"],
            r["ref_add"], r["ref_rem"], " ".join(extra)))
        sys.stdout.flush()

    path, run = runner.run(root, ts, cfg, args.agent, kind, template, args.model, cost_re, label, args.repeat,
                           args.jobs, args.timeout, args.keep, progress)
    s = R.summarize(run)
    print("%s  %d/%d passed  %s  (95%% CI %s-%s)  -> %s" % (
        c("1", label), s["passed"], s["attempts"], pct(s["pass_rate"]).strip(), pct(s["ci"][0]).strip(),
        pct(s["ci"][1]).strip(), os.path.relpath(path, os.getcwd())))
    return 0


def _runs(root, refs):
    if refs:
        return [runner.load_run(root, r) for r in refs]
    return runner.list_runs(root)


def cmd_report(args):
    root = root_of(args)
    runs = _runs(root, args.runs)
    if not runs:
        sys.exit("benchmine: no runs yet (benchmine run --agent ...)")
    rows = [R.summarize(r) for r in runs]
    if args.format == "json":
        print(json.dumps(rows, indent=2))
        return 0
    head = ["agent", "pass", "95% CI", "tasks", "median time", "cost", "$/pass", "diff vs ref", "edited tests", "run"]
    body = []
    for s in rows:
        body.append([
            s["label"], "%d/%d %s" % (s["passed"], s["attempts"], pct(s["pass_rate"]).strip()),
            "%s-%s" % (pct(s["ci"][0]).strip(), pct(s["ci"][1]).strip()), str(s["tasks"]),
            fmt_secs(s["median_secs"]), fmt_cost(s["cost"]), fmt_cost(s["cost_per_pass"]),
            "-" if s["median_diff_ratio"] is None else "%.1fx" % s["median_diff_ratio"],
            str(s["edited_hidden_tests"]), s["run_id"]])
    if args.format == "md":
        print("| " + " | ".join(head) + " |")
        print("|" + "---|" * len(head))
        for b in body:
            print("| " + " | ".join(b) + " |")
        return 0
    widths = [max(len(h), *(len(b[i]) for b in body)) for i, h in enumerate(head)]
    print("  ".join(c("1", h.ljust(w)) for h, w in zip(head, widths)))
    for b in body:
        print("  ".join(x.ljust(w) for x, w in zip(b, widths)))
    print(dim("diff vs ref = lines the agent changed / lines the real change touched, on passing tasks"))
    return 0


def cmd_compare(args):
    root = root_of(args)
    base = runner.load_run(root, args.baseline)
    cur = runner.load_run(root, args.current)
    res = R.compare(base, cur, args.alpha)
    if args.format == "json":
        print(json.dumps(res, indent=2))
    else:
        print("baseline %s (%s)  vs  current %s (%s)" % (c("1", res["baseline"]), res["baseline_run"],
                                                         c("1", res["current"]), res["current_run"]))
        if not res["same_taskset"]:
            print(warn("  note: different task sets; comparing the %d tasks they share" % res["tasks_compared"]))
        print("  pass rate %s -> %s  (%+.0f points, 95%% CI %+.0f to %+.0f)" % (
            pct(res["baseline_rate"]).strip(), pct(res["current_rate"]).strip(), 100 * res["delta"],
            100 * res["delta_ci"][0], 100 * res["delta_ci"][1]))
        print("  %d tasks got worse: %s" % (len(res["regressed"]), ", ".join(res["regressed"]) or "-"))
        print("  %d tasks got better: %s" % (len(res["improved"]), ", ".join(res["improved"]) or "-"))
        print("  sign test p(drop by chance) = %.3f" % res["p_drop"])
        v = res["verdict"]
        col = bad if v == "REGRESSION" else ok if v == "improvement" else dim
        print("  verdict: %s" % col(v + ("" if v != "no significant change" else
                                       " (at least %d tasks must move one way for a signal at alpha=%.2f)"
                                       % (res["needed_for_signal"], res["alpha"]))))
    return 3 if res["verdict"] == "REGRESSION" else 0


def build_parser():
    p = argparse.ArgumentParser(prog="benchmine", description="Turn your repo's own history into a private benchmark "
                                "for coding agents: pick models on your code, and catch silent quality drops.")
    p.add_argument("--version", action="version", version="benchmine " + __version__)
    p.add_argument("-C", "--repo", default=".", help="repository (default: current directory)")
    p.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("init", help="write .benchmine/config.json with the detected test command")
    s.add_argument("--test-cmd")
    s.add_argument("--setup-cmd")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("mine", help="turn history into validated fail->pass tasks")
    s.add_argument("--rev", default="HEAD")
    s.add_argument("--limit", type=int, default=300, help="first-parent commits to scan (default 300)")
    s.add_argument("--since", help="only commits after this date, e.g. '6 months ago'")
    s.add_argument("--max-tasks", type=int, default=0)
    s.add_argument("--max-files", type=int, default=25, help="skip changes touching more code files")
    s.add_argument("--test-cmd", help="test command template: {tests} {test_dirs} {test_pkgs}")
    s.add_argument("--setup-cmd", help="run in each fresh tree first, e.g. 'npm ci'")
    s.add_argument("--gh", action="store_true", help="use PR title+body from GitHub (gh CLI) as the prompt")
    s.add_argument("--no-validate", action="store_true", help="skip the fail->pass check (not recommended)")
    s.add_argument("-j", "--jobs", type=int, default=2)
    s.add_argument("-v", "--verbose", action="store_true", help="list skipped commits and why")
    s.set_defaults(fn=cmd_mine)

    s = sub.add_parser("tasks", help="list mined tasks, or print one task's prompt")
    s.add_argument("id", nargs="?")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_tasks)

    s = sub.add_parser("agents", help="show built-in agents and harness presets")
    s.set_defaults(fn=cmd_agents)

    s = sub.add_parser("run", help="run an agent on every task and grade it with the hidden tests")
    s.add_argument("--agent", default="oracle", help="oracle, noop, a preset (claude-code, codex, ...) or a label for --cmd")
    s.add_argument("--cmd", help="custom agent command template, e.g. 'my-agent --prompt-file {prompt_file}'")
    s.add_argument("--model")
    s.add_argument("--label", help="name for this run in reports (default agent@model)")
    s.add_argument("--tasks", help="comma-separated task id prefixes")
    s.add_argument("--repeat", type=int, default=1, help="attempts per task (agents are not deterministic)")
    s.add_argument("-j", "--jobs", type=int, default=1)
    s.add_argument("--timeout", type=int, help="seconds per agent attempt (default 1800)")
    s.add_argument("--cost-regex", help="regex with one group capturing USD cost from agent output")
    s.add_argument("--keep", action="store_true", help="keep task trees for inspection")
    s.add_argument("--dry-run", action="store_true", help="print the prompt and commands for the first task")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("report", help="pass rate, CI, time, cost and diff size per run")
    s.add_argument("runs", nargs="*", help="run ids/prefixes/paths or latest[:label] (default: all)")
    s.add_argument("--format", choices=["text", "md", "json"], default="text")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("compare", help="paired comparison vs a baseline run; exit 3 on a significant drop")
    s.add_argument("baseline")
    s.add_argument("current")
    s.add_argument("--alpha", type=float, default=0.05)
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.set_defaults(fn=cmd_compare)
    return p


def main(argv=None):
    global COLOR
    p = build_parser()
    args = p.parse_args(argv)
    COLOR = args.color == "always" or (args.color == "auto" and not os.environ.get("NO_COLOR")
                                          and (sys.stdout.isatty() or bool(os.environ.get("FORCE_COLOR"))))
    if not getattr(args, "fn", None):
        p.print_help()
        return 0
    try:
        return args.fn(args)
    except (FileNotFoundError, g.GitError) as e:
        print("benchmine: %s" % e, file=sys.stderr)
        return 2
