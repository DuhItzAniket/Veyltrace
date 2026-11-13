"""Unit and property tests of robust_z: scale floor, persistence, onset (03-anomara §3.2, §7)."""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from veyltrace_anomara.robust import persistent_z, robust_scale, robust_z
from veyltrace_anomara.settings import anomara_config
from veyltrace_core.config import load_section_file

RZ = anomara_config(load_section_file("anomara")).robust_z
NS = 1_000_000_000
G = 15 * NS
T0 = 1_767_225_600 * NS  # epoch-aligned to 10 s and 15 s
BASE: tuple[int, int] = (T0, T0 + 600 * NS)
INC: tuple[int, int] = (T0 + 600 * NS, T0 + 1200 * NS)
MICRO = [100.0, 102.0, 98.0, 101.0, 99.0, 100.0, 103.0, 97.0]


def _points(baseline: list[float], incident: list[float]) -> tuple[Any, Any]:
    """Baseline points from T0 and incident points from the incident start, one per 15 s."""
    t = [T0 + k * G for k in range(len(baseline))] + [INC[0] + k * G for k in range(len(incident))]
    return np.asarray(t, dtype=np.int64), np.asarray([*baseline, *incident], dtype=np.float64)


def test_micro_example_is_exact() -> None:
    # 03-anomara §3.2: med 100, MAD 1.5 -> 2.224, IQR 2.5 -> 1.853, eps 1, 2% of 100 = 2 -> s = 2.224.
    eps = RZ.epsilon_for("latency", "ms")
    assert robust_scale(np.asarray(MICRO), eps, RZ) == (100.0, 1.4826 * 1.5)
    score = robust_z(*_points(MICRO, [130.0] * 4), BASE, INC, G, eps, RZ)
    assert score.score == pytest.approx(30.0 / 2.2239, abs=1e-3)
    assert round(score.score_norm, 2) == 2.67
    assert score.score_norm == math.log1p(score.score)
    assert (score.direction, score.onset_ns, score.above_threshold) == ("up", INC[0], True)


def test_flat_error_counter_is_floored_by_epsilon() -> None:
    # 03-anomara §3.2: all-zero errors (unit 1/s) have s_B = 0.1; one error per second gives z = 10.
    eps = RZ.epsilon_for("errors", "1/s")
    score = robust_z(*_points([0.0] * 8, [1.0] * 4), BASE, INC, G, eps, RZ)
    assert (eps, score.score, round(score.score_norm, 2)) == (0.1, 10.0, 2.40)


@pytest.mark.parametrize(
    ("baseline", "eps", "expected"),
    [
        ([0.0, 0.0, 0.0, 10.0, 10.0, 10.0, 20.0, 20.0], 1.0, 1.4826 * 10.0),  # MAD
        ([0.0, 0.0, 0.0, 0.0, 0.0, 10.0, 10.0, 10.0], 1.0, 10.0 / 1.349),  # IQR (MAD = 0, q75 = 10)
        ([5.0] * 8, 0.5, 0.5),  # epsilon
        ([1000.0] * 8, 0.5, 20.0),  # eta * |median|
    ],
    ids=["mad", "iqr", "epsilon", "eta"],
)
def test_scale_floor_picks_each_branch(baseline: list[float], eps: float, expected: float) -> None:
    assert robust_scale(np.asarray(baseline), eps, RZ)[1] == pytest.approx(expected, rel=1e-12)


def test_persistence_rejects_a_single_spike_and_sign_flips() -> None:
    eps = RZ.epsilon_for("latency", "ms")
    spike = robust_z(*_points(MICRO, [100.0, 400.0, 100.0, 100.0]), BASE, INC, G, eps, RZ)
    flips = robust_z(*_points(MICRO, [200.0, 0.0, 200.0, 0.0, 200.0]), BASE, INC, G, eps, RZ)
    held = robust_z(*_points(MICRO, [100.0, 200.0, 200.0, 200.0]), BASE, INC, G, eps, RZ)
    assert (spike.score, spike.direction, spike.onset_ns) == (0.0, "flat", None)
    assert flips.score == 0.0
    assert held.onset_ns == INC[0] + G and held.above_threshold


def test_persistence_needs_p_grid_buckets_not_p_rows() -> None:
    # Rows 1 s apart: [t, t + 3 g) holds many rows, but only the 15 s buckets they cover count.
    t = np.asarray([0, NS, 2 * NS, 20 * NS, 21 * NS, 40 * NS], dtype=np.int64)
    assert persistent_z(t, np.full(6, 5.0), G, 3).tolist() == [5.0, 5.0, 5.0, 0.0, 0.0, 0.0]


def test_down_direction_and_earliest_argmax() -> None:
    score = robust_z(*_points(MICRO, [50.0, 50.0, 50.0, 60.0, 50.0, 50.0, 50.0]), BASE, INC, G, 1.0, RZ)
    assert (score.direction, score.onset_ns) == ("down", INC[0])


@pytest.mark.parametrize(
    ("incident", "expected"),
    [([90.0] * 3 + [110.0] * 3, "down"), ([110.0] * 3 + [90.0] * 3, "up")],
)
def test_an_up_down_tie_at_equal_persistent_z_takes_the_earliest(
    incident: list[float], expected: str
) -> None:
    # 03-anomara §3.2 step 6: |z| = 10/2.2239 for both runs, so only the earliest-argmax rule decides.
    score = robust_z(*_points(MICRO, incident), BASE, INC, G, 1.0, RZ)
    assert score.score == pytest.approx(10.0 / (1.4826 * 1.5))
    assert (score.direction, score.onset_ns) == (expected, INC[0])


def test_short_baseline_or_no_incident_is_flat() -> None:
    # 03-anomara §3.2 step 8: fewer than min_baseline_steps (5) baseline buckets -> score 0.
    for t, x in (_points(MICRO[:4], [130.0] * 4), _points(MICRO, [])):
        score = robust_z(t, x, BASE, INC, G, 1.0, RZ)
        assert (score.score, score.score_norm, score.direction, score.onset_ns) == (0.0, 0.0, "flat", None)
        assert not score.above_threshold


_values = st.lists(st.integers(-1000, 1000).map(float), min_size=8, max_size=30)


@settings(max_examples=60, deadline=None)
@given(_values, _values)
def test_score_is_non_negative_and_matches_the_threshold(
    baseline: list[float], incident: list[float]
) -> None:
    score = robust_z(*_points(baseline, incident), BASE, INC, G, 1.0, RZ)
    assert score.score >= 0.0 and score.score_norm == math.log1p(score.score)
    assert score.above_threshold == (score.score >= score.threshold)
    assert (score.onset_ns is None) == (score.score < score.threshold)


@settings(max_examples=60, deadline=None)
@given(_values, _values, st.integers(1, 10), st.integers(-10_000, 10_000))
def test_affine_invariance_without_eps_and_eta(
    baseline: list[float], incident: list[float], a: int, b: int
) -> None:
    raw = dataclasses.replace(RZ, eta=0.0)
    t, x = _points(baseline, incident)
    one, two = robust_z(t, x, BASE, INC, G, 0.0, raw), robust_z(t, a * x + b, BASE, INC, G, 0.0, raw)
    # Scores only: an exact tie between an up and a down point may resolve differently after rounding.
    assert math.isclose(one.score, two.score, rel_tol=1e-9, abs_tol=1e-12)
