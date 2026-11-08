"""Metric series (02 §3.2): family rules, collisions, units, counters."""

from __future__ import annotations

from typing import Any

import numpy as np
import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_core.config import resolve_config
from veyltrace_signalyth.metrics import MetricRules, metric_series, sanitise

RULES = MetricRules.from_config(resolve_config({}, ai_mode="off").engine("signalyth"))
NS = 1_000_000_000


@pytest.mark.parametrize(
    ("name", "signal", "family", "klass"),
    [
        ("cpu", "cpu", "cpu", "internal"),
        ("mem", "mem", "mem", "internal"),
        ("diskio", "diskio", "disk", "internal"),
        ("socket", "socket", "net", "internal"),
        ("workload", "workload", "traffic", "context"),
        ("error", "error", "errors", "external"),
        ("latency-50", "latency_p50", "latency", "external"),
        ("latency-90", "latency_p90", "latency", "external"),
        ("container_cpu_usage_seconds_total", "cpu", "cpu", "internal"),
        ("container_fs_reads_total", "disk", "disk", "internal"),
        ("net_rx", "net", "net", "internal"),
        ('http_duration_seconds{quantile="0.99"}', "latency_p99", "latency", "external"),
        ("http_requests_total", "rps", "traffic", "context"),
        ("cpu_quota", "cpu_quota", "other", "context"),  # rule 0 before the cpu rule
        ("load", "load", "other", "context"),
        ("weird name|x", "weird-name-x", "other", "context"),
    ],
)
def test_family_rules(name: str, signal: str, family: str, klass: str) -> None:
    rule = RULES.classify(name)
    assert (rule.signal_for(name), rule.family, rule.klass) == (signal, family, klass)


def _table(rows: list[dict[str, Any]]) -> pa.Table:
    return pa.Table.from_pylist(rows)


def _rows(name: str, values: list[float], unit: str | None = None, svc: str = "cart") -> list[dict[str, Any]]:
    return [
        {"t_ns": i * NS, "service": svc, "component": svc, "name": name, "value": v, "unit": unit}
        for i, v in enumerate(values)
    ]


def _series(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    out = metric_series(_table(rows), RULES)
    return list(zip(out["signal"], out["unit"], out["t_ns"], out["value"], strict=True))


def test_latency_to_ms_and_memory_bytes() -> None:
    assert _series(_rows("latency-90", [0.25, 0.5], "s")) == [
        ("latency_p90", "ms", 0, 250.0),
        ("latency_p90", "ms", NS, 500.0),
    ]
    assert _series(_rows("mem", [7.0], None))[0][:2] == ("mem", "bytes")


def test_collisions_rename_every_member() -> None:
    out = metric_series(_table(_rows("cpu", [1.0]) + _rows("process_cpu_seconds", [2.0])), RULES)
    assert sorted(set(out["signal"])) == ["cpu:cpu", "cpu:process_cpu_seconds"]
    other = metric_series(_table(_rows("cpu", [1.0]) + _rows("cpu", [2.0], svc="frontend")), RULES)
    assert set(other["signal"]) == {"cpu"}  # different services do not collide


def test_named_counter_rate_with_reset() -> None:
    assert _series(_rows("http_requests_total", [10, 20, 40, 5], None)) == [
        ("rps", "1/s", NS, 10.0),
        ("rps", "1/s", 2 * NS, 20.0),
        ("rps", "1/s", 3 * NS, 5.0),
    ]  # the drop 40 -> 5 is a reset: the new value counts from zero


def test_shape_counter_and_excluded_families() -> None:
    climbing = [float(i) for i in range(20)]
    assert {s[0] for s in _series(_rows("socket", climbing, "count"))} == {"socket"}
    assert _series(_rows("socket", climbing, "count"))[0][1] == "count/s"
    assert len(_series(_rows("socket", climbing))) == 19  # first point has no rate
    assert len(_series(_rows("mem", climbing))) == 20  # memory leaks stay gauges
    flat = [1.0, 1.0, 2.0, 1.0] * 5
    assert len(_series(_rows("socket", flat))) == 20  # not monotone: gauge


@given(st.lists(st.floats(0, 1e6, allow_nan=False), min_size=2, max_size=40))
def test_counter_rates_are_never_negative(values: list[float]) -> None:
    out = metric_series(_table(_rows("x_total", values)), RULES)
    assert all(v >= 0 for v in out["value"])


def test_sanitise_and_empty() -> None:
    assert sanitise("a b|c") == "a-b-c"
    empty = pa.table(
        {
            "t_ns": pa.array([], pa.int64()),
            "service": pa.array([], pa.string()),
            "component": pa.array([], pa.string()),
            "name": pa.array([], pa.string()),
            "value": pa.array([], pa.float64()),
            "unit": pa.array([], pa.string()),
        }
    )
    assert metric_series(empty, RULES)["t_ns"] == []
    assert np.isfinite(metric_series(_table(_rows("cpu", [0.5, 0.25])), RULES)["value"]).all()
