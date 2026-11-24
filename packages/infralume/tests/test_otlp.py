"""The OTLP → canonical converter (01 §3.9) on small synthetic OTLP/JSON requests.

The requests are written by hand in the protobuf-JSON mapping the Collector's file exporter and
the gateway send (#24): lowerCamelCase, hex ids, 64-bit integers as strings. No captured data.
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from veyltrace_core.config import EngineConfig, resolve_config
from veyltrace_core.errors import CaseRejected
from veyltrace_core.io import arrow_schema, encode
from veyltrace_infralume import otlp
from veyltrace_infralume.names import NameRules, Normalised
from veyltrace_infralume.scrub import Scrubber, ScrubRules

T = 1_764_000_000_000_000_000
TRACE = "5B8EFFF798038103D269B633813FC60C"
POD = "cartservice-579b9bff58-t2dbm"
FIXTURES = Path(__file__).parents[1] / "fixtures" / "handmade" / "otlp"


def _kv(**attrs: object) -> list[dict[str, Any]]:
    def value(v: object) -> dict[str, Any]:
        if isinstance(v, bool):
            return {"boolValue": v}
        if isinstance(v, int):
            return {"intValue": str(v)}
        return {"doubleValue": v} if isinstance(v, float) else {"stringValue": v}

    return [{"key": k.replace("__", "."), "value": value(v)} for k, v in attrs.items()]


def _resource(service: str | None, **more: object) -> dict[str, Any]:
    named = {} if service is None else {"service__name": service}
    return {"attributes": _kv(**named, **more)}


def _span(span_id: str, start: int = T, end: int = T + 5, **fields: Any) -> dict[str, Any]:
    base = {"traceId": TRACE, "spanId": span_id, "name": "GET /cart", "kind": 2,
            "startTimeUnixNano": str(start), "endTimeUnixNano": str(end)}  # fmt: skip
    return base | fields


def _traces(*resources: tuple[dict[str, Any], list[dict[str, Any]]]) -> dict[str, Any]:
    return {"resourceSpans": [{"resource": r, "scopeSpans": [{"spans": s}]} for r, s in resources]}


def _metrics(resource: dict[str, Any], *metrics: dict[str, Any]) -> dict[str, Any]:
    return {"resourceMetrics": [{"resource": resource, "scopeMetrics": [{"metrics": list(metrics)}]}]}


def _logs(resource: dict[str, Any], *records: dict[str, Any]) -> dict[str, Any]:
    return {"resourceLogs": [{"resource": resource, "scopeLogs": [{"logRecords": list(records)}]}]}


def _point(value: float | int, t: int = T, **attrs: object) -> dict[str, Any]:
    number = {"asInt": str(value)} if isinstance(value, int) else {"asDouble": value}
    return {"timeUnixNano": str(t), "attributes": _kv(**attrs), **number}


def _rows(table: pa.Table) -> list[dict[str, Any]]:
    return table.to_pylist()


def test_spans_are_canonical(infralume_cfg: EngineConfig) -> None:
    child = _kv(rpc__grpc__status_code=0, feature_flag__key="x", peer="redis")
    request = _traces(
        (
            _resource("Cart_Service", k8s__pod__name=POD),
            [
                _span("0B", parentSpanId="0a", kind="SPAN_KIND_CLIENT", status={"code": 2}, attributes=child),
                _span("0a", parentSpanId="", attributes=_kv(http__response__status_code=503)),
            ],
        ),
    )
    table, counts = otlp.spans(request, infralume_cfg)
    assert table.schema.equals(arrow_schema("telemetry.spans"))
    root, child = _rows(table)
    assert root == {
        "trace_id": TRACE.lower(), "span_id": "0a", "parent_span_id": None, "service": "cart-service",
        "component": POD, "operation": "GET /cart", "kind": "server", "start_ns": T, "end_ns": T + 5,
        "status": "error", "status_code": 503, "attrs_json": '{"http.response.status_code":503}',
    }  # fmt: skip
    assert (child["span_id"], child["parent_span_id"], child["kind"]) == ("0b", "0a", "client")
    assert (child["status"], child["status_code"]) == ("error", 0)  # the native status wins (§3.5)
    assert child["attrs_json"] == '{"peer":"redis","rpc.grpc.status_code":0}'
    assert counts == {"dropped_attributes": 1, "dropped_rows": 0}
    encode("telemetry.spans", table)  # the core writer accepts it as it is
    # Re-applying the rules, as `otlp_live` does on a snapshot, changes nothing (idempotent).
    again = Scrubber(ScrubRules.from_config(infralume_cfg))
    names = NameRules.from_config(infralume_cfg, "other")
    for row in (root, child):
        assert again.attrs_json(row["attrs_json"]) == row["attrs_json"]
        assert names.normalise(row["service"]) == Normalised(row["service"], row["service"])
    assert again.dropped_attributes == 0


@pytest.mark.parametrize(
    ("native", "attrs", "status", "code"),
    [
        (0, {}, "unset", None),
        (1, {"http__response__status_code": 500}, "ok", 500),
        ("STATUS_CODE_ERROR", {}, "error", None),
        (0, {"http__response__status_code": 200}, "ok", 200),
        (0, {"http__response__status_code": 500}, "error", 500),
        (0, {"rpc__grpc__status_code": 0}, "ok", 0),
        (0, {"rpc__grpc__status_code": 1}, "error", 1),  # CANCELLED: never read as OTel ok
        (0, {"rpc__grpc__status_code": 14, "http__response__status_code": 200}, "ok", 200),
    ],
)
def test_span_status_rule(
    infralume_cfg: EngineConfig, native: object, attrs: dict[str, int], status: str, code: int | None
) -> None:
    request = _traces((_resource("cart"), [_span("0a", status={"code": native}, attributes=_kv(**attrs))]))
    (row,) = _rows(otlp.spans(request, infralume_cfg)[0])
    assert (row["status"], row["status_code"], row["component"]) == (status, code, None)


def test_spans_dropped(infralume_cfg: EngineConfig) -> None:
    request = _traces(
        (_resource("cart"), [_span("0a"), _span("0a", end=T + 9), _span("0c", end=T - 1)]),
        (_resource("flagd"), [_span("0d")]),  # fault tool: scrub.drop_services
        (_resource("istio-proxy"), [_span("0e")]),  # sidecar: normalise.drop_containers
        (_resource(None), [_span("0f")]),  # no service.name
        (_resource("unknown_service:java"), [_span("10")]),  # no valid name
    )
    table, counts = otlp.spans(request, infralume_cfg)
    assert [(r["span_id"], r["end_ns"]) for r in _rows(table)] == [("0a", T + 5)]
    assert counts == {"dropped_attributes": 0, "dropped_rows": 2}


def test_metric_kinds(infralume_cfg: EngineConfig) -> None:
    cumulative = {"aggregationTemporality": 2}
    request = _metrics(
        _resource("carts-db", service__instance__id="A1"),
        {"name": "cpu", "unit": "1", "gauge": {"dataPoints": [_point(0.5), _point(float("nan"), T + 1)]}},
        {"name": "calls", "sum": cumulative | {"isMonotonic": True, "dataPoints": [_point(7)]}},
        {"name": "queue", "sum": cumulative | {"dataPoints": [_point(3)]}},
        {"name": "lat", "unit": "ms", "histogram": cumulative | {"dataPoints": [
            {"timeUnixNano": str(T), "count": "4", "sum": 9.5, "bucketCounts": ["4"]}]}},
        {"name": "delta", "sum": {"aggregationTemporality": 1, "isMonotonic": True,
                                  "dataPoints": [_point(1)]}},
        {"name": "quantiles", "summary": {"dataPoints": [{"timeUnixNano": str(T), "count": "1"}]}},
    )  # fmt: skip
    table, _ = otlp.metrics(request, infralume_cfg)
    assert table.schema.equals(arrow_schema("telemetry.metrics"))
    rows = _rows(table)
    assert {(r["service"], r["component"], r["source_system"]) for r in rows} == {("carts", "a1", "otlp")}
    assert [(r["name"], r["metric_type"], r["value"], r["unit"]) for r in rows] == [
        ("calls_total", "counter", 7.0, None), ("cpu", "gauge", 0.5, "1"),
        ("lat_count", "counter", 4.0, "ms"), ("lat_sum", "counter", 9.5, "ms"), ("queue", "gauge", 3.0, None),
    ]  # fmt: skip
    encode("telemetry.metrics", table)


def test_metric_labels_and_combining(infralume_cfg: EngineConfig) -> None:
    ok, bad = {"http__response__status_code": 200}, {"http__response__status_code": 500}
    sum_of = {"aggregationTemporality": "AGGREGATION_TEMPORALITY_CUMULATIVE", "isMonotonic": True}
    request = _metrics(
        _resource("frontend", k8s__pod__name="frontend-0"),
        {"name": "req_total", "sum": sum_of | {"dataPoints": [
            _point(3, http__route="/cart", http__method="GET", **ok),
            _point(4, http__route="/cart", http__method="POST", **ok),
            _point(1, http__route="/cart", fault__kind="x", **bad)]}},
        {"name": "load", "gauge": {"dataPoints": [_point(1.0, host="a"), _point(2.0, host="b")]}},
    )  # fmt: skip
    table, counts = otlp.metrics(request, infralume_cfg)
    assert [(r["name"], r["value"], r["attrs_json"]) for r in _rows(table)] == [
        ("load", 1.5, None),
        ("req_total{http.response.status_code=200,http.route=/cart}", 7.0,
         '{"http.response.status_code":200,"http.route":"/cart"}'),
        ("req_total{http.response.status_code=500,http.route=/cart}", 1.0,
         '{"http.response.status_code":500,"http.route":"/cart"}'),
    ]  # fmt: skip
    assert table.column("component").unique().to_pylist() == ["frontend-0"]
    assert counts == {"dropped_attributes": 0, "dropped_rows": 0}  # unlisted keys are never written


def test_logs_are_canonical(infralume_cfg: EngineConfig) -> None:
    request = _logs(
        _resource("cart"),
        {"timeUnixNano": str(T + 2), "severityNumber": 9, "body": {"stringValue": "fault injected? no"},
         "traceId": TRACE, "spanId": "0A", "attributes": _kv(chaos__kind="pod", thread="main")},
        {"timeUnixNano": "0", "observedTimeUnixNano": str(T + 1),
         "severityNumber": "SEVERITY_NUMBER_ERROR2", "body": {"kvlistValue": {"values": _kv(b=1, a="x")}}},
        {"timeUnixNano": str(T), "severityNumber": 99, "traceId": ""},
        {"severityNumber": 24, "body": {"stringValue": "no time"}},
    )  # fmt: skip
    table, counts = otlp.logs(request, infralume_cfg)
    assert table.schema.equals(arrow_schema("telemetry.logs"))
    assert [(r["t_ns"], r["severity"], r["body"]) for r in _rows(table)] == [
        (T, None, ""), (T + 1, "ERROR", '{"a":"x","b":1}'), (T + 2, "INFO", "fault injected? no"),
    ]  # fmt: skip
    last = _rows(table)[-1]
    assert (last["trace_id"], last["span_id"]) == (TRACE.lower(), "0a")
    assert last["attrs_json"] == '{"thread":"main"}'
    assert _rows(table)[0]["trace_id"] is None
    assert counts == {"dropped_attributes": 1, "dropped_rows": 0}
    encode("telemetry.logs", table)


@pytest.mark.parametrize("severity", range(1, 25))
def test_severity_ranges(infralume_cfg: EngineConfig, severity: int) -> None:
    levels = ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL")
    request = _logs(_resource("cart"), {"timeUnixNano": str(T), "severityNumber": severity})
    assert _rows(otlp.logs(request, infralume_cfg)[0])[0]["severity"] == levels[(severity - 1) // 4]


@pytest.mark.parametrize(
    ("name", "convert"), [("traces", otlp.spans), ("metrics", otlp.metrics), ("logs", otlp.logs)]
)
def test_handmade_capture_lines(infralume_cfg: EngineConfig, name: str, convert: Any) -> None:
    """Each line of the handmade `otlp/*.jsonl` files (the lab capture shape) converts to the
    reviewed rows and scrub counts in `expected.json`."""
    lines = (FIXTURES / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    expected = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))[name]
    assert len(lines) == len(expected)
    for line, want in zip(lines, expected, strict=True):
        table, counts = convert(json.loads(line), infralume_cfg)
        assert (table.to_pylist(), dict(counts)) == (want["rows"], want["scrub"])


def test_empty_requests(infralume_cfg: EngineConfig) -> None:
    for convert, contract in ((otlp.spans, "spans"), (otlp.metrics, "metrics"), (otlp.logs, "logs")):
        table, counts = convert({}, infralume_cfg)
        assert table.num_rows == 0
        assert table.schema.equals(arrow_schema(f"telemetry.{contract}"))
        assert counts == {"dropped_attributes": 0, "dropped_rows": 0}


@pytest.mark.parametrize(
    "request_",
    [
        [],
        {"resourceSpans": {}},
        {"resourceLogs": []},  # another signal's request
        _traces((_resource("cart"), [_span("W1Yx8Q==")])),  # a base64 id
        _traces((_resource("cart"), [_span("")])),
        _traces((_resource("cart"), [_span("0a", startTimeUnixNano=1.5)])),
        _traces((_resource("cart"), [_span("0a", kind="SPAN_KIND_NOPE")])),
        _traces(({"attributes": [{"value": {}}]}, [_span("0a")])),
    ],
)
def test_malformed_request_is_rejected(infralume_cfg: EngineConfig, request_: Any) -> None:
    with pytest.raises(CaseRejected) as caught:
        otlp.spans(request_, infralume_cfg)
    assert caught.value.reason == "invalid_capture"


@settings(deadline=None)  # the first call imports and resolves the config
@given(st.integers(0, 2**32))
def test_output_does_not_depend_on_request_order(seed: int) -> None:
    """Shuffling the records of a request changes nothing, and the request is not modified."""
    cfg = resolve_config({}, ai_mode="off").engine("infralume")  # hypothesis takes no function fixture
    spans = [_span(f"{i:016x}", start=T + i % 3, end=T + 9) for i in range(6)] + [_span(f"{0:016x}")]
    points = [_point(float(i), T + i % 2, http__route=f"/{i % 2}") for i in range(6)]
    logs = [{"timeUnixNano": str(T + i % 2), "body": {"stringValue": f"m{i % 3}"}} for i in range(6)]
    rng = random.Random(seed)
    for convert, build, items in (
        (otlp.spans, lambda x: _traces((_resource("a"), x)), spans),
        (otlp.metrics, lambda x: _metrics(_resource("a"), {"name": "g", "gauge": {"dataPoints": x}}), points),
        (otlp.logs, lambda x: _logs(_resource("a"), *x), logs),
    ):
        shuffled = list(items)
        rng.shuffle(shuffled)
        request = build(shuffled)
        before = copy.deepcopy(request)
        assert convert(request, cfg)[0].equals(convert(build(items), cfg)[0])
        assert request == before
