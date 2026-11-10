import json
import os

from benchmine import config as C
from benchmine import tasks as T


def test_is_test_path():
    yes = ["tests/test_a.py", "pkg/test_x.py", "a_test.go", "src/foo.test.ts", "web/x.spec.jsx", "src/__tests__/a.js",
           "app/FooTest.java", "spec/models/user_spec.rb", "tests/fixtures/data.json", "conftest.py"]
    no = ["src/app.py", "pkg/testing_utils.go2", "lib/contest.py", "README.md", "src/latest.py"]
    for p in yes:
        assert C.is_test_path(p), p
    for p in no:
        assert not C.is_test_path(p), p


def test_ignored():
    assert C.is_ignored("docs/index.md") and C.is_ignored("package-lock.json") and C.is_ignored("x/CHANGELOG.md")
    assert not C.is_ignored("src/app.py")


def test_detect(tmp_path):
    assert C.detect_test_cmd(str(tmp_path)) is None
    (tmp_path / "pyproject.toml").write_text("")
    assert "pytest" in C.detect_test_cmd(str(tmp_path))
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"vitest": "1"}}))
    assert C.detect_test_cmd(str(tmp_path)) == "npx vitest run {tests}"
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "x"}}))
    assert C.detect_test_cmd(str(tmp_path)) == "npm test --silent"
    (tmp_path / "go.mod").write_text("module x")
    assert C.detect_test_cmd(str(tmp_path)) == "go test {test_pkgs}"


def test_save_and_load(tmp_path):
    cfg = C.load(str(tmp_path))
    cfg["test_cmd"] = "make check"
    C.save(str(tmp_path), cfg)
    assert C.load(str(tmp_path))["test_cmd"] == "make check"
    assert os.path.exists(tmp_path / ".benchmine" / ".gitignore")


def test_clean_message():
    t, pr = T.clean_message("Fix thing (#42)\n\nBody here.\n\nSigned-off-by: a <b>\nCo-authored-by: c <d>\n")
    assert pr == 42 and t == "Fix thing\n\nBody here."
    t, pr = T.clean_message("Merge pull request #7 from me/branch\n\nAdd the widget\n")
    assert pr == 7 and t == "Add the widget"


def test_fill_placeholders():
    task = {"id": "abc", "run_tests": ["pkg/a_test.go", "pkg/sub/b_test.go"], "test_files": []}
    assert T.fill("go test {test_pkgs}", task) == "go test ./pkg ./pkg/sub"
    task = {"id": "abc", "run_tests": ["tests/test a.py"], "test_files": []}
    assert T.fill("pytest {tests} # {task_id}", task) == "pytest 'tests/test a.py' # abc"
