"""`robust_z` and `nsigma`: how far the incident deviates from the baseline (03-anomara §3.2–3.3).

Why a multi-part scale floor: dividing by a near-zero MAD made BARO rank a wrong metric at
4.6 × 10¹⁴ (rcaeval_facts §Anomaly scoring methods), so the scale is never below the IQR term, a
per-family ε or 2% of |median|. Why persistence: one-sample spikes must not set the robust score;
`nsigma` keeps the raw max for parity with RCAEval's N-Sigma baseline.

Pure functions over one series' arrays: exact medians and linear quantiles, ties to the earliest
time, no RNG (03-anomara §5).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

from veyltrace_anomara.series import FloatArray, IntArray, Window, bucket_ids, covered_buckets, in_window
from veyltrace_anomara.settings import NSigmaConfig, RobustZConfig

__all__ = ["Direction", "Score", "nsigma", "persistent_z", "robust_scale", "robust_z"]

Direction = Literal["up", "down", "flat"]


@dataclass(frozen=True)
class Score:
    """One detector's verdict on one series (the `anomalies` columns it decides, 03 §4.1)."""

    score: float
    score_norm: float
    direction: Direction
    onset_ns: int | None
    threshold: float

    @property
    def above_threshold(self) -> bool:
        """03 §4.1: `above_threshold ⇔ score ≥ threshold`."""
        return self.score >= self.threshold

    @classmethod
    def flat(cls, threshold: float) -> Score:
        """Nothing to score (short baseline, no incident points): 03-anomara §3.2 step 8, §6."""
        return cls(0.0, 0.0, "flat", None, threshold)


def robust_scale(baseline: FloatArray, epsilon: float, cfg: RobustZConfig) -> tuple[float, float]:
    """(median, floored scale) of the baseline: `max(1.4826·MAD, IQR/1.349, ε, η·|med|)`."""
    med = float(np.median(baseline))
    mad = float(np.median(np.abs(baseline - med)))
    q25, q75 = (float(q) for q in np.quantile(baseline, [0.25, 0.75], method="linear"))
    return med, max(cfg.mad_factor * mad, (q75 - q25) / cfg.iqr_divisor, epsilon, cfg.eta * abs(med))


def _range_min(values: FloatArray, lo: IntArray, hi: IntArray) -> FloatArray:
    """min(values[lo[k]:hi[k]]) for every k (sparse table; every range is non-empty)."""
    levels = [values]
    width = 1
    while 2 * width <= values.size:
        prev = levels[-1]
        levels.append(np.minimum(prev[:-width], prev[width:]))
        width *= 2
    span = hi - lo
    order = np.floor(np.log2(span)).astype(np.int64)
    out = np.empty(lo.size, dtype=np.float64)
    for k in np.unique(order):
        pick = order == k
        table = levels[int(k)]
        out[pick] = np.minimum(table[lo[pick]], table[hi[pick] - (1 << int(k))])
    return out


def persistent_z(t: IntArray, z: FloatArray, step: int, persist_steps: int) -> FloatArray:
    """z̃_t (03-anomara §3.2 step 4): the min |z| over `[t, t + p·g)` when every point there has the
    sign of `z_t` and they cover at least `p` grid buckets; else 0."""
    n = z.size
    if n == 0:
        return np.zeros(0, dtype=np.float64)
    lo = np.arange(n, dtype=np.int64)
    hi = np.searchsorted(t, t + persist_steps * step, side="left").astype(np.int64)
    buckets = bucket_ids(t, step)
    ordinal = np.cumsum(np.concatenate(([1], (buckets[1:] != buckets[:-1]).astype(np.int64))))
    covered = ordinal[hi - 1] - ordinal[lo] + 1
    pos = np.concatenate(([0], np.cumsum(z > 0)))
    neg = np.concatenate(([0], np.cumsum(z < 0)))
    length = hi - lo
    same_sign = ((pos[hi] - pos[lo]) == length) | ((neg[hi] - neg[lo]) == length)
    keep = same_sign & (covered >= persist_steps)
    return np.where(keep, _range_min(np.abs(z), lo, hi), 0.0)


def _first(mask: npt.NDArray[np.bool_], t: IntArray) -> int | None:
    hits = np.flatnonzero(mask)
    return int(t[hits[0]]) if hits.size else None


def robust_z(
    t: IntArray,
    x: FloatArray,
    baseline: Window,
    incident: Window,
    step: int,
    epsilon: float,
    cfg: RobustZConfig,
) -> Score:
    """Persistent robust z of the incident against the baseline (03-anomara §3.2)."""
    b = in_window(t, baseline)
    i = in_window(t, incident)
    if covered_buckets(t[b], step) < cfg.min_baseline_steps or not i.any():
        return Score.flat(cfg.threshold)
    med, scale = robust_scale(x[b], epsilon, cfg)
    if scale <= 0.0:  # only with ε = η = 0 and a constant baseline (property tests)
        return Score.flat(cfg.threshold)
    ti = t[i]
    z = (x[i] - med) / scale
    zt = persistent_z(ti, z, step, cfg.persist_steps)
    k = int(np.argmax(zt))  # first index of the max: earliest time on ties
    score = float(zt[k])
    if score == 0.0:
        return Score.flat(cfg.threshold)
    direction: Direction = "up" if z[k] > 0 else "down"
    onset = _first(zt >= cfg.threshold, ti)
    return Score(score, math.log1p(score), direction, onset, cfg.threshold)


def nsigma(
    t: IntArray,
    x: FloatArray,
    baseline: Window,
    incident: Window,
    step: int,
    epsilon: float,
    rz: RobustZConfig,
    cfg: NSigmaConfig,
) -> Score:
    """Raw-max N-Sigma (03-anomara §3.3): RCAEval's zero-scale convention (unit scale when the
    baseline std is 0), and a `score_norm` over the floored scale `max(std_B, ε, η·|mean_B|)` so it
    compares across series."""
    b = in_window(t, baseline)
    i = in_window(t, incident)
    if covered_buckets(t[b], step) < rz.min_baseline_steps or not i.any():
        return Score.flat(cfg.threshold)
    mu = float(np.mean(x[b]))
    sigma = float(np.std(x[b]))
    dev = np.abs(x[i] - mu)
    ratio = dev / (sigma if sigma > 0.0 else 1.0)
    k = int(np.argmax(ratio))
    score = float(ratio[k])
    if score == 0.0:
        return Score.flat(cfg.threshold)
    floor = max(sigma, epsilon, rz.eta * abs(mu))
    norm = math.log1p(float(dev[k]) / floor) if floor > 0.0 else math.log1p(score)
    direction: Direction = "up" if x[i][k] > mu else "down"
    return Score(score, norm, direction, _first(ratio >= cfg.threshold, t[i]), cfg.threshold)
