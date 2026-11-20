"""Exact, unresampled procedures of 04 §8: McNemar's test and the Holm correction.

Both use integer and rational arithmetic until the last step, so a p-value is the same on every
machine.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

__all__ = ["McNemar", "holm", "mcnemar_exact"]


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
