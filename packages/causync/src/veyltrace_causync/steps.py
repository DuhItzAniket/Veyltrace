"""Source steps and the comparison tolerance (04-causync §3.1).

Each present source has a step, derived from `signal_cube.series` alone (no other engine's config
is read): metrics take the median effective step of their series (the median duration of runs of
equal consecutive values, at least the observation spacing; the definition of 03-anomara §3.1),
logs and traces the bucket spacing of their zero-filled count series. Two onsets closer than the
largest step cannot be ordered, so that step is `tolerance_ns`; for it the metrics step is an
upper quantile over the metric series, because an onset found on a coarse series cannot be placed
more finely than that series' step, however many other series change every second.
"""

from __future__ import annotations

from collections.abc import Iterator
from itertools import pairwise
from typing import Any, Final

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

__all__ = ["COUNT_SIGNALS", "SERIES_COLUMNS", "series_groups", "source_steps", "tolerance"]

_pc: Any = pc  # pyarrow-stubs type compute kernels with Unknown parts (as core's io.py)
type Vec = np.ndarray[Any, Any]
SERIES_COLUMNS: Final = ("service", "component", "signal", "source", "t_ns", "value")
#: The zero-filled count series whose bucket spacing is the step of a bucketed source (02 §3.1).
COUNT_SIGNALS: Final = {"logs": "log_rate", "traces": "rps"}


def series_groups(series: pa.Table) -> Iterator[tuple[tuple[str, str, str, str], Vec, Vec]]:
    """((source, service, component, signal), t_ns, value) per series, in key order, points by time."""
    if series.num_rows == 0:
        return
    names = ("source", "service", "component", "signal")
    order = _pc.sort_indices(series, sort_keys=[(n, "ascending") for n in (*names, "t_ns")])
    s = series.take(order)
    keys = list(zip(*(s.column(n).to_pylist() for n in names), strict=True))
    t = np.asarray(s.column("t_ns").to_numpy(), dtype=np.int64)
    x = np.asarray(s.column("value").to_numpy(), dtype=np.float64)
    cuts = [0, *(i for i in range(1, len(keys)) if keys[i] != keys[i - 1]), len(keys)]
    for a, b in pairwise(cuts):
        yield keys[a], t[a:b], x[a:b]


def _effective_step(t: Vec, x: Vec) -> float | None:
    """Median run length of equal consecutive values, at least the median observation spacing."""
    if t.size < 2:
        return None
    spacing = float(np.median(np.diff(t)))
    starts = np.concatenate(([0], np.flatnonzero(x[1:] != x[:-1]) + 1))
    runs = np.diff(t[starts])
    return max(float(np.median(runs)), spacing) if runs.size else spacing


def source_steps(series: pa.Table, metrics_quantile: float = 0.5) -> dict[str, int]:
    """{source: step_ns} for every source with a stepped series (`metrics`, `logs`, `traces`).
    The metrics step is the `metrics_quantile` quantile (exact, linear) of the effective steps
    over metric series: the median for resampling, a higher quantile for the tolerance, where
    the coarse series must be covered (04 §3.1)."""
    found: dict[str, list[float]] = {}
    for (source, _, _, signal), t, x in series_groups(series):
        if source == "metrics":
            step = _effective_step(t, x)
        elif signal == COUNT_SIGNALS.get(source) and t.size >= 2:
            step = float(np.median(np.diff(t)))
        else:
            step = None
        if step is not None:
            found.setdefault(source, []).append(step)
    out: dict[str, int] = {}
    for source, steps in sorted(found.items()):
        q = metrics_quantile if source == "metrics" else 0.5
        out[source] = max(int(np.rint(np.quantile(np.asarray(steps), q, method="linear"))), 1)
    return out


def tolerance(steps: dict[str, int]) -> int:
    """The largest source step; 0 when no stepped source is present (03 §5.1)."""
    return max(steps.values(), default=0)
