"""Cluster bootstrap and sign-flip test (04 §8, O-14) on toy data with known answers."""

from __future__ import annotations

import itertools
import math
import random

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_stats.cluster import cluster_bootstrap, sign_flip_test

rows = st.lists(
    st.tuples(st.sampled_from([0.0, 1 / 3, 0.5, 1.0, -1.0]), st.integers(0, 6)), min_size=1, max_size=40
)


def _split(pairs: list[tuple[float, int]]) -> tuple[list[float], list[int]]:
    return [v for v, _ in pairs], [c for _, c in pairs]


def test_bootstrap_of_constant_data_is_a_point() -> None:
    got = cluster_bootstrap([0.4] * 12, [i % 4 for i in range(12)], seed=1)
    assert (got.estimate, got.low, got.high) == pytest.approx((0.4, 0.4, 0.4))
    assert (got.n_cases, got.n_clusters, got.resamples) == (12, 4, 2000)
    one = cluster_bootstrap([0.0, 1.0, 1.0], ["a", "a", "a"], seed=1)  # one cluster: nothing to resample
    assert (one.estimate, one.low, one.high) == pytest.approx((2 / 3, 2 / 3, 2 / 3))


def test_bootstrap_matches_the_normal_interval_on_a_large_sample() -> None:
    """300 clusters of one case: the interval is close to mean ± 1.96·sd/√n."""
    values = np.random.default_rng(7).normal(10.0, 2.0, 300).tolist()
    got = cluster_bootstrap(values, list(range(300)), seed=1)
    half = 1.96 * float(np.std(values, ddof=1)) / math.sqrt(300)
    assert got.estimate == pytest.approx(float(np.mean(values)))
    assert got.low == pytest.approx(got.estimate - half, abs=0.03)
    assert got.high == pytest.approx(got.estimate + half, abs=0.03)


def test_bootstrap_resamples_clusters_not_cases() -> None:
    """Repeating every case inside its cluster adds no information: the interval is that of the
    cluster-level data, and wider than if the 90 rows were treated as independent."""
    base = [float(i % 2) for i in range(30)]
    alone = cluster_bootstrap(base, list(range(30)), seed=3)
    tripled = cluster_bootstrap(
        [v for v in base for _ in range(3)], [c for c in range(30) for _ in range(3)], seed=3
    )
    assert (tripled.low, tripled.high) == pytest.approx((alone.low, alone.high))
    naive = cluster_bootstrap([v for v in base for _ in range(3)], list(range(90)), seed=3)
    assert tripled.high - tripled.low > naive.high - naive.low


def test_bootstrap_weights_cases_not_clusters() -> None:
    got = cluster_bootstrap([1.0, 1.0, 1.0, 0.0], ["a", "a", "a", "b"], seed=1)
    assert got.estimate == 0.75  # 3 of 4 cases, not the mean of the cluster means (0.5)


@given(rows, st.randoms())
def test_bootstrap_ignores_row_order_and_stays_in_range(
    pairs: list[tuple[float, int]], rnd: random.Random
) -> None:
    values, clusters = _split(pairs)
    got = cluster_bootstrap(values, clusters, seed=5, resamples=200)
    shuffled = list(pairs)
    rnd.shuffle(shuffled)
    assert cluster_bootstrap(*_split(shuffled), seed=5, resamples=200) == got
    assert min(values) - 1e-9 <= got.low <= got.high <= max(values) + 1e-9


def test_sign_flip_matches_the_exact_enumeration() -> None:
    """Eight clusters: all 256 sign vectors can be listed, so the exact p-value is known."""
    d = [0.9, 0.4, 0.7, -0.1, 0.5, 0.3, 0.8, 0.2]
    observed = abs(sum(d)) / 8
    exact = (
        sum(
            abs(sum(s * x for s, x in zip(signs, d, strict=True))) / 8 >= observed - 1e-12
            for signs in itertools.product((1, -1), repeat=8)
        )
        / 256
    )
    got = sign_flip_test(d, list(range(8)), seed=2)
    assert got.statistic == pytest.approx(sum(d) / 8) and (got.n_clusters, got.flips) == (8, 10_000)
    assert abs(got.p_value - exact) < 4 * math.sqrt(exact * (1 - exact) / 10_000)
    assert exact == 4 / 256  # all positive or the one −0.1 flipped, and their mirror images


def test_sign_flip_known_extremes() -> None:
    assert sign_flip_test([0.0] * 6, list(range(6)), seed=2).p_value == 1.0  # no difference at all
    assert sign_flip_test([1.0, 1.0, 1.0], ["a", "a", "a"], seed=2).p_value == 1.0  # one cluster: ± only
    strong = sign_flip_test([1.0] * 20, list(range(20)), seed=2)
    assert strong.p_value < 0.001 and strong.p_value >= 1 / 10_001  # never 0


def test_sign_flip_uses_cluster_means() -> None:
    """Three repetitions that agree count once: 30 rows in 10 clusters test like 10 rows."""
    d = [1.0, 1.0, -1.0, 1.0, 1.0, 1.0, -1.0, 1.0, 1.0, 1.0]
    alone = sign_flip_test(d, list(range(10)), seed=4)
    tripled = sign_flip_test(
        [v for v in d for _ in range(3)], [c for c in range(10) for _ in range(3)], seed=4
    )
    assert tripled == alone
    assert sign_flip_test([0.0, 1.0, 1.0], ["a", "a", "b"], seed=4).statistic == 0.75  # mean of 0.5 and 1


@given(rows, st.randoms())
def test_sign_flip_is_symmetric_and_ignores_row_order(
    pairs: list[tuple[float, int]], rnd: random.Random
) -> None:
    values, clusters = _split(pairs)
    got = sign_flip_test(values, clusters, seed=9, flips=300)
    swapped = sign_flip_test([-v for v in values], clusters, seed=9, flips=300)
    assert (swapped.statistic, swapped.p_value) == (pytest.approx(-got.statistic), got.p_value)
    shuffled = list(pairs)
    rnd.shuffle(shuffled)
    assert sign_flip_test(*_split(shuffled), seed=9, flips=300) == got
    assert 0 < got.p_value <= 1


def test_same_seed_same_result_and_bad_input_is_refused() -> None:
    values, clusters = (
        [0.0, 1.0, 1.0, 0.0, 1.0],
        [("ob", "cart", "cpu"), ("ob", "cart", "cpu"), "b", "c", "c"],
    )
    assert cluster_bootstrap(values, clusters, seed=1) == cluster_bootstrap(values, clusters, seed=1)
    spread = [float(i * i % 17) for i in range(60)]  # many distinct values: the seed shows
    assert cluster_bootstrap(spread, list(range(60)), seed=1) != cluster_bootstrap(
        spread, list(range(60)), seed=2
    )
    for bad in (([], []), ([1.0], ["a", "b"]), ([math.nan], ["a"])):
        with pytest.raises(ValueError):
            cluster_bootstrap(*bad, seed=1)
        with pytest.raises(ValueError):
            sign_flip_test(*bad, seed=1)
