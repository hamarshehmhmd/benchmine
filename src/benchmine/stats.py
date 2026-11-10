"""Small exact statistics, stdlib only."""
import math
import random


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes out of n."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def binom_tail(k, n, p=0.5):
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def sign_test(down, up):
    """One-sided exact sign test (McNemar's exact test when each task ran once).

    down: tasks that got worse, up: tasks that got better. Returns P(at least `down` drops | no real change).
    """
    n = down + up
    if n == 0:
        return 1.0
    return min(1.0, binom_tail(down, n))


def paired_bootstrap(deltas, iters=4000, seed=7):
    """95% CI of the mean of per-task deltas."""
    if not deltas:
        return 0.0, 0.0
    rng = random.Random(seed)
    n = len(deltas)
    means = sorted(sum(rng.choice(deltas) for _ in range(n)) / n for _ in range(iters))
    return means[int(0.025 * iters)], means[int(0.975 * iters) - 1]


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def min_tasks_for(drop, alpha=0.05):
    """Fewest discordant tasks for which `all of them dropped` is significant (rough power hint)."""
    n = 1
    while 0.5 ** n >= alpha:
        n += 1
    return n
