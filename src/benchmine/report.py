"""Summaries and baseline comparisons."""
from collections import defaultdict

from . import stats


def summarize(run):
    rs = [r for r in run["results"] if not r.get("error")]
    errors = [r for r in run["results"] if r.get("error")]
    k = sum(1 for r in rs if r["passed"])
    n = len(rs)
    lo, hi = stats.wilson(k, n)
    costs = [r.get("cost") for r in rs if r.get("cost") is not None]
    ratios = []
    for r in rs:
        ref = (r.get("ref_add") or 0) + (r.get("ref_rem") or 0)
        if r["passed"] and ref:
            ratios.append(((r.get("add") or 0) + (r.get("rem") or 0)) / ref)
    passed_cost = sum(c for r, c in ((r, r.get("cost")) for r in rs if r["passed"]) if c is not None)
    return {
        "run_id": run["run_id"], "label": run["label"], "tasks": len({r["task"] for r in rs}),
        "attempts": n, "passed": k, "pass_rate": k / n if n else 0.0, "ci": [lo, hi],
        "median_secs": stats.median([r.get("secs") for r in rs]),
        "cost": sum(costs) if costs else None,
        "cost_per_pass": (sum(costs) / k) if costs and k else None,
        "median_diff_ratio": stats.median(ratios),
        "edited_hidden_tests": sum(1 for r in rs if r.get("touched_tests")),
        "timeouts": sum(1 for r in rs if r.get("timed_out")),
        "errors": len(errors),
        "started": run.get("started"),
    }


def per_task(run):
    acc = defaultdict(lambda: [0, 0])
    for r in run["results"]:
        if r.get("error"):
            continue
        acc[r["task"]][1] += 1
        acc[r["task"]][0] += 1 if r["passed"] else 0
    return {t: k / n for t, (k, n) in acc.items() if n}


def compare(base, cur, alpha=0.05):
    a, b = per_task(base), per_task(cur)
    common = sorted(set(a) & set(b))
    deltas = [b[t] - a[t] for t in common]
    down = [t for t in common if b[t] < a[t]]
    up = [t for t in common if b[t] > a[t]]
    p_drop = stats.sign_test(len(down), len(up))
    p_gain = stats.sign_test(len(up), len(down))
    mean_a = sum(a[t] for t in common) / len(common) if common else 0.0
    mean_b = sum(b[t] for t in common) / len(common) if common else 0.0
    lo, hi = stats.paired_bootstrap(deltas)
    verdict = "no significant change"
    if p_drop < alpha and mean_b < mean_a:
        verdict = "REGRESSION"
    elif p_gain < alpha and mean_b > mean_a:
        verdict = "improvement"
    return {
        "baseline": base["label"], "baseline_run": base["run_id"], "current": cur["label"], "current_run": cur["run_id"],
        "tasks_compared": len(common), "only_in_baseline": sorted(set(a) - set(b)), "only_in_current": sorted(set(b) - set(a)),
        "baseline_rate": mean_a, "current_rate": mean_b, "delta": mean_b - mean_a, "delta_ci": [lo, hi],
        "regressed": down, "improved": up, "p_drop": p_drop, "p_gain": p_gain, "alpha": alpha, "verdict": verdict,
        "needed_for_signal": stats.min_tasks_for(1.0, alpha),
        "same_taskset": base.get("taskset") == cur.get("taskset"),
    }
