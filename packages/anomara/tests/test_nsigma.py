"""Unit and property tests of the N-Sigma detector (03-anomara §3.3, §7)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from veyltrace_anomara.robust import nsigma
from veyltrace_anomara.settings import anomara_config
from veyltrace_core.config import load_section_file

CFG = anomara_config(load_section_file("anomara"))
NS = 1_000_000_000
G = 15 * NS
T0 = 1_767_225_600 * NS
BASE: tuple[int, int] = (T0, T0 + 600 * NS)
INC: tuple[int, int] = (T0 + 600 * NS, T0 + 1200 * NS)
MICRO = [100.0, 102.0, 98.0, 101.0, 99.0, 100.0, 103.0, 97.0]


def _points(baseline: list[float], incident: list[float]) -> tuple[Any, Any]:
    t = [T0 + k * G for k in range(len(baseline))] + [INC[0] + k * G for k in range(len(incident))]
    return np.asarray(t, dtype=np.int64), np.asarray([*baseline, *incident], dtype=np.float64)


def _nsigma(baseline: list[float], incident: list[float], eps: float = 1.0) -> Any:
    return nsigma(*_points(baseline, incident), BASE, INC, G, eps, CFG.robust_z, CFG.nsigma)


def test_zero_scale_convention_and_floored_norm() -> None:
    # sigma_B = 0 -> unit scale (scikit-learn, as RCAEval's N-Sigma), so the score is the raw deviation.
    score = _nsigma([5.0] * 8, [8.0, 5.0, 5.0], eps=0.5)
    assert (score.score, score.direction, score.onset_ns) == (3.0, "up", INC[0])
    assert score.score_norm == math.log1p(3.0 / 0.5)  # floored scale max(0, eps 0.5, 2% of 5)


def test_a_non_dyadic_constant_baseline_has_unit_scale() -> None:
    # 600 one-second rows of 0.3 (the RCAEval shape): std_B is float noise, not 0, and must not be a scale.
    t = np.asarray([T0 + k * NS for k in range(1200)], dtype=np.int64)
    x = np.full(1200, 0.3)
    assert float(np.std(x[:600])) > 0.0  # the case under test: rounding noise in the std
    same = nsigma(t, x, BASE, INC, G, 1.0, CFG.robust_z, CFG.nsigma)
    x[600:] = 0.3000001
    tiny = nsigma(t, x, BASE, INC, G, 1.0, CFG.robust_z, CFG.nsigma)
    assert same.score < 1e-12 and not same.above_threshold
    assert tiny.score == pytest.approx(1e-7, rel=1e-6)
    assert (tiny.above_threshold, tiny.onset_ns) == (False, None)


def test_raw_max_without_persistence() -> None:
    score = _nsigma(MICRO, [100.0, 400.0, 100.0])
    assert score.score == pytest.approx(300.0 / float(np.std(MICRO)))
    assert (score.direction, score.onset_ns) == ("up", INC[0] + G)


def test_down_and_short_baseline() -> None:
    assert _nsigma(MICRO, [100.0, 0.0]).direction == "down"
    short = _nsigma(MICRO[:4], [400.0] * 3)
    assert (short.score, short.direction, short.onset_ns, short.above_threshold) == (0.0, "flat", None, False)


_values = st.lists(st.integers(-1000, 1000).map(float), min_size=8, max_size=30)


@settings(max_examples=60, deadline=None)
@given(_values, _values)
def test_score_is_non_negative_and_matches_the_threshold(
    baseline: list[float], incident: list[float]
) -> None:
    score = _nsigma(baseline, incident)
    assert score.score >= 0.0 and score.score_norm >= 0.0
    assert score.above_threshold == (score.score >= score.threshold)
    assert (score.onset_ns is None) == (score.score < score.threshold)
