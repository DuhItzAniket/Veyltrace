"""Exact, unresampled procedures of 04 §8: McNemar's test, the Holm correction and the
Clopper–Pearson binomial interval.

Both use integer and rational arithmetic until the last step, so a p-value is the same on every
machine.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Final

__all__ = ["BinomialInterval", "McNemar", "clopper_pearson", "holm", "mcnemar_exact"]

LEVEL: Final = 0.95  # 04 §8: 95% intervals
#: Bounds are found on the grid k / 2**GRID_BITS, so they are exact to about 1e-12, well below the
#: 9 decimals summary.json keeps, and identical on every machine (a priori).
GRID_BITS: Final = 40


@dataclass(frozen=True)
class McNemar:
    """Discordant pair counts and the exact two-sided p-value."""

    only_a: int  # cases A hit and B missed
    only_b: int  # cases B hit and A missed
    p_value: float


def mcnemar_exact(hits_a: Sequence[bool], hits_b: Sequence[bool]) -> McNemar:
    """Exact McNemar on case-level discordant pairs, unclustered (04 §8 secondary test).

    Under the null a discordant pair favours A or B with probability ½, so with `n` discordant
    pairs and `k` the smaller count, p = min(1, 2·P(Bin(n, ½) ≤ k)); p = 1 without discordant pairs.
    Hits must be booleans: mean hits over seeds (LLM arms) go to the sign-flip test, not here.
    """
    if len(hits_a) != len(hits_b):
        raise ValueError("hits_a and hits_b must have equal length")
    if not all(isinstance(h, bool) for h in (*hits_a, *hits_b)):
        raise ValueError("McNemar needs boolean hits")
    only_a = sum(a and not b for a, b in zip(hits_a, hits_b, strict=True))
    only_b = sum(b and not a for a, b in zip(hits_a, hits_b, strict=True))
    n, k = only_a + only_b, min(only_a, only_b)
    tail = Fraction(sum(math.comb(n, i) for i in range(k + 1)), 2**n)
    return McNemar(only_a, only_b, float(min(Fraction(1), 2 * tail)))


def holm(p_values: Sequence[float]) -> list[float]:
    """Holm-adjusted p-values in the order given (04 §8: within one pre-declared family).

    The i-th smallest of `m` p-values is multiplied by (m − i + 1), capped at 1, and made
    monotone, so an adjusted value is never below that of a smaller raw p-value. Reject where
    the adjusted value is at most the test level. Equal p-values get equal adjusted values.
    """
    if not all(0.0 <= p <= 1.0 for p in p_values):
        raise ValueError("p-values must lie in [0, 1]")
    m = len(p_values)
    order = sorted(range(m), key=lambda i: (p_values[i], i))
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted


@dataclass(frozen=True)
class BinomialInterval:
    """A proportion `successes / n` with its exact (Clopper–Pearson) interval."""

    estimate: float
    low: float
    high: float
    successes: int
    n: int
    level: float


def _lower_tail(k: int, n: int, a: int, scale: int) -> int:
    """`scale**n · P(X <= k)` for X ~ Bin(n, a / scale), as an integer (-1 <= k <= n)."""
    b, acc, power = scale - a, 0, 1  # Horner in a, with b**(k - i) built up one factor at a time
    for i in range(k, -1, -1):
        acc = acc * a + math.comb(n, i) * power
        power *= b
    return acc * b ** (n - k) if k >= 0 else 0


def clopper_pearson(successes: int, n: int, *, level: float = LEVEL) -> BinomialInterval:
    """The exact two-sided binomial interval for `successes` out of `n` independent trials (04 §8:
    proportions without clusters, e.g. decoy flips H2b, permutation invariance H2c, replay rates).

    With alpha = 1 - level: `low` is 0 when no trial succeeded, else the p with
    P(X >= successes) = alpha/2; `high` is 1 when every trial succeeded, else the p with
    P(X <= successes) = alpha/2. The interval covers the true proportion with probability at
    least `level` for every p, which the percentile bootstrap does not at 0 or n successes.
    Each bound is the outermost point of a 2**-GRID_BITS grid still inside that equation, found by
    bisection with integer tail sums, so it is never too narrow and has no platform rounding.
    """
    if (
        isinstance(successes, bool)
        or isinstance(n, bool)
        or not isinstance(successes, int)
        or not isinstance(n, int)
    ):
        raise ValueError("successes and n must be integers")
    if n < 1 or not 0 <= successes <= n:
        raise ValueError("need n >= 1 and 0 <= successes <= n")
    if not 0 < level < 1:
        raise ValueError("level must be in (0, 1)")
    half = (1 - Fraction(repr(level))) / 2  # alpha/2 as the decimal the caller wrote
    scale = 1 << GRID_BITS
    limit = half * scale**n

    def last_grid_point(inside: Callable[[int], bool]) -> int:
        """The largest a in [0, scale] with inside(a), for an `inside` that is true up to a point."""
        lo, hi = 0, scale  # inside(lo) holds, inside(hi) may not
        if inside(hi):
            return hi
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if inside(mid) else (lo, mid)
        return lo

    # P(X >= x | p) grows with p: the lower bound is the last p where it is still <= alpha/2.
    full = scale**n
    low = (
        last_grid_point(lambda a: full - _lower_tail(successes - 1, n, a, scale) <= limit)
        if successes > 0
        else 0
    )
    # P(X <= x | p) falls with p: the upper bound is the first p where it is <= alpha/2.
    high = (
        last_grid_point(lambda a: _lower_tail(successes, n, a, scale) > limit) + 1 if successes < n else scale
    )
    return BinomialInterval(successes / n, low / scale, min(high, scale) / scale, successes, n, level)
