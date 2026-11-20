"""Clustered resampling (04 §8): the percentile cluster bootstrap and the sign-flip permutation test.

RCAEval repeats each (system, root service, fault) several times, and repetitions are not
independent, so both procedures resample whole clusters, never single cases. Every per-case value
is first reduced to its cluster (sum and count, or mean) with `math.fsum` over clusters in sorted
label order, so a result depends on the data and the seed only, never on row order.

Randomness is `numpy.random.default_rng(seed)` with the experiment's seed (04 §9; core's rng module
allows it for bench).
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

__all__ = ["Interval", "PermutationTest", "cluster_bootstrap", "sign_flip_test"]

LEVEL: Final = 0.95  # 04 §8: 95% intervals
RESAMPLES: Final = 2000  # 04 §8: bootstrap resamples
FLIPS: Final = 10_000  # 04 §8: random sign flips
#: Absolute slack when a permuted statistic is compared with the observed one: hits are 0/1, so
#: exact ties are common and must not depend on the order of a float sum (a priori).
TIE_TOLERANCE: Final = 1e-12


@dataclass(frozen=True)
class Interval:
    """A case-weighted mean with its percentile cluster-bootstrap interval."""

    estimate: float
    low: float
    high: float
    n_cases: int
    n_clusters: int
    resamples: int


@dataclass(frozen=True)
class PermutationTest:
    """The mean over clusters of the per-cluster mean difference, and its two-sided p-value."""

    statistic: float
    p_value: float
    n_clusters: int
    flips: int


def _by_cluster(values: Sequence[float], clusters: Sequence[Hashable]) -> tuple[list[float], list[int]]:
    """Per-cluster sum and case count, clusters in sorted label order."""
    if len(values) != len(clusters) or not values:
        raise ValueError("values and clusters must be non-empty and of equal length")
    if not all(math.isfinite(v) for v in values):
        raise ValueError("values must be finite: drop or impute missing cases before testing")
    groups: dict[Hashable, list[float]] = {}
    for value, label in zip(values, clusters, strict=True):
        groups.setdefault(label, []).append(float(value))
    ordered: Any = sorted(groups, key=repr)  # labels are tuples or strings; repr orders any mix
    return [math.fsum(groups[c]) for c in ordered], [len(groups[c]) for c in ordered]


def cluster_bootstrap(
    values: Sequence[float],
    clusters: Sequence[Hashable],
    *,
    seed: int,
    resamples: int = RESAMPLES,
    level: float = LEVEL,
) -> Interval:
    """The mean of `values` over cases with a percentile interval from resampling clusters.

    Each resample draws as many clusters as there are, with replacement, and takes the mean over
    all cases of the drawn clusters. For a paired difference pass the per-case differences.
    """
    if resamples < 1 or not 0 < level < 1:
        raise ValueError("resamples must be >= 1 and level in (0, 1)")
    sums, counts = (np.asarray(x, dtype=np.float64) for x in _by_cluster(values, clusters))
    drawn = np.random.default_rng(seed).integers(0, len(sums), size=(resamples, len(sums)))
    means = sums[drawn].sum(axis=1) / counts[drawn].sum(axis=1)
    low, high = np.quantile(means, [(1 - level) / 2, (1 + level) / 2])
    estimate = math.fsum(sums.tolist()) / len(values)
    return Interval(estimate, float(low), float(high), len(values), len(sums), resamples)


def sign_flip_test(
    differences: Sequence[float], clusters: Sequence[Hashable], *, seed: int, flips: int = FLIPS
) -> PermutationTest:
    """Two-sided cluster sign-flip test of "the mean paired difference is zero" (04 §8 primary test).

    `d_c` is the mean of a cluster's per-case differences (hit_A − hit_B), the statistic the mean
    of `d_c`. Under the null each cluster's sign is exchangeable, so `flips` random sign vectors
    give the reference distribution. The p-value is (1 + #{|T*| ≥ |T|}) / (flips + 1): the observed
    labelling counts as one draw, so p is never 0.
    """
    if flips < 1:
        raise ValueError("flips must be >= 1")
    sums, counts = _by_cluster(differences, clusters)
    d = np.asarray([s / n for s, n in zip(sums, counts, strict=True)], dtype=np.float64)
    observed = math.fsum(d.tolist()) / len(d)
    signs = np.random.default_rng(seed).integers(0, 2, size=(flips, len(d))) * 2 - 1
    permuted = np.abs(signs @ d) / len(d)
    extreme = int(np.count_nonzero(permuted >= abs(observed) - TIE_TOLERANCE))
    return PermutationTest(observed, (1 + extreme) / (flips + 1), len(d), flips)
