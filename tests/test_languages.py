"""Mining works beyond Python: Go and Node repos (skipped when the toolchain is missing)."""
import shutil

import pytest

from conftest import commit, git
from benchmine import config as C
from benchmine import tasks as T
from benchmine.cli import main


def _repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    return str(r)


@pytest.mark.skipif(not shutil.which("go"), reason="go not installed")
def test_go_repo(tmp_path):
    r = _repo(tmp_path)
    commit(r, "init", {"go.mod": "module example.com/calc\n\ngo 1.21\n",
                       "calc/calc.go": "package calc\n\nfunc Add(a, b int) int { return a + b }\n",
                       "calc/calc_test.go": 'package calc\n\nimport "testing"\n\nfunc TestAdd(t *testing.T) {\n\tif Add(1, 2) != 3 {\n\t\tt.Fatal()\n\t}\n}\n'})
    commit(r, "Add Mul to calc for the pricing code", {
        "calc/calc.go": "package calc\n\nfunc Add(a, b int) int { return a + b }\n\nfunc Mul(a, b int) int { return a * b }\n",
        "calc/mul_test.go": 'package calc\n\nimport "testing"\n\nfunc TestMul(t *testing.T) {\n\tif Mul(3, 4) != 12 {\n\t\tt.Fatal()\n\t}\n}\n'})
    cfg = C.load(r)
    assert cfg["test_cmd"] == "go test {test_pkgs}"
    t = next(t for t, _ in T.candidates(r, cfg) if t)
    assert T.fill(cfg["test_cmd"], t) == "go test ./calc"
    assert T.validate(r, t, cfg) == (True, "fail -> pass")


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_node_repo(tmp_path, capsys):
    r = _repo(tmp_path)
    commit(r, "init", {"package.json": '{"name": "x", "type": "module"}\n',
                       "src/greet.js": "export const greet = (n) => `hi ${n}`;\n",
                       "src/greet.test.js": "import test from 'node:test';\nimport assert from 'node:assert';\n"
                                            "import { greet } from './greet.js';\ntest('g', () => assert.equal(greet('a'), 'hi a'));\n"})
    commit(r, "greet: support a custom greeting word", {
        "src/greet.js": "export const greet = (n, w = 'hi') => `${w} ${n}`;\n",
        "src/greet.test.js": "import test from 'node:test';\nimport assert from 'node:assert';\n"
                             "import { greet } from './greet.js';\ntest('g', () => assert.equal(greet('a'), 'hi a'));\n"
                             "test('w', () => assert.equal(greet('a', 'yo'), 'yo a'));\n"})
    assert main(["-C", r, "init"]) == 0
    assert "node --test {tests}" in capsys.readouterr().out
    assert main(["-C", r, "mine"]) == 0
    assert main(["-C", r, "run", "--agent", "oracle"]) == 0
    assert "1/1 passed" in capsys.readouterr().out
