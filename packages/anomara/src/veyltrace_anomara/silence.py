"""`silence`: a series that drops to zero or disappears is an anomaly, never health (03-anomara §3.5).

Why: an agent that read a dead service's flat-zero metrics as "healthy" blamed the wrong service
(verified_agents §Q2), and 02 §6.3 requires silent services to be flagged. Two forms, both on the
grid series: zero-silence for count-like signals (`silence.zero_signals`) whose baseline was mostly
non-zero, and absence-silence for any series whose baseline was well covered. Buckets after the last
observation of the same source anywhere in the case never count, so a truncated case is not
"everything went silent".
"""

from __future__ import annotations

import math

import numpy as np

from veyltrace_anomara.robust import Score
from veyltrace_anomara.series import BoolArray, IntArray, Series, Window, grid
from veyltrace_anomara.settings import SilenceConfig

__all__ = ["SILENCE_THRESHOLD", "silence"]

#: Definitional, not tuned: the score is the longest qualifying run in units of L, and a run
#: qualifies only when it lasts at least L (03-anomara §3.5).
SILENCE_THRESHOLD = 1.0


def _runs(mask: BoolArray, starts: IntArray, step: int, length: int) -> list[tuple[int, int]]:
    """(start_ns, duration_ns) of every maximal run of consecutive True buckets lasting ≥ length."""
    if not mask.any():
        return []
    edges = np.diff(np.concatenate(([0], mask.astype(np.int64), [0])))
    begins, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    return [
        (int(starts[b]), int((e - b) * step))
        for b, e in zip(begins, ends, strict=True)
        if (e - b) * step >= length
    ]


def silence(
    series: Series,
    step: int,
    baseline: Window,
    incident: Window,
    source_end_ns: int | None,
    cfg: SilenceConfig,
) -> Score:
    """Score = longest qualifying run / L (0 if none); onset = start of the first qualifying run.

    `source_end_ns` is the last `t_ns` of the series' source anywhere in the case (None: the source
    has no point, so nothing can be absent). Direction is `down` (03-anomara §3.5).
    """
    g = grid(series.t, series.x, step, (baseline[0], incident[1]))
    length = max(cfg.min_gap_ns, cfg.min_steps * step)
    in_b, in_i = g.within(baseline), g.within(incident)
    runs: list[tuple[int, int]] = []
    seen_b = g.observed & in_b
    if series.signal in cfg.zero_signals and seen_b.any():
        zero_share = float(np.count_nonzero(g.values[seen_b] == 0.0)) / float(np.count_nonzero(seen_b))
        if zero_share <= cfg.max_baseline_zero_share:
            runs += _runs(g.observed & (g.values == 0.0) & in_i, g.starts, step, length)
    n_b = int(np.count_nonzero(in_b))
    if n_b and np.count_nonzero(seen_b) / n_b >= cfg.min_baseline_coverage and source_end_ns is not None:
        counted = in_i & (g.starts <= source_end_ns)
        runs += _runs(counted & ~g.observed, g.starts, step, length)
    if not runs:
        return Score(0.0, 0.0, "down", None, SILENCE_THRESHOLD)
    score = max(d for _, d in runs) / length
    return Score(score, math.log1p(score), "down", min(s for s, _ in runs), SILENCE_THRESHOLD)
