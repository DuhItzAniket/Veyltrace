"""Unit and property tests of the BOCPD onset detector (03-anomara §3.4, §7)."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from veyltrace_anomara.bocpd import Standardised, bocpd, run_length_posterior
from veyltrace_anomara.series import grid
from veyltrace_anomara.settings import anomara_config
from veyltrace_core.config import load_section_file

CFG = anomara_config(load_section_file("anomara"))
B = CFG.bocpd
NS = 1_000_000_000
G = 15 * NS
T0 = 1_767_225_600 * NS
N_BASE, N_INC = 72, 40  # an 18 min baseline and a 10 min incident on a 15 s grid
INC: tuple[int, int] = (T0 + N_BASE * G, T0 + (N_BASE + N_INC) * G)
#: A deterministic noise pattern (no RNG in tests either: the expected index must not move).
WIGGLE = [0.3, -0.2, 0.1, -0.4, 0.2, 0.0, -0.1, 0.4, -0.3, 0.1]


def _y(step_at: int, size: float, n: int = N_BASE + N_INC) -> np.ndarray:
    return np.asarray([WIGGLE[k % 10] + (size if k >= step_at else 0.0) for k in range(n)])


def test_posterior_sums_to_one_every_step() -> None:
    y = _y(80, 6.0)[None, :]
    observed = np.ones_like(y, dtype=bool)
    observed[0, 30:33] = False  # unobserved steps advance without a likelihood term
    _, _, history = run_length_posterior(y, observed, B, keep=True)
    assert len(history) == y.shape[1]
    for log_r in history:
        assert math.isclose(float(np.exp(log_r).sum()), 1.0, rel_tol=1e-12)


def test_truncation_folds_long_runs_and_keeps_the_mass() -> None:
    short = dataclasses.replace(B, r_max=5)
    y = _y(10_000, 0.0, n=40)[None, :]
    _, _, history = run_length_posterior(y, np.ones_like(y, dtype=bool), short, keep=True)
    assert history[-1].shape == (1, 6)
    assert math.isclose(float(np.exp(history[-1]).sum()), 1.0, rel_tol=1e-12)
    assert float(np.exp(history[-1][0, -1])) > 0.5  # most mass sits in the folded "≥ R_max" bucket


def test_a_mean_step_is_found_at_its_grid_index() -> None:
    cp, rhat, _ = run_length_posterior(_y(80, 6.0)[None, :], np.ones((1, N_BASE + N_INC), dtype=bool), B)
    hits = [t for t in range(N_BASE, N_BASE + N_INC) if cp[0, t] >= B.threshold]
    # The first incident step with P(r <= m) >= 0.5, moved back by its most likely run length.
    assert hits and hits[0] - int(rhat[0, hits[0]]) == 80


def _standardised(values: np.ndarray) -> Standardised:
    t = T0 + np.arange(values.size, dtype=np.int64) * G
    g = grid(t, values.astype(np.float64), G, (T0, INC[1]))
    return Standardised(g, 0.0, 1.0)


def test_bocpd_scores_onset_and_direction() -> None:
    up, down, flat = (_standardised(_y(80, s)) for s in (6.0, -6.0, 0.0))
    s_up, s_down, s_flat = bocpd([up, down, flat], INC, 3, B)
    assert (s_up.onset_ns, s_up.direction, s_up.above_threshold) == (T0 + 80 * G, "up", True)
    assert (s_down.onset_ns, s_down.direction) == (T0 + 80 * G, "down")
    assert (s_flat.onset_ns, s_flat.direction, s_flat.above_threshold) == (None, "flat", False)
    assert s_up.score_norm == math.log1p(s_up.score) and 0.0 <= s_flat.score < B.threshold


def test_stacking_does_not_change_a_series_result() -> None:
    one = _standardised(_y(85, 4.0))
    alone = bocpd([one], INC, 3, B)[0]
    stacked = bocpd([_standardised(_y(75, -3.0)), one, _standardised(_y(0, 0.0))], INC, 3, B)[1]
    assert (alone.score, alone.onset_ns, alone.direction) == (
        stacked.score,
        stacked.onset_ns,
        stacked.direction,
    )


@settings(max_examples=25, deadline=None)
@given(st.lists(st.floats(-5, 5, allow_nan=False), min_size=20, max_size=60))
def test_score_is_a_probability_and_matches_the_threshold(values: list[float]) -> None:
    n = len(values)
    inc: tuple[int, int] = (T0 + (n // 2) * G, T0 + n * G)
    (score,) = bocpd([_standardised(np.asarray(values))], inc, 3, B)
    assert 0.0 <= score.score <= 1.0 + 1e-12
    assert score.above_threshold == (score.score >= B.threshold) == (score.onset_ns is not None)


@pytest.mark.parametrize("r_max", [5, 200])
def test_no_incident_bucket_is_flat(r_max: int) -> None:
    (score,) = bocpd([_standardised(_y(10, 5.0, n=20))], (T0 + 100 * G, T0 + 100 * G), 3,
                     dataclasses.replace(B, r_max=r_max))  # fmt: skip
    assert (score.score, score.direction, score.onset_ns) == (0.0, "flat", None)


def test_a_series_with_no_incident_points_is_flat() -> None:
    # 03-anomara §6: a shift at the end of the baseline, then no incident points at all.
    values = _y(N_BASE - 1, 8.0, n=N_BASE)
    t = T0 + np.arange(values.size, dtype=np.int64) * G
    g = grid(t, values, G, (T0, INC[1]))
    assert g.within(INC).any() and not (g.within(INC) & g.observed).any()
    (score,) = bocpd([Standardised(g, 0.0, 1.0)], INC, 3, B)
    assert (score.score, score.direction, score.onset_ns, score.above_threshold) == (0.0, "flat", None, False)
