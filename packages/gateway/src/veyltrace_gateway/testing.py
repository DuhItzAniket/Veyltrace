"""Test helpers for the live path: OTLP/JSON request builders and a stub converter (tests only).

Why a stub: Infralume's converter (`veyltrace_infralume.otlp`, O-07) does not exist yet, and the
gateway must not implement it (06 §3.3). `StubConverter` maps only the few OTLP fields the tests
send onto canonical rows, with no normalisation or scrubbing, so the receiver, buffer and snapshot
can be tested end to end through the same seam the real module will use. Never used at runtime.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final, cast

import pyarrow as pa

from veyltrace_core.io import TELEMETRY, arrow_schema

__all__ = ["StubConverter", "otlp_gauge", "otlp_spans"]

_KINDS: Final = {1: "internal", 2: "server", 3: "client", 4: "producer", 5: "consumer"}
_STATUS_ERROR: Final = 2  # OTLP STATUS_CODE_ERROR
_SCRUB: Final = {"dropped_attributes": 0}


def _resource(service: str) -> dict[str, Any]:
    return {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]}


def otlp_spans(service: str, spans: Sequence[tuple[str, str, int, int, bool]]) -> dict[str, Any]:
    """An ExportTraceServiceRequest (protobuf-JSON) of `(trace_id, span_id, start_ns, end_ns,
    error)` server spans of one service; ids are hex, as in a capture's `otlp/*.jsonl`."""
    items = [
        {
            "traceId": trace, "spanId": span, "parentSpanId": "", "name": "GET /", "kind": 2,
            "startTimeUnixNano": str(start), "endTimeUnixNano": str(end),
            "status": {"code": _STATUS_ERROR if error else 0},
        }
        for trace, span, start, end, error in spans
    ]  # fmt: skip
    return {"resourceSpans": [{"resource": _resource(service), "scopeSpans": [{"spans": items}]}]}


def otlp_gauge(service: str, name: str, points: Sequence[tuple[int, float]]) -> dict[str, Any]:
    """An ExportMetricsServiceRequest with one gauge of `(t_ns, value)` points."""
    data = [{"timeUnixNano": str(t), "asDouble": v} for t, v in points]
    metric = {"name": name, "unit": "1", "gauge": {"dataPoints": data}}
    return {"resourceMetrics": [{"resource": _resource(service), "scopeMetrics": [{"metrics": [metric]}]}]}


def _service(resource: Mapping[str, Any]) -> str:
    attrs = cast(list[dict[str, Any]], resource.get("resource", {}).get("attributes", []))
    return next(str(a["value"]["stringValue"]) for a in attrs if a["key"] == "service.name")


class StubConverter:
    """The `OtlpConverter` seam for tests: spans and gauges only; logs are always empty."""

    def spans(
        self, request: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> tuple[pa.Table, Mapping[str, int]]:
        rows = [
            {
                "trace_id": s["traceId"], "span_id": s["spanId"], "parent_span_id": s["parentSpanId"] or None,
                "service": _service(rs), "component": _service(rs), "operation": s["name"],
                "kind": _KINDS.get(int(s["kind"]), "unspecified"), "start_ns": int(s["startTimeUnixNano"]),
                "end_ns": int(s["endTimeUnixNano"]),
                "status": "error" if s["status"]["code"] == _STATUS_ERROR else "unset",
                "status_code": None, "attrs_json": None,
            }
            for rs in request["resourceSpans"]
            for ss in rs["scopeSpans"]
            for s in ss["spans"]
        ]  # fmt: skip
        return pa.Table.from_pylist(rows, schema=arrow_schema(TELEMETRY["spans"])), _SCRUB

    def metrics(
        self, request: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> tuple[pa.Table, Mapping[str, int]]:
        rows = [
            {
                "t_ns": int(p["timeUnixNano"]), "service": _service(rm), "component": _service(rm),
                "name": m["name"], "metric_type": "gauge", "attrs_json": None, "value": float(p["asDouble"]),
                "unit": m.get("unit"), "source_system": "otlp",
            }
            for rm in request["resourceMetrics"]
            for sm in rm["scopeMetrics"]
            for m in sm["metrics"]
            for p in m["gauge"]["dataPoints"]
        ]  # fmt: skip
        return pa.Table.from_pylist(rows, schema=arrow_schema(TELEMETRY["metrics"])), _SCRUB

    def logs(
        self, request: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> tuple[pa.Table, Mapping[str, int]]:
        _ = request["resourceLogs"]  # a malformed request still fails, as the real converter would
        return arrow_schema(TELEMETRY["logs"]).empty_table(), _SCRUB
