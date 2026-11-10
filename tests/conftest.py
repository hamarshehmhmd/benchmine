import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
EXAMPLES = os.path.join(ROOT, "examples")
STANDIN = os.path.join(EXAMPLES, "agents", "standin.py")
PY = sys.executable
TEST_CMD = "%s -m pytest -q -p no:cacheprovider {tests}" % PY


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


def write(repo, path, text):
    p = os.path.join(str(repo), path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(text)


def commit(repo, msg, files):
    for k, v in files.items():
        if v is None:
            os.remove(os.path.join(str(repo), k))
        else:
            write(repo, k, v)
    git(repo, "add", "-A")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture(scope="session")
def demo_repo(tmp_path_factory):
    d = tmp_path_factory.mktemp("demo") / "textkit"
    subprocess.run([PY, os.path.join(EXAMPLES, "make_demo_repo.py"), str(d)], check=True, capture_output=True)
    return str(d)


@pytest.fixture
def tiny(tmp_path):
    """Empty git repo with a pyproject so the pytest command is detected."""
    r = tmp_path / "tiny"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    commit(r, "init", {"pyproject.toml": "[project]\nname='x'\n", "pkg/__init__.py": "",
                       "pkg/m.py": "def f():\n    return 1\n", "tests/test_m.py": "from pkg.m import f\n\ndef test_f():\n    assert f() == 1\n"})
    return str(r)
