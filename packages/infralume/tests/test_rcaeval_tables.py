"""RCAEval raw tables → canonical rows (01 §3.3), on in-memory Arrow tables."""

from __future__ import annotations

import numpy as np
import pyarrow as pa

from veyltrace_core.adapters import TelemetryTables
from veyltrace_infralume.adapters.rcaeval_tables import epoch_ns, logs_table, metrics_table, spans_table
from veyltrace_infralume.names import NameRules
from veyltrace_infralume.scrub import Scrubber, ScrubRules, folder_tokens
from veyltrace_infralume.status import StatusRules

NS = 1_000_000_000
T0 = 1_705_353_846  # seconds, as the Hugging Face mirror stores metric and log times
KEY = "re2ob_cartservice_cpu_1"
OB = NameRules({"frontendservice": "frontend"}, ("-db",), frozenset({"istio-init", "istio-proxy", "pod"}))
STATUS = StatusRules(frozenset({0, 1, 2}), 500)


def _scrubber() -> Scrubber:
    rules = ScrubRules("scrub-1", ("feature_flag.*", "chaos*", "fault*", "inject*"), frozenset({"flagd"}))
    return Scrubber(rules, folder_tokens(KEY, f"rcaeval/hf/{KEY}"))


def test_metrics_unpivot_units_and_dropped_points() -> None:
    nan, s = float("nan"), _scrubber()
    raw = pa.table({
        "time": [T0, T0 + 1, T0 + 2], "carts-db_mem": [1.0, nan, 3.0],
        "frontend_latency-90": [0.1, 0.2, float("inf")], "istio-init_cpu": [0.5, 0.5, nan],
        "flagd_cpu": [1.0, nan, nan], "time.1": [T0, T0 + 1, T0 + 2],
    })  # fmt: skip
    rows = metrics_table(raw, OB, s).to_pylist()
    assert [(r["service"], r["component"], r["name"], r["t_ns"] // NS, r["unit"]) for r in rows] == [
        ("carts", "carts-db", "mem", T0, "bytes"), ("carts", "carts-db", "mem", T0 + 2, "bytes"),
        ("frontend", "frontend", "latency-90", T0, "s"), ("frontend", "frontend", "latency-90", T0 + 1, "s"),
    ]  # fmt: skip
    assert {r["source_system"] for r in rows} == {"prom"}
    assert s.dropped_rows == 3  # istio-init x2 (a sidecar), flagd x1 (a fault tool)


def test_logs_time_unit_severity_pod_and_attrs() -> None:
    s = _scrubber()
    raw = pa.table({
        "timestamp": [T0, T0 + 1, None, T0 + 2],
        "container_name": ["cartservice", "flagd", "frontend", "frontend"],
        "message": [f"read /{KEY}/x", "on", "ok", None], "level": ["warning", None, None, "bogus"],
        "pod_name": ["cartservice-6f9c7b5d4c-x2kqz", None, None, None], "time": ["21:24"] * 4,
        "req_path": ["/cart", None, None, None], "fault_type": ["cpu", None, None, None],
    })  # fmt: skip
    rows = logs_table(raw, OB, s).to_pylist()
    assert [(r["service"], r["component"], r["t_ns"], r["severity"]) for r in rows] == [
        ("cartservice", "cartservice-6f9c7b5d4c-x2kqz", T0 * NS, "WARN"),
        ("frontend", "frontend", (T0 + 2) * NS, None),
    ]  # fmt: skip
    assert [r["body"] for r in rows] == ["read /<case>/x", ""]  # tokens replaced; a null message is ""
    assert [r["attrs_json"] for r in rows] == ['{"req_path":"/cart"}', None]
    assert (s.dropped_attributes, s.dropped_rows) == (1, 2)  # fault_type; flagd and the timeless line


def _spans(**columns: list[object]) -> pa.Table:
    us = T0 * 1_000_000
    base: dict[str, list[object]] = {
        "traceID": ["t1", "t1", "t1", "t1", "t2"], "spanID": ["0a", "0b", "0b", "0c", "0d"],
        "parentSpanID": [None, "0a", "0a", "", None],
        "serviceName": ["frontendservice", "cartservice", "cartservice", "carts-db", "cartservice"],
        "methodName": [None, "GetCart", "GetCart", "", "Empty"],
        "operationName": ["frontend", f"/{KEY}", "dup", "op", "x"],
        "startTimeMillis": [us // 1000, 0, 0, 0, 0], "startTime": [us, us + 10, us + 20, None, us + 40],
        "duration": [1000, 50, 50, 5, -1], "statusCode": [0, 2, 2, None, 0],
    }  # fmt: skip
    return pa.table({**base, **columns})


def test_spans_times_operation_status_and_dedupe() -> None:
    rows = {
        (r["trace_id"], r["span_id"]): r for r in spans_table(_spans(), OB, STATUS, _scrubber()).to_pylist()
    }
    assert sorted(rows) == [("t1", "0a"), ("t1", "0b"), ("t1", "0c")]  # repeated 0b and negative 0d dropped
    root, child, db = rows["t1", "0a"], rows["t1", "0b"], rows["t1", "0c"]
    assert (root["service"], root["component"], root["operation"], root["parent_span_id"]) == (
        "frontend", None, "frontend", None,
    )  # fmt: skip
    assert (root["start_ns"], root["end_ns"], root["kind"]) == (T0 * NS, T0 * NS + 1_000_000, "unspecified")
    assert (child["operation"], child["status"], child["status_code"], child["start_ns"]) == (
        "GetCart", "error", 2, T0 * NS + 10_000,
    )  # the first of the two 0b rows in key order  # fmt: skip
    assert (db["service"], db["component"], db["parent_span_id"], db["status"]) == (
        "carts",
        "carts-db",
        None,
        "unset",
    )
    assert db["start_ns"] == 0  # no startTime: startTimeMillis × 10^6


def test_spans_http_codes_from_csv_floats() -> None:
    raw = _spans(statusCode=[503.0, 200.0, 200.0, float("nan"), 0.0])
    rows = {
        r["span_id"]: (r["status"], r["status_code"])
        for r in spans_table(raw, OB, STATUS, _scrubber()).to_pylist()
    }
    assert rows == {"0a": ("error", 503), "0b": ("ok", 200), "0c": ("unset", None)}


def test_tables_fit_the_contracts_and_empty_inputs() -> None:
    s = _scrubber()
    TelemetryTables.from_tables(
        metrics=metrics_table(pa.table({"time": [T0], "cartservice_cpu": [0.1]}), OB, s),
        logs=logs_table(pa.table({"timestamp": [T0], "container_name": ["cartservice"]}), OB, s),
        spans=spans_table(_spans(), OB, STATUS, s),
    )  # raises if a column type or nullability differs from the contract  # fmt: skip
    empty = pa.Table.from_arrays([], names=[])
    assert metrics_table(empty, OB, s).num_rows == logs_table(empty, OB, s).num_rows == 0
    assert spans_table(empty, OB, STATUS, s).num_rows == 0


def test_epoch_units() -> None:
    for scale in (1, 1_000, 1_000_000, 1_000_000_000):
        assert epoch_ns(np.array([T0 * scale], dtype=np.int64)).tolist() == [T0 * NS]
