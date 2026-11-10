import os

from conftest import TEST_CMD, commit, git
from benchmine import config as C
from benchmine import tasks as T
from benchmine.cli import main


def cfg_for(root):
    cfg = C.load(root)
    cfg["test_cmd"] = TEST_CMD
    return cfg


def test_candidates_on_demo_repo(demo_repo):
    cfg = cfg_for(demo_repo)
    got = list(T.candidates(demo_repo, cfg))
    tasks = [t for t, _ in got if t]
    skipped = dict(w for _, w in got if w)
    assert len(tasks) == 12
    reasons = set(skipped.values())
    assert "root commit" in reasons and "no test changes" in reasons and "tests only, no code change" in reasons
    assert any(r.startswith("skipped subject: Bump") for r in reasons)
    t = next(t for t in tasks if t["subject"] == "Add max_len to slugify")
    assert t["pr"] == 10 and "Co-authored-by" not in t["prompt"] and "trailing dash" in t["prompt"]
    assert t["source_files"] == ["textkit/core.py"] and t["run_tests"] == ["tests/test_slug_len.py"]
    assert (t["ref_add"], t["ref_rem"]) == (5, 3)


def test_validate_accepts_and_rejects(tiny):
    cfg = cfg_for(tiny)
    commit(tiny, "Make f return 2 when asked nicely", {
        "pkg/m.py": "def f(nice=False):\n    return 2 if nice else 1\n",
        "tests/test_nice.py": "from pkg.m import f\n\ndef test_nice():\n    assert f(nice=True) == 2\n"})
    commit(tiny, "Refactor f without changing behaviour", {
        "pkg/m.py": "def f(nice=False):\n    if nice:\n        return 2\n    return 1\n",
        "tests/test_same.py": "from pkg.m import f\n\ndef test_same():\n    assert f() == 1\n"})
    commit(tiny, "Add g but with a broken test that never passes", {
        "pkg/g.py": "def g():\n    return 3\n",
        "tests/test_g.py": "from pkg.g import g\n\ndef test_g():\n    assert g() == 4\n"})
    tasks = {t["subject"]: t for t, _ in T.candidates(tiny, cfg) if t}
    assert T.validate(tiny, tasks["Make f return 2 when asked nicely"], cfg) == (True, "fail -> pass")
    ok, why = T.validate(tiny, tasks["Refactor f without changing behaviour"], cfg)
    assert not ok and "already pass" in why
    ok, why = T.validate(tiny, tasks["Add g but with a broken test that never passes"], cfg)
    assert not ok and "fail even with the real change" in why


def test_deleted_test_file_and_overlay(tiny, tmp_path):
    commit(tiny, "Rename test and change f to return 5 for everyone", {
        "pkg/m.py": "def f():\n    return 5\n", "tests/test_m.py": None,
        "tests/test_m2.py": "from pkg.m import f\n\ndef test_f():\n    assert f() == 5\n"})
    cfg = cfg_for(tiny)
    t = next(t for t, _ in T.candidates(tiny, cfg) if t)
    assert set(t["test_files"]) == {"tests/test_m.py", "tests/test_m2.py"}
    assert t["run_tests"] == ["tests/test_m2.py"]
    res = T.validate(tiny, t, cfg)
    assert res[0], res
    dest = tmp_path / "tree"
    dest.mkdir()
    (dest / "tests").mkdir()
    (dest / "tests" / "test_m.py").write_text("old")
    T.overlay(tiny, t["ref"], str(dest), t["test_files"])
    assert not (dest / "tests" / "test_m.py").exists() and (dest / "tests" / "test_m2.py").exists()


def test_merge_commit_prompt_uses_branch_messages(tiny):
    git(tiny, "checkout", "-q", "-b", "feature")
    commit(tiny, "Teach f to double\n\nf(x) now returns 2*x; without x it still returns 1.", {
        "pkg/m.py": "def f(x=None):\n    return 1 if x is None else 2 * x\n",
        "tests/test_double.py": "from pkg.m import f\n\ndef test_double():\n    assert f(4) == 8\n"})
    git(tiny, "checkout", "-q", "main")
    git(tiny, "-c", "commit.gpgsign=false", "merge", "-q", "--no-ff", "feature", "-m",
        "Merge pull request #5 from me/feature\n\nDouble support")
    cfg = cfg_for(tiny)
    t = next(t for t, _ in T.candidates(tiny, cfg) if t)
    assert t["pr"] == 5
    assert "Double support" in t["prompt"] and "returns 2*x" in t["prompt"]
    assert T.validate(tiny, t, cfg)[0]


def test_cli_mine_and_tasks(demo_repo, tmp_path, capsys):
    import shutil
    repo = str(tmp_path / "r")
    shutil.copytree(demo_repo, repo)
    assert main(["-C", repo, "mine", "--test-cmd", TEST_CMD, "--max-tasks", "3", "-v"]) == 0
    out = capsys.readouterr().out
    assert "saved 3 tasks" in out and "tests only" in out
    assert main(["-C", repo, "tasks"]) == 0
    assert "3 tasks" in capsys.readouterr().out
    body = T.load_tasks(repo)
    assert main(["-C", repo, "tasks", body["tasks"][0]["id"][:6]]) == 0
    assert "Hidden tests will check" in capsys.readouterr().out


def test_cli_mine_without_test_cmd(tmp_path):
    import pytest
    r = tmp_path / "x"
    r.mkdir()
    git(r, "init", "-q")
    commit(r, "init", {"a.txt": "a"})
    with pytest.raises(SystemExit) as e:
        main(["-C", str(r), "mine"])
    assert "no test command" in str(e.value)


def test_not_a_repo(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        main(["-C", str(tmp_path), "tasks"])


def test_same_size_edit_in_same_second_is_not_hidden_by_pyc(tiny):
    # pkg/m.py changes "return 1" -> "return 7": same size, and validation runs both within one second
    commit(tiny, "Change f to return 7 for the new pricing", {
        "pkg/m.py": "def f():\n    return 7\n",
        "tests/test_m.py": "from pkg.m import f\n\ndef test_f():\n    assert f() == 7\n"})
    cfg = cfg_for(tiny)
    t = next(t for t, _ in T.candidates(tiny, cfg) if t)
    for _ in range(3):
        assert T.validate(tiny, t, cfg) == (True, "fail -> pass")
