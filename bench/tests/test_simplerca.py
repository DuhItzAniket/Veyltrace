"""SimpleRCA, the alert-count baseline (04 §4; Fang et al. arXiv 2510.04711v2 §3.1.2; #15)."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_bench import baselines, simplerca
from veyltrace_bench.simplerca import LogRule, MetricRule, SimpleRcaConfig, TraceRule
from veyltrace_core.errors import ConfigError

S = 1_000_000_000
HISTORY, DETECT = (0, 100 * S), (100 * S, 200 * S)
METRIC = MetricRule(sigma=3.0, percentile=95.0)
TRACE = TraceRule(percentile=95.0, factor=3.0)
LOG = LogRule(keywords=("error", "fail", "exception"), factor=3.0, min_count=1)


def _metrics(series: dict[tuple[str, str], tuple[list[float], list[float]]]) -> pa.Table:
    """Long metrics rows: per (service, name), history values at 0..n s, detection from 100 s."""
    rows: dict[str, list[object]] = {"t_ns": [], "service": [], "component": [], "name": [], "value": []}
    for (service, name), (hist, det) in series.items():
        times = [i * S for i in range(len(hist))] + [100 * S + i * S for i in range(len(det))]
        for t, v in zip(times, [*hist, *det], strict=True):
            for col, val in zip(rows, (t, service, service, name, v), strict=True):
                rows[col].append(val)
    return pa.table(rows)


def test_metric_alert_on_a_3_sigma_rise_only() -> None:
    flat = [1.0, 2.0] * 20
    table = _metrics({("cart", "cpu"): (flat, [9.0] * 10), ("ad", "cpu"): (flat, flat[:10])})
    assert simplerca.metric_alerts(table, HISTORY, DETECT, METRIC) == {"cart": 1}


def test_metric_alert_counts_series_and_ignores_points_outside_windows() -> None:
    hist = [1.0] * 30
    table = _metrics({("cart", "cpu"): (hist, [5.0]), ("cart", "mem"): (hist, [5.0])})
    assert simplerca.metric_alerts(table, HISTORY, DETECT, METRIC) == {"cart": 2}
    late = (300 * S, 400 * S)  # no detection point: no alert
    assert simplerca.metric_alerts(table, HISTORY, late, METRIC) == {}


def test_metric_alert_above_history_p95_even_below_3_sigma() -> None:
    hist = [0.0] * 95 + [100.0] * 5  # P95 = 5 (type 7: index 94.05), mean + 3 sigma ≈ 70
    table = _metrics({("cart", "cpu"): (hist, [10.0] * 5)})
    assert simplerca.metric_alerts(table, (0, 100 * S), (100 * S, 200 * S), METRIC) == {"cart": 1}


def _spans(rows: list[tuple[str, int, int]]) -> pa.Table:
    return pa.table({
        "service": [r[0] for r in rows],
        "start_ns": [r[1] for r in rows],
        "end_ns": [r[1] + r[2] for r in rows],
    })  # fmt: skip


def test_trace_alert_at_3x_history_p95() -> None:
    base = [("cart", i * S, 10) for i in range(50)] + [("ad", i * S, 10) for i in range(50)]
    slow = [("cart", 100 * S + i * S, 30) for i in range(20)] + [
        ("ad", 100 * S + i * S, 29) for i in range(20)
    ]
    assert simplerca.trace_alerts(_spans(base + slow), HISTORY, DETECT, TRACE) == {"cart": 1}


def _logs(rows: list[tuple[str, int, str]]) -> pa.Table:
    return pa.table(
        {"service": [r[0] for r in rows], "t_ns": [r[1] for r in rows], "body": [r[2] for r in rows]}
    )


def test_log_alert_on_an_error_keyword_spike() -> None:
    rows = [("cart", 10 * S, "Error once"), ("cart", 110 * S, "FAILED to call"), ("cart", 120 * S, "x")]
    rows += [("cart", 130 * S + i, "NullPointerException") for i in range(3)]
    rows += [("ad", 10 * S, "error"), ("ad", 110 * S, "error"), ("web", 110 * S, "all good")]
    assert simplerca.log_alerts(_logs(rows), HISTORY, DETECT, LOG) == {"cart": 1}  # cart 4 vs 1, ad 1 vs 1


def test_rank_most_alerts_first_ties_a_to_z_every_service_once() -> None:
    assert simplerca.rank(["b", "a", "c"], {"c": 2, "b": 1, "d": 1}) == ("c", "b", "d", "a")


@given(st.dictionaries(st.sampled_from("abcdefg"), st.integers(0, 5)), st.sets(st.sampled_from("abcdefg")))
def test_rank_is_a_permutation_sorted_by_alerts(alerts: dict[str, int], services: set[str]) -> None:
    ranks = simplerca.rank(services, alerts)
    assert sorted(ranks) == sorted(services | set(alerts))
    counts = [alerts.get(s, 0) for s in ranks]
    assert counts == sorted(counts, reverse=True)


@given(
    st.lists(st.floats(-1e6, 1e6), min_size=2, max_size=30),
    st.lists(st.floats(-1e6, 1e6), min_size=1, max_size=30),
)
def test_metric_alerts_do_not_depend_on_row_order(hist: list[float], det: list[float]) -> None:
    table = _metrics({("cart", "cpu"): (hist, det), ("ad", "mem"): (det, hist)})
    reverse = table.take(pa.array(range(table.num_rows - 1, -1, -1)))
    assert simplerca.metric_alerts(table, HISTORY, DETECT, METRIC) == simplerca.metric_alerts(
        reverse, HISTORY, DETECT, METRIC
    )


def test_config_file_loads_and_rejects_unknown_keys(tmp_path: Path) -> None:
    cfg = baselines.load("simplerca", SimpleRcaConfig)
    assert cfg.metric.sigma == 3.0 and cfg.trace.factor == 3.0 and "exception" in cfg.log.keywords
    bad = tmp_path / "bench" / "baselines.yaml"
    bad.parent.mkdir()
    bad.write_text("simplerca: {metric: {sigma: 3, percentile: 95, extra: 1}}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="simplerca"):
        baselines.load("simplerca", SimpleRcaConfig, tmp_path)
    with pytest.raises(ConfigError, match="no `rcaeval` section"):
        baselines.section("rcaeval", tmp_path)
