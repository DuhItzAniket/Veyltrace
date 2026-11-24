"""The OTLP → canonical converter (01 §3.9) on small synthetic OTLP/JSON requests.

The requests are written by hand in the protobuf-JSON mapping the Collector's file exporter and
the gateway send (#24): lowerCamelCase, hex ids, 64-bit integers as strings. No captured data.
"""

from __future__ import annotations

import copy
import random
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


def _sid(short: str) -> str:
    """A 16-hex span id from a two-character test id."""
    return short.rjust(16, "0") if len(short) == 2 else short


def _span(span_id: str, start: int = T, end: int = T + 5, **fields: Any) -> dict[str, Any]:
    base = {"traceId": TRACE, "spanId": _sid(span_id), "name": "GET /cart", "kind": 2,
            "startTimeUnixNano": str(start), "endTimeUnixNano": str(end)}  # fmt: skip
    return base | fields


def _traces(*resources: tuple[dict[str, Any], list[dict[str, Any]]]) -> dict[str, Any]:
    return {"resourceSpans": [{"resource": r, "scopeSpans": [{"spans": s}]} for r, s in resources]}


def _rows(table: pa.Table) -> list[dict[str, Any]]:
    return table.to_pylist()


def test_spans_are_canonical(infralume_cfg: EngineConfig) -> None:
    child = _kv(rpc__grpc__status_code=0, feature_flag__key="x", peer="redis")
    request = _traces(
        (
            _resource("Cart_Service", k8s__pod__name=POD),
            [
                _span(
                    "0B",
                    parentSpanId=_sid("0a"),
                    kind="SPAN_KIND_CLIENT",
                    status={"code": 2},
                    attributes=child,
                ),
                _span("0a", parentSpanId="", attributes=_kv(http__response__status_code=503)),
            ],
        ),
    )
    table, counts = otlp.spans(request, infralume_cfg)
    assert table.schema.equals(arrow_schema("telemetry.spans"))
    root, child = _rows(table)
    assert root == {
        "trace_id": TRACE.lower(), "span_id": _sid("0a"), "parent_span_id": None, "service": "cart-service",
        "component": POD, "operation": "GET /cart", "kind": "server", "start_ns": T, "end_ns": T + 5,
        "status": "error", "status_code": 503, "attrs_json": '{"http.response.status_code":503}',
    }  # fmt: skip
    assert (child["span_id"], child["parent_span_id"], child["kind"]) == (_sid("0b"), _sid("0a"), "client")
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
        (0, {"http__status_code": 503}, "error", 503),  # pre-1.21 semconv name (lead decision, #24)
        (0, {"http__status_code": 200, "rpc__grpc__status_code": 14}, "ok", 200),
        (0, {"http__status_code": 200, "http__response__status_code": 500}, "error", 500),
        ("STATUS_CODE_FROM_A_NEWER_SDK", {}, "unset", None),  # an unknown enum name reads as 0
    ],
)
def test_span_status_rule(
    infralume_cfg: EngineConfig, native: object, attrs: dict[str, int], status: str, code: int | None
) -> None:
    request = _traces((_resource("cart"), [_span("0a", status={"code": native}, attributes=_kv(**attrs))]))
    (row,) = _rows(otlp.spans(request, infralume_cfg)[0])
    assert (row["status"], row["status_code"], row["component"]) == (status, code, None)


def test_spans_dropped(infralume_cfg: EngineConfig) -> None:
    # proto3 JSON leaves out a zero field: a span without a start time has no timestamp (01 §6)
    untimed = {k: v for k, v in _span("11").items() if k != "startTimeUnixNano"}
    request = _traces(
        (_resource("cart"), [_span("0a"), _span("0a", end=T + 9), _span("0c", end=T - 1), untimed]),
        (_resource("flagd"), [_span("0d")]),  # fault tool: scrub.drop_services
        (_resource("istio-proxy"), [_span("0e")]),  # sidecar: normalise.drop_containers
        (_resource(None), [_span("0f")]),  # no service.name
        (_resource("unknown_service:java"), [_span("10")]),  # no valid name
    )
    table, counts = otlp.spans(request, infralume_cfg)
    assert [(r["span_id"], r["end_ns"]) for r in _rows(table)] == [(_sid("0a"), T + 5)]
    assert counts == {"dropped_attributes": 0, "dropped_rows": 2}


def test_unknown_kind_and_keyless_attribute(infralume_cfg: EngineConfig) -> None:
    """A newer SDK's enum name, or an attribute whose empty key proto3 JSON left out, fails nothing."""
    span = _span("0a", kind="SPAN_KIND_FROM_A_NEWER_SDK", attributes=[{"value": {"stringValue": "x"}}])
    (row,) = _rows(otlp.spans(_traces((_resource("cart"), [span])), infralume_cfg)[0])
    assert (row["kind"], row["attrs_json"]) == ("unspecified", '{"":"x"}')


def test_empty_request(infralume_cfg: EngineConfig) -> None:
    table, counts = otlp.spans({}, infralume_cfg)
    assert table.num_rows == 0
    assert table.schema.equals(arrow_schema("telemetry.spans"))
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
        _traces((_resource("cart"), [_span("123456789012")])),  # base64 length, digits only
        _traces((_resource("cart"), [_span("0a", traceId="1" * 24)])),
        _traces((_resource("cart"), [_span("0a", parentSpanId="0a")])),
        _traces(({"attributes": "x"}, [_span("0a")])),
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
    shuffled = list(spans)
    random.Random(seed).shuffle(shuffled)  # a seeded shuffle of test data
    request = _traces((_resource("a"), shuffled))
    before = copy.deepcopy(request)
    assert otlp.spans(request, cfg)[0].equals(otlp.spans(_traces((_resource("a"), spans)), cfg)[0])
    assert request == before
