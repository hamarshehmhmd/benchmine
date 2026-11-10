import pytest

from benchmine import report as R
from benchmine import stats as S


def test_wilson():
    lo, hi = S.wilson(11, 12)
    assert lo == pytest.approx(0.646, abs=0.002) and hi == pytest.approx(0.985, abs=0.002)
    assert S.wilson(0, 0) == (0.0, 0.0)
    assert S.wilson(0, 10)[0] == 0.0


def test_sign_test():
    assert S.sign_test(0, 0) == 1.0
    assert S.sign_test(5, 0) == pytest.approx(1 / 32)
    assert S.sign_test(3, 0) == pytest.approx(1 / 8)
    assert S.sign_test(6, 2) == pytest.approx(37 / 256)
    assert S.min_tasks_for(1.0, 0.05) == 5


def test_bootstrap_and_median():
    lo, hi = S.paired_bootstrap([-1.0] * 6 + [0.0] * 6)
    assert -1.0 <= lo < -0.5 < hi <= 0.0
    assert S.median([3, None, 1, 2]) == 2 and S.median([]) is None


def run(label, rates):
    res = []
    for t, (k, n) in rates.items():
        res += [{"task": t, "attempt": i + 1, "passed": i < k} for i in range(n)]
    return {"run_id": label, "label": label, "results": res, "taskset": "x"}


def test_compare_with_repeats():
    base = run("a", {"t%d" % i: (3, 3) for i in range(8)})
    cur = run("b", {**{"t%d" % i: (1, 3) for i in range(6)}, "t6": (3, 3), "t7": (3, 3), "t9": (0, 3)})
    c = R.compare(base, cur)
    assert c["tasks_compared"] == 8 and c["only_in_current"] == ["t9"]
    assert len(c["regressed"]) == 6 and c["verdict"] == "REGRESSION"
    assert c["delta"] == pytest.approx(-0.5)
    c2 = R.compare(cur, base)
    assert c2["verdict"] == "improvement"
