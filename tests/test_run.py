import json
import os
import shutil
import sys

import pytest

from conftest import PY, STANDIN, TEST_CMD
from benchmine import agents as A
from benchmine import config as C
from benchmine import report as R
from benchmine import runner
from benchmine import tasks as T
from benchmine.cli import main


@pytest.fixture(scope="module")
def mined(demo_repo, tmp_path_factory):
    repo = str(tmp_path_factory.mktemp("m") / "r")
    shutil.copytree(demo_repo, repo)
    assert main(["-C", repo, "mine", "--test-cmd", TEST_CMD, "-j", "4"]) == 0
    return repo


def go(repo, *args):
    return main(["-C", repo, "run", "-j", "4", *args])


def last(repo, label=None):
    return runner.load_run(repo, "latest" + (":" + label if label else ""))


def test_oracle_and_noop(mined):
    assert go(mined, "--agent", "oracle") == 0
    s = R.summarize(last(mined, "oracle"))
    assert s["passed"] == s["attempts"] == 12 and s["median_diff_ratio"] == 1.0
    assert go(mined, "--agent", "noop") == 0
    assert R.summarize(last(mined, "noop"))["passed"] == 0


def test_hidden_tests_win_over_agent_edits(mined):
    tid = T.load_tasks(mined)["tasks"][0]["id"]
    cheat = "for f in tests/*.py; do printf 'def test_ok():\\n    assert True\\n' > \"$f\"; done; " \
            "printf 'def test_ok():\\n    assert True\\n' > " + T.load_tasks(mined)["tasks"][0]["run_tests"][0]
    assert go(mined, "--agent", "cheater", "--cmd", cheat, "--tasks", tid) == 0
    r = last(mined, "cheater")["results"][0]
    assert r["passed"] is False and r["touched_tests"]


def test_agent_sees_no_future_history(mined):
    tid = T.load_tasks(mined)["tasks"][0]["id"]
    probe = "git log --oneline | wc -l > /tmp/bm-probe-%d; git cat-file -t %s >> /tmp/bm-probe-%d 2>&1 || true" % (
        os.getpid(), tid, os.getpid())
    go(mined, "--agent", "probe", "--cmd", probe, "--tasks", tid)
    out = open("/tmp/bm-probe-%d" % os.getpid()).read().split()
    os.remove("/tmp/bm-probe-%d" % os.getpid())
    assert out[0] == "1" and "commit" not in out


def test_timeout_and_cost_regex(mined):
    tid = T.load_tasks(mined)["tasks"][0]["id"]
    assert go(mined, "--agent", "slow", "--cmd", "sleep 5", "--tasks", tid, "--timeout", "1") == 0
    r = last(mined, "slow")["results"][0]
    assert r["timed_out"] and not r["passed"] and r["secs"] < 4
    assert go(mined, "--agent", "talky", "--cmd", "echo '{\"total_cost_usd\": 0.25}'", "--tasks", tid,
              "--cost-regex", r'"total_cost_usd"\s*:\s*([0-9.]+)') == 0
    assert last(mined, "talky")["results"][0]["cost"] == 0.25


def test_standin_profiles_and_compare(mined, capsys):
    sol = mined.rstrip("/").rsplit("/", 1)[0]
    # solutions file sits next to the original demo repo; regenerate a copy beside this one
    src = [p for p in os.listdir(os.path.dirname(os.path.dirname(mined)))]
    assert src  # sanity
    from conftest import EXAMPLES
    import subprocess
    tmp = os.path.join(sol, "gen")
    subprocess.run([PY, os.path.join(EXAMPLES, "make_demo_repo.py"), tmp], check=True, capture_output=True)
    sols = tmp + ".solutions.json"
    for prof, label in (("big-model", "big"), ("big-model-after-update", "big-later"), ("small-model", "small")):
        assert go(mined, "--agent", label, "--cmd", "%s %s %s %s" % (PY, STANDIN, prof, sols)) == 0
    assert R.summarize(last(mined, "big"))["passed"] == 11
    assert R.summarize(last(mined, "small"))["passed"] == 8
    assert R.summarize(last(mined, "big"))["cost"] > R.summarize(last(mined, "small"))["cost"]
    capsys.readouterr()
    assert main(["-C", mined, "compare", "latest:big", "latest:big-later"]) == 3
    out = capsys.readouterr().out
    assert "REGRESSION" in out and "6 tasks got worse" in out
    assert main(["-C", mined, "compare", "latest:big", "latest:small"]) == 0  # 3 drops: not enough for a signal
    assert "no significant change" in capsys.readouterr().out
    assert main(["-C", mined, "report", "--format", "md"]) == 0
    md = capsys.readouterr().out
    assert md.startswith("| agent |") and "| big |" in md
    assert main(["-C", mined, "report", "--format", "json", "latest:big"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["passed"] == 11


def test_setup_failure_is_an_error_not_a_fail(mined, tmp_path):
    cfgp = os.path.join(mined, ".benchmine", "config.json")
    orig = open(cfgp).read()
    cfg = json.loads(orig)
    cfg["setup_cmd"] = "exit 7"
    open(cfgp, "w").write(json.dumps(cfg))
    try:
        tid = T.load_tasks(mined)["tasks"][0]["id"]
        go(mined, "--agent", "oracle", "--label", "broken-setup", "--tasks", tid)
        r = last(mined, "broken-setup")["results"][0]
        assert r["error"].startswith("setup") and R.summarize(last(mined, "broken-setup"))["errors"] == 1
    finally:
        open(cfgp, "w").write(orig)


def test_dry_run_and_presets(mined, capsys):
    assert main(["-C", mined, "run", "--agent", "claude-code", "--model", "opus", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "claude -p <prompt>" in out and "--model opus" in out and "pytest" in out
    kind, cmd, rx = A.resolve("codex")
    assert kind == "cmd" and "{model}" not in cmd and "{prompt_file}" in cmd
    with pytest.raises(ValueError):
        A.resolve("nope")
    assert main(["agents"]) == 0


def test_load_run_refs(mined):
    with pytest.raises(FileNotFoundError):
        runner.load_run(mined, "latest:does-not-exist")
    with pytest.raises(FileNotFoundError):
        runner.load_run(mined, "2026")  # matches several runs: ambiguous
    run = last(mined, "oracle")
    assert runner.load_run(mined, run["run_id"])["run_id"] == run["run_id"]
