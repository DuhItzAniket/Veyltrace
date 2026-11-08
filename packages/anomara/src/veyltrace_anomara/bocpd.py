"""`bocpd`: Bayesian online change-point onset per series (03-anomara §3.4; Adams & MacKay 2007).

Why: robust z says *that* a series moved; BOCPD says *when* a run began, so a slow ramp's onset moves
back to where it started (§3.6 onset of record). BARO uses BOCPD for onset (rcaeval_facts §Anomaly
scoring methods); here it is univariate on the standardised grid series, so the priors are unit-free.

Model: Gaussian with unknown mean and variance, Normal-Gamma prior, constant hazard 1/λ, run lengths
truncated at R_max (mass of longer runs folded into R_max). The run that starts at step t contains
x_t, so a change at t puts the mass on r_t = 0 and the onset is t − r̂·g. Determinism: every series
of one grid is stacked into a (series × run length) array advanced by one sequential loop over time,
in log space with max-shifted log-sum-exp and elementwise numpy only (no matrix products, so no
multithreaded BLAS), no RNG. The lgamma terms depend only on the observation count, so they are a
precomputed table (`math.lgamma`, no scipy).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from veyltrace_anomara.robust import Direction, Score
from veyltrace_anomara.series import BoolArray, FloatArray, Grid, IntArray, Window
from veyltrace_anomara.settings import BocpdConfig

__all__ = ["Standardised", "bocpd", "run_length_posterior"]


@dataclass(frozen=True, eq=False)
class Standardised:
    """One series' grid and its robust baseline location and scale (03-anomara §3.2)."""

    grid: Grid
    median: float
    scale: float


def _logsumexp(a: FloatArray) -> FloatArray:
    """Row-wise log Σ exp, shifted by the row max (every row has a finite entry)."""
    top = np.max(a, axis=1)
    return top + np.log(np.sum(np.exp(a - top[:, None]), axis=1))


def _student_t(
    y: FloatArray, mu: FloatArray, kappa: FloatArray, count: npt.NDArray[np.int64], beta: FloatArray,
    lg: FloatArray, alpha0: float,
) -> FloatArray:  # fmt: skip
    """Log predictive density: Student-t, 2·alpha dof, location mu, scale² beta(kappa + 1)/(alpha·kappa)."""
    alpha = alpha0 + 0.5 * count
    nu = 2.0 * alpha
    scale2 = beta * (kappa + 1.0) / (alpha * kappa)
    dev = (y[:, None] - mu) ** 2 / (nu * scale2)
    return lg[count] - 0.5 * np.log(nu * math.pi * scale2) - (alpha + 0.5) * np.log1p(dev)


def run_length_posterior(
    y: FloatArray, observed: BoolArray, cfg: BocpdConfig, *, keep: bool = False
) -> tuple[FloatArray, IntArray, list[FloatArray]]:
    """Short-run mass `cp[s, t] = P(r_t ≤ m)`, its argmax `r̂[s, t]` (smallest r on ties) and, with
    `keep`, the normalised log posterior of every step (tests). `y`, `observed`: (series × steps);
    an unobserved step advances the run lengths without a likelihood term."""
    n_series, n_steps = y.shape
    # Runs cannot be longer than the grid, so a shorter array gives the same posterior faster.
    width = max(min(cfg.r_max, n_steps - 1), 1) + 1
    lg = np.asarray(
        [
            math.lgamma(cfg.alpha0 + 0.5 * k + 0.5) - math.lgamma(cfg.alpha0 + 0.5 * k)
            for k in range(n_steps + 2)
        ]
    )
    log_h, log_stay = math.log(1.0 / cfg.lam), math.log1p(-1.0 / cfg.lam)
    prior = (np.full(n_series, cfg.mu0), np.full(n_series, cfg.kappa0), np.zeros(n_series, np.int64),
             np.full(n_series, cfg.beta0))  # fmt: skip
    mu, kappa = np.full((n_series, width), cfg.mu0), np.full((n_series, width), cfg.kappa0)
    count, beta = np.zeros((n_series, width), np.int64), np.full((n_series, width), cfg.beta0)
    log_r = np.full((n_series, width), -np.inf)
    log_r[:, 0] = 0.0
    cp = np.zeros((n_series, n_steps))
    rhat = np.zeros((n_series, n_steps), np.int64)
    history: list[FloatArray] = []
    for t in range(n_steps):
        seen = observed[:, t]
        yt = np.where(seen, y[:, t], 0.0)
        if t > 0:
            pred = np.where(seen[:, None], _student_t(yt, mu, kappa, count, beta, lg, cfg.alpha0), 0.0)
            first = _student_t(yt, prior[0][:, None], prior[1][:, None], prior[2][:, None], prior[3][:, None],
                               lg, cfg.alpha0)  # fmt: skip
            pred0 = np.where(seen, first[:, 0], 0.0)
            grow = log_r + pred + log_stay
            new = np.empty_like(log_r)
            new[:, 0] = log_h + pred0  # log_r is normalised: Σ_r P(r_{t-1}) = 1
            new[:, 1:] = grow[:, :-1]
            new[:, -1] = np.logaddexp(grow[:, -2], grow[:, -1])
            log_r = new - _logsumexp(new)[:, None]
            # Shift the statistics: run r+1 continues run r; run 0 starts from the prior.
            mu = np.concatenate((prior[0][:, None], mu[:, :-1]), axis=1)
            kappa = np.concatenate((prior[1][:, None], kappa[:, :-1]), axis=1)
            count = np.concatenate((prior[2][:, None], count[:, :-1]), axis=1)
            beta = np.concatenate((prior[3][:, None], beta[:, :-1]), axis=1)
        upd = seen[:, None]
        dev = yt[:, None] - mu
        beta = np.where(upd, beta + kappa * dev**2 / (2.0 * (kappa + 1.0)), beta)
        mu = np.where(upd, (kappa * mu + yt[:, None]) / (kappa + 1.0), mu)
        kappa = np.where(upd, kappa + 1.0, kappa)
        count = np.where(upd, count + 1, count)
        short = log_r[:, : cfg.short_run + 1]
        cp[:, t] = np.exp(_logsumexp(short))
        rhat[:, t] = np.argmax(short, axis=1)
        if keep:
            history.append(log_r.copy())
    return cp, rhat, history


def bocpd(
    series: Sequence[Standardised], incident: Window, persist_steps: int, cfg: BocpdConfig
) -> list[Score]:
    """Score every series of one grid (same step and buckets); one Score per input, in order."""
    if not series:
        return []
    step = series[0].grid.step
    y = np.stack([(s.grid.values - s.median) / s.scale for s in series])
    observed = np.stack([s.grid.observed for s in series])
    cp, rhat, _ = run_length_posterior(np.where(observed, y, 0.0), observed, cfg)
    scores: list[Score] = []
    for k, s in enumerate(series):
        starts = s.grid.starts
        in_i = s.grid.within(incident)
        if not in_i.any():
            scores.append(Score.flat(cfg.threshold))
            continue
        score = float(np.max(cp[k][in_i]))
        hits = np.flatnonzero(in_i & (cp[k] >= cfg.threshold))
        if hits.size == 0:
            scores.append(Score(score, math.log1p(score), "flat", None, cfg.threshold))
            continue
        onset = int(starts[hits[0]] - rhat[k][hits[0]] * step)
        span = observed[k] & (starts >= onset) & (starts < onset + persist_steps * step)
        mean = float(np.mean(y[k][span], dtype=np.float64)) if span.any() else 0.0
        direction: Direction = "up" if mean > 0 else "down" if mean < 0 else "flat"
        scores.append(Score(score, math.log1p(score), direction, onset, cfg.threshold))
    return scores
