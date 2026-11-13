"""Unit and property tests of Anomara's series layer: split, effective step, grid (03-anomara §3.1)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pyarrow as pa
from hypothesis import given, settings
from hypothesis import strategies as st

from veyltrace_anomara.series import Series, effective_step, grid, split_series

NS = 1_000_000_000
G = 15 * NS
BUCKET = 10 * NS


def _series(source: str, t: list[int], x: list[float]) -> Series:
    return Series(
        "a|a|x|" + source, "a", "a", "x", "other", "internal", source, None,
        np.asarray(t, dtype=np.int64), np.asarray(x, dtype=np.float64),
    )  # fmt: skip


def test_effective_step_of_step_held_1s_rows_is_the_scrape() -> None:
    held = [float(k // 15) for k in range(120)]  # RCAEval-like: 1 s rows that change every 15 s
    assert effective_step(_series("metrics", [k * NS for k in range(120)], held), BUCKET) == G


def test_effective_step_is_at_least_the_median_spacing() -> None:
    rates = [float(k % 3) for k in range(10)]  # a counter rate: a new value at every 15 s scrape
    assert effective_step(_series("metrics", [k * G for k in range(10)], rates), BUCKET) == G
    constant = [1.0] * 10  # one run only: no run duration, so the spacing decides
    assert effective_step(_series("metrics", [k * G for k in range(10)], constant), BUCKET) == G


def test_bucketed_sources_and_short_metrics_use_the_signalyth_bucket() -> None:
    assert effective_step(_series("traces", [0, G], [1.0, 2.0]), BUCKET) == BUCKET
    assert effective_step(_series("logs", [0, G], [1.0, 2.0]), BUCKET) == BUCKET
    assert effective_step(_series("metrics", [0], [1.0]), BUCKET) == BUCKET


def test_grid_keeps_the_last_value_per_bucket_and_marks_gaps() -> None:
    t = np.asarray([3 * NS, 5 * NS, 12 * NS, 47 * NS], dtype=np.int64)
    x = np.asarray([1.0, 2.0, 3.0, 4.0])
    g = grid(t, x, BUCKET, (0, 60 * NS))
    assert g.starts.tolist() == [k * BUCKET for k in range(6)]
    assert g.observed.tolist() == [True, True, False, False, True, False]
    assert [v for v in g.values.tolist() if not math.isnan(v)] == [2.0, 3.0, 4.0]
    assert g.within((20 * NS, 40 * NS)).tolist() == [False, False, True, True, False, False]


def test_grid_drops_points_before_the_first_whole_bucket_and_after_the_span() -> None:
    t = np.asarray([2 * NS, 11 * NS, 31 * NS], dtype=np.int64)
    g = grid(t, np.asarray([9.0, 1.0, 7.0]), BUCKET, (NS, 30 * NS))
    assert g.starts.tolist() == [BUCKET, 2 * BUCKET]
    assert g.values.tolist()[0] == 1.0 and g.observed.tolist() == [True, False]
    assert grid(t, np.asarray([9.0, 1.0, 7.0]), BUCKET, (5 * NS, 5 * NS)).starts.size == 0


def _table(rows: list[tuple[str, int, float]]) -> pa.Table:
    ids = [r[0] for r in rows]
    parts = {k: [s.split("|")[i] for s in ids] for i, k in enumerate(("service", "component", "signal"))}
    n = len(rows)
    columns: dict[str, Any] = {
        "series_id": ids,
        "t_ns": [r[1] for r in rows],
        "value": [r[2] for r in rows],
        **parts,
        "family": ["other"] * n,
        "klass": ["internal"] * n,
        "source": ["metrics"] * n,
        "unit": pa.nulls(n, pa.string()),
    }
    return pa.table(columns)


def test_split_series_orders_series_and_drops_nan() -> None:
    rows = [("b|b|x|metrics", 2, 1.0), ("a|a|x|metrics", 5, math.nan), ("a|a|x|metrics", 1, 2.0)]
    found = list(split_series(_table(rows)))
    assert [s.series_id for s in found] == ["a|a|x|metrics", "b|b|x|metrics"]
    assert (found[0].t.tolist(), found[0].x.tolist(), found[0].unit) == ([1], [2.0], None)
    assert list(split_series(_table([]))) == []


_rows = st.lists(
    st.tuples(st.sampled_from("abc"), st.integers(0, 50), st.integers(-5, 5)), unique_by=lambda r: r[:2]
)


@settings(max_examples=30, deadline=None)
@given(_rows)
def test_split_series_ignores_row_order(rows: list[tuple[str, int, int]]) -> None:
    table = _table([(f"{s}|{s}|x|metrics", t, float(v)) for s, t, v in rows])
    flipped = table.take(np.arange(table.num_rows)[::-1])
    for one, two in zip(split_series(table), split_series(flipped), strict=True):
        assert one.series_id == two.series_id
        assert one.t.tolist() == two.t.tolist() and one.x.tolist() == two.x.tolist()
