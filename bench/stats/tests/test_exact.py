"""Exact McNemar and Holm (04 §8, O-14) on worked examples with known answers."""

from __future__ import annotations

import itertools
import math
import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_stats.exact import clopper_pearson, holm, mcnemar_exact


def _pairs(only_a: int, only_b: int, both: int = 3, neither: int = 2) -> tuple[list[bool], list[bool]]:
    a = [True] * only_a + [False] * only_b + [True] * both + [False] * neither
    b = [False] * only_a + [True] * only_b + [True] * both + [False] * neither
    return a, b


@pytest.mark.parametrize(
    ("only_a", "only_b", "p"),
    [
        (0, 0, 1.0),  # no discordant pair
        (1, 0, 1.0),  # 2 · (1/2)
        (5, 0, 2 / 32),  # 2 · (1/2)^5
        (6, 2, 74 / 256),  # 2 · (1 + 8 + 28) / 2^8
        (5, 5, 1.0),  # balanced: capped at 1
        (10, 1, 24 / 2048),  # 2 · (1 + 11) / 2^11
    ],
)
def test_mcnemar_worked_examples(only_a: int, only_b: int, p: float) -> None:
    got = mcnemar_exact(*_pairs(only_a, only_b))
    assert (got.only_a, got.only_b, got.p_value) == (only_a, only_b, p)
    assert (
        mcnemar_exact(*_pairs(only_a, only_b, both=40, neither=0)).p_value == p
    )  # concordant pairs do not count


@given(st.lists(st.tuples(st.booleans(), st.booleans()), max_size=60), st.randoms())
def test_mcnemar_is_symmetric_and_order_free(pairs: list[tuple[bool, bool]], rnd: random.Random) -> None:
    a, b = [x for x, _ in pairs], [y for _, y in pairs]
    got = mcnemar_exact(a, b)
    assert mcnemar_exact(b, a).p_value == got.p_value and 0 < got.p_value <= 1
    rnd.shuffle(pairs)
    assert mcnemar_exact([x for x, _ in pairs], [y for _, y in pairs]) == got


def test_mcnemar_refuses_fractional_hits_and_unequal_lengths() -> None:
    with pytest.raises(ValueError):
        mcnemar_exact([True, False], [True])
    with pytest.raises(ValueError):
        mcnemar_exact([1 / 3, True], [True, False])  # type: ignore[list-item]  # the refused input


def test_holm_worked_example() -> None:
    """Four tests: sorted 0.005, 0.01, 0.03, 0.04 times 4, 3, 2, 1, then made monotone."""
    assert holm([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert holm([0.5, 0.9]) == [1.0, 1.0]  # capped
    assert holm([0.02]) == [0.02] and holm([]) == []
    assert holm([0.01, 0.01]) == [0.02, 0.02]  # ties share a value
    with pytest.raises(ValueError):
        holm([0.2, 1.5])


@given(st.lists(st.floats(0, 1), min_size=1, max_size=13), st.randoms())
def test_holm_properties(p: list[float], rnd: random.Random) -> None:
    adjusted = holm(p)
    assert all(raw <= adj <= 1 for raw, adj in zip(p, adjusted, strict=True))
    assert all(
        a1 <= a2
        for (p1, a1), (p2, a2) in zip(
            sorted(zip(p, adjusted, strict=True)), sorted(zip(p, adjusted, strict=True))[1:], strict=False
        )
        if p1 <= p2
    )
    assert min(adjusted) == pytest.approx(min(1.0, len(p) * min(p)))  # the smallest is Bonferroni
    order = list(range(len(p)))
    rnd.shuffle(order)
    assert holm([p[i] for i in order]) == pytest.approx([adjusted[i] for i in order])


# --- exact binomial interval (04 §8 "exact binomial CIs otherwise": H2b, H2c, RQ6 replay rates) ---


def _tail_ge(x: int, n: int, p: float) -> float:
    return math.fsum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(x, n + 1))


@pytest.mark.parametrize(
    ("x", "n", "low", "high"),
    [
        (0, 10, 0.0, 1 - 0.025 ** (1 / 10)),  # closed form when x = 0
        (10, 10, 0.025 ** (1 / 10), 1.0),  # and when x = n
        (1, 1, 0.025, 1.0),
        (0, 1, 0.0, 0.975),
        (5, 10, 0.187086028, 0.812913972),  # textbook value
        (267, 267, 0.025 ** (1 / 267), 1.0),  # H2c on RE2: every case invariant
    ],
)
def test_clopper_pearson_known_values(x: int, n: int, low: float, high: float) -> None:
    got = clopper_pearson(x, n)
    assert (got.low, got.high) == pytest.approx((low, high), abs=1e-9)
    assert (got.estimate, got.successes, got.n, got.level) == (x / n, x, n, 0.95)


@given(st.integers(1, 120).flatmap(lambda n: st.tuples(st.integers(0, n), st.just(n))))
def test_clopper_pearson_solves_its_tail_equations(xn: tuple[int, int]) -> None:
    x, n = xn
    got = clopper_pearson(x, n)
    assert 0.0 <= got.low <= x / n <= got.high <= 1.0
    if x > 0:  # P(X >= x | low) = alpha / 2
        assert _tail_ge(x, n, got.low) == pytest.approx(0.025, abs=1e-9)
    if x < n:  # P(X <= x | high) = alpha / 2
        assert 1 - _tail_ge(x + 1, n, got.high) == pytest.approx(0.025, abs=1e-9)
    mirror = clopper_pearson(n - x, n)
    assert (got.low, got.high) == pytest.approx((1 - mirror.high, 1 - mirror.low), abs=1e-11)


def test_clopper_pearson_is_monotone_and_widens_with_level() -> None:
    bounds = [clopper_pearson(x, 30) for x in range(31)]
    assert all(a.low <= b.low and a.high <= b.high for a, b in itertools.pairwise(bounds))
    narrow, wide = clopper_pearson(12, 30, level=0.90), clopper_pearson(12, 30, level=0.99)
    assert wide.low < narrow.low < narrow.high < wide.high


def test_clopper_pearson_refuses_bad_input() -> None:
    for x, n in ((-1, 5), (6, 5), (0, 0)):
        with pytest.raises(ValueError, match="0 <= successes <= n"):
            clopper_pearson(x, n)
    with pytest.raises(ValueError, match="integers"):
        clopper_pearson(True, 5)
    with pytest.raises(ValueError, match="level"):
        clopper_pearson(1, 5, level=1.0)
