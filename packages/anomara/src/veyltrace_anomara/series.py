"""One `signal_cube.series` series as arrays, its effective step and grid buckets (03-anomara §3.1).

Why the effective step: RCAEval metrics are 1 s rows that change about every 15 s, so persistence,
BOCPD and silence must count steps of the real scrape (`g ≈ 15 s`), not of the row spacing
(rcaeval_facts §Metric step and windows). Traces and logs are already on Signalyth's bucket grid.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.compute as pc

__all__ = [
    "BoolArray",
    "FloatArray",
    "Grid",
    "IntArray",
    "Series",
    "Window",
    "bucket_ids",
    "covered_buckets",
    "effective_step",
    "grid",
    "in_window",
    "split_series",
]

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]
#: A half-open [start_ns, end_ns) window (03 §2.6).
Window = tuple[int, int]
#: pyarrow-stubs leave pyarrow.compute's signatures partly unknown (as in veyltrace_core.io).
_pc: Any = pc
_META = ("series_id", "service", "component", "signal", "family", "klass", "source", "unit")


@dataclass(frozen=True, eq=False)
class Series:
    """One series: its descriptive columns and its finite points, sorted by `t_ns`."""

    series_id: str
    service: str
    component: str
    signal: str
    family: str
    klass: str
    source: str
    unit: str | None
    t: IntArray
    x: FloatArray


def split_series(table: pa.Table) -> Iterator[Series]:
    """Yield the series of a `signal_cube.series` table in `series_id` order (03-anomara §5).

    Non-finite values are dropped (03-anomara §6: NaN is missing); a series with no finite point
    is still yielded, with empty arrays, so it keeps its `anomalies` rows.
    """
    if table.num_rows == 0:
        return
    keys = [("series_id", "ascending"), ("t_ns", "ascending")]
    ordered = table.take(cast("pa.Array[Any]", _pc.sort_indices(table, sort_keys=keys)))
    ids = cast("list[str]", ordered.column("series_id").to_pylist())
    t_all = np.asarray(ordered.column("t_ns").to_numpy(), dtype=np.int64)
    x_all = np.asarray(ordered.column("value").to_numpy(), dtype=np.float64)
    meta = {name: cast("list[Any]", ordered.column(name).to_pylist()) for name in _META[1:]}
    start = 0
    for end in [*(i for i in range(1, len(ids)) if ids[i] != ids[i - 1]), len(ids)]:
        t, x = t_all[start:end], x_all[start:end]
        keep = np.isfinite(x)
        yield Series(
            ids[start],
            *(cast("str", meta[name][start]) for name in _META[1:-1]),
            unit=cast("str | None", meta["unit"][start]),
            t=t[keep],
            x=x[keep],
        )
        start = end


def effective_step(series: Series, bucket_ns: int) -> int:
    """`g` in ns (03-anomara §3.1).

    Metrics: the median duration of runs of equal consecutive values (a run lasts from its first
    point to the next run's first point), but at least the median spacing of observations.
    Traces and logs, and a metric with fewer than two points: the Signalyth bucket.
    """
    t, x = series.t, series.x
    if series.source != "metrics" or t.size < 2:
        return bucket_ns
    spacing = float(np.median(np.diff(t)))
    starts = np.concatenate(([0], np.flatnonzero(x[1:] != x[:-1]) + 1))
    runs = np.diff(t[starts])
    step = max(float(np.median(runs)), spacing) if runs.size else spacing
    return max(int(np.rint(step)), 1)


def in_window(t: IntArray, window: Window) -> BoolArray:
    """Mask of the points inside the half-open window."""
    return (t >= window[0]) & (t < window[1])


def bucket_ids(t: IntArray, step: int) -> IntArray:
    """Epoch-aligned bucket index `floor(t / g)` of each point."""
    return np.floor_divide(t, step)


def covered_buckets(t: IntArray, step: int) -> int:
    """Number of distinct epoch-aligned `g` buckets holding at least one point."""
    return int(np.unique(bucket_ids(t, step)).size)


@dataclass(frozen=True, eq=False)
class Grid:
    """A grid series (03-anomara §3.1): contiguous epoch-aligned buckets `k·g` inside a span, the
    last observed value of each bucket (NaN where the bucket has no point) and the observed mask."""

    step: int
    starts: IntArray
    values: FloatArray
    observed: BoolArray

    def within(self, window: Window) -> BoolArray:
        """Buckets whose start lies in the half-open window (membership of B and I)."""
        return in_window(self.starts, window)


def grid(t: IntArray, x: FloatArray, step: int, span: Window) -> Grid:
    """The grid of buckets `k` with `span[0] ≤ k·g < span[1]`, from the points inside the span.

    Points before the first whole bucket (an unaligned span start) belong to no bucket; `t` is
    sorted, so the last point of each run of equal bucket ids is that bucket's last observation.
    """
    first = -(-span[0] // step)  # ceil(span[0] / g)
    count = max(-(-span[1] // step) - first, 0)
    starts = (first + np.arange(count, dtype=np.int64)) * step
    values = np.full(count, np.nan, dtype=np.float64)
    observed = np.zeros(count, dtype=np.bool_)
    inside = in_window(t, span)
    index = bucket_ids(t[inside], step) - first
    kept = index >= 0
    index, xs = index[kept], x[inside][kept]
    if index.size:
        last = np.flatnonzero(np.concatenate((index[1:] != index[:-1], [True])))
        values[index[last]] = xs[last]
        observed[index[last]] = True
    return Grid(step, starts, values, observed)
