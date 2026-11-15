"""Logs and metrics onto the reference clock (04-causync §3.3).

Two estimators, both source-level (`service` null). `log_span_join`: a log line that names its
span should lie inside it, so the lines that do not say how far the log clock is off.
`comovement`: the fallback for logs without span ids and for metrics. Traffic seen by two sources
rises and falls together, so the lag that best correlates their first differences is the clock
difference. Its resolution is one step: it only catches gross misalignment, finer differences
are inside `tolerance_ns` by construction.
"""

from __future__ import annotations

from typing import Any, Final

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from veyltrace_causync.settings import AlignConfig
from veyltrace_causync.steps import series_groups
from veyltrace_causync.tracepairs import Offset

__all__ = ["JOIN_LOG_COLUMNS", "TRAFFIC_SIGNALS", "comovement_offset", "log_span_offset"]

_pc: Any = pc  # pyarrow-stubs type compute kernels with Unknown parts (as core's io.py)
type Vec = np.ndarray[Any, Any]
JOIN_LOG_COLUMNS: Final = ("t_ns", "service", "trace_id", "span_id")
#: Traffic-like series per source (04 §3.3 step 1); bucketed sources are rates, metrics gauges.
TRAFFIC_SIGNALS: Final = {"logs": ("log_rate",), "traces": ("rps",), "metrics": ("workload", "rps")}


def log_span_offset(logs: pa.Table, spans: pa.Table, cfg: AlignConfig) -> Offset | None:
    """The `logs` offset from lines joined to their span on (trace_id, span_id), or None when no
    line joins. Offset 0 if at least `log_inside_share` of the lines already lie inside their
    span; else the median shift that would put each line inside. `confidence` is the share of
    lines inside their span after the shift."""
    named = logs.filter(_pc.and_(_pc.is_valid(logs.column("trace_id")), _pc.is_valid(logs.column("span_id"))))
    if named.num_rows == 0 or spans.num_rows == 0:
        return None
    span_keys = _pc.binary_join_element_wise(spans.column("trace_id"), spans.column("span_id"), "\x00")
    log_keys = _pc.binary_join_element_wise(named.column("trace_id"), named.column("span_id"), "\x00")
    found = _pc.fill_null(_pc.index_in(log_keys, value_set=span_keys), -1)
    index = np.asarray(found.to_numpy(zero_copy_only=False), dtype=np.int64)
    joined = index >= 0
    if not joined.any():
        return None
    t = np.asarray(named.column("t_ns").to_numpy(), dtype=np.int64)[joined]
    lo = np.asarray(spans.column("start_ns").to_numpy(), dtype=np.int64)[index[joined]] - t
    hi = np.asarray(spans.column("end_ns").to_numpy(), dtype=np.int64)[index[joined]] - t
    inside = float(np.mean((lo <= 0) & (hi >= 0)))
    if inside >= cfg.log_inside_share:
        return Offset("logs", None, 0, "log_span_join", inside)
    shift = int(np.rint(np.median(np.clip(0, lo, hi))))  # each line's nearest in-span shift
    return Offset("logs", None, shift, "log_span_join", float(np.mean((lo <= shift) & (hi >= shift))))


def _traffic(series: pa.Table, source: str, step: int) -> dict[str, dict[int, float]]:
    """{service: {bucket: value}} of a source's traffic series on the `step` grid. Bucketed sources
    carry rates, so a bucket takes the mean of its points: a sum would alternate with the number
    of 10 s buckets that fall into each step of a coarser grid and correlate with nothing but
    itself. Metrics are held gauges and keep their last value. A service's replicas are added up."""
    out: dict[str, dict[int, float]] = {}
    for (src, service, _, signal), t, x in series_groups(series):
        if src != source or signal not in TRAFFIC_SIGNALS[source]:
            continue
        buckets: dict[int, list[float]] = {}
        for b, value in zip((t // step).tolist(), x.tolist(), strict=True):
            buckets.setdefault(b, []).append(value)
        total = out.setdefault(service, {})
        for b, values in buckets.items():
            value = values[-1] if source == "metrics" else sum(values) / len(values)
            total[b] = total.get(b, 0.0) + value
    return out


def _best_lag(
    src: dict[int, float], ref: dict[int, float], max_steps: int, cfg: AlignConfig
) -> tuple[int, float] | None:
    """(lag in steps, correlation) of the best accepted lag: the source shows the reference's
    changes `lag` steps later. Ties go to the smaller |lag|, then to the negative one."""
    first, last = min(*src, *ref), max(*src, *ref)
    grid = range(first, last + 1)
    ds = np.diff(np.asarray([src.get(b, np.nan) for b in grid], dtype=np.float64))
    dr = np.diff(np.asarray([ref.get(b, np.nan) for b in grid], dtype=np.float64))
    best: tuple[int, float] | None = None
    for lag in sorted(range(-max_steps, max_steps + 1), key=lambda k: (abs(k), k)):
        a = ds[max(lag, 0) : ds.size + min(lag, 0)]
        b = dr[max(-lag, 0) : dr.size + min(-lag, 0)]
        ok = np.isfinite(a) & np.isfinite(b)
        if int(ok.sum()) < cfg.min_points or float(np.std(a[ok])) == 0.0 or float(np.std(b[ok])) == 0.0:
            continue
        r = float(np.corrcoef(a[ok], b[ok])[0, 1])
        if best is None or r > best[1]:
            best = (lag, r)
    if best is None or best[1] < cfg.min_corr:
        return None
    return best


def comovement_offset(
    series: pa.Table, source: str, reference: str, steps: dict[str, int], cfg: AlignConfig
) -> Offset:
    """The source-level offset of `source` against `reference` by co-movement of traffic: the
    median of the accepted per-service offsets if at least two services agree within one step,
    else offset 0 with method `none`. A median of at most one step is published as 0."""
    none = Offset(source, None, 0, "none", 0.0)
    if source not in steps or reference not in steps:
        return none
    step = max(steps[source], steps[reference])
    max_steps = (cfg.max_lag_ns - 1) // step  # |lag| strictly below max_lag
    mine, theirs = _traffic(series, source, step), _traffic(series, reference, step)
    accepted: list[tuple[int, float]] = []
    for service in sorted(set(mine) & set(theirs)):
        found = _best_lag(mine[service], theirs[service], max_steps, cfg)
        if found is not None:
            accepted.append((-found[0] * step, found[1]))  # shown later → shift earlier
    if not accepted:
        return none
    median = float(np.median([offset for offset, _ in accepted]))
    agreeing = [r for offset, r in accepted if abs(offset - median) <= step]
    if len(agreeing) < 2:
        return none
    # One step is the resolution: a lag of a single step is what a rate stamped at the end of its
    # interval looks like, and it is inside `tolerance_ns` anyway. Only a larger lag is skew.
    shift = int(np.rint(median)) if abs(median) > step else 0
    return Offset(source, None, shift, "comovement", min(float(np.median(agreeing)), 1.0))
