"""OTLP → canonical converter (01 §3.9, O-07): one OTLP/JSON export request in, one table out.

Why here: the gateway's live receiver (06 §3.3) must not parse telemetry semantics, so
it hands each decoded request to `spans`, `metrics` or `logs` and buffers what comes back. The
interface was agreed on #24: `request` is the protobuf-JSON mapping of one Export*ServiceRequest
(lowerCamelCase fields, hex ids, 64-bit integers as decimal strings), `settings` is the `infralume`
config section, and the result is the contract-typed table, normalised (§3.4), scrubbed (§3.6)
and in canonical row order, plus the scrub counts. Pure functions: no I/O, no clock, no state
between calls, and no protobuf dependency (the gateway decodes protobuf itself).

Choices the spec table leaves open (listed on #24): no per-system alias is applied, because a
request does not say which system it is; a resource without a usable `service.name` is dropped
and logged; the HTTP/gRPC status rule never uses the case-level OTel reading of §3.5 rule 1, so a
span's status does not depend on the other spans of its request; a non-monotonic cumulative Sum
is a gauge; delta data, exponential histograms and summaries are skipped and logged.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

import pyarrow as pa
import pyarrow.compute as pc

from veyltrace_core.canonical import canonical_json_str, normalize
from veyltrace_core.errors import CaseRejected
from veyltrace_core.io import contract_info
from veyltrace_core.log import get_logger
from veyltrace_infralume.adapters.rcaeval_tables import distinct_spans, typed_table
from veyltrace_infralume.names import InvalidName, NameRules
from veyltrace_infralume.scrub import Scrubber, ScrubRules
from veyltrace_infralume.status import ERROR, OK, StatusRules, span_status

__all__ = ["METRIC_LABEL_KEYS", "logs", "metrics", "spans"]

_pc: Any = pc  # pyarrow-stubs type compute kernels with Unknown parts (as rcaeval_tables)
_log = get_logger(__name__)

#: `otlp.metric_label_keys` (01 §4: a priori; HTTP stable semconv, RPC release candidate). A named
#: constant until the key can be added to config/infralume.yaml: a new key changes every run's
#: config hash, and the golden verdicts cannot be regenerated before #256 is closed.
METRIC_LABEL_KEYS: Final = ("http.response.status_code", "http.route", "rpc.method")
#: Span attributes holding the HTTP, else gRPC, status code (01 §3.5).
_CODE_KEYS: Final = ("http.response.status_code", "rpc.grpc.status_code")
#: The system whose aliases apply: none, as one request does not name its system (#24).
_NO_SYSTEM: Final = "other"
# OTLP enums by number (opentelemetry-proto); the JSON mapping may also carry the name.
_KINDS: Final = ("unspecified", "internal", "server", "client", "producer", "consumer")
_STATUS: Final = ("unset", OK, ERROR)
_TEMPORALITY: Final = ("unspecified", "delta", "cumulative")
_LEVELS: Final = ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL")
_PER_LEVEL: Final = 4  # severity numbers 1–4 are TRACE…TRACE4, 5–8 DEBUG…, up to 24 (01 §3.9)
_SEVERITIES: Final = (
    "unspecified",
    *(f"{lv}{i if i > 1 else ''}".lower() for lv in _LEVELS for i in range(1, _PER_LEVEL + 1)),
)
_TOPS: Final = frozenset({"resourceSpans", "resourceMetrics", "resourceLogs"})
_HEX: Final = re.compile(r"[0-9a-fA-F]+")

type Json = Mapping[str, Any]


@dataclass
class _Rules:
    names: NameRules
    status: StatusRules
    scrub: Scrubber


def _items(obj: Json, key: str) -> list[Json]:
    """`obj[key]` as a list of objects ([] when absent); anything else is a malformed request."""
    value: object = obj.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, Mapping) for v in cast("list[object]", value)):
        raise TypeError(f"{key} is not a list of objects")
    return cast("list[Json]", value)


def _int(value: object) -> int:
    """A protobuf-JSON integer: a number or its decimal string (64-bit values are strings)."""
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise TypeError(f"expected an integer, got {value!r}")
    return int(value)


def _enum(value: object, names: tuple[str, ...], prefix: str) -> int:
    """An enum given as its number or its name; a number this code does not know reads as 0."""
    if isinstance(value, str) and not value.isdigit():
        return names.index(value.removeprefix(prefix).lower())
    number = _int(value)
    return number if 0 <= number < len(names) else 0


def _hex(value: object) -> str | None:
    """A trace or span id as lowercase hex; empty or absent → None. Base64 (what a plain protobuf
    to JSON dump writes for bytes) is refused: OTLP/JSON ids are hex."""
    if value in (None, ""):
        return None
    if not isinstance(value, str) or _HEX.fullmatch(value) is None:
        raise ValueError(f"id {value!r} is not hex")
    return value.lower()


def _any(value: Json) -> object:
    """An OTLP AnyValue as a plain JSON value (bytes stay as their base64 text)."""
    if "intValue" in value:
        return _int(value["intValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "arrayValue" in value:
        return [_any(v) for v in _items(value["arrayValue"], "values")]
    if "kvlistValue" in value:
        return _attrs(value["kvlistValue"], "values")
    return next((value[k] for k in ("stringValue", "boolValue", "bytesValue") if k in value), None)


def _attrs(obj: Json, key: str = "attributes") -> dict[str, object]:
    return {str(kv["key"]): _any(kv.get("value", {})) for kv in _items(obj, key)}


def _identity(resource: Json, names: NameRules) -> tuple[str, str] | Literal[False] | None:
    """(service, component) of a resource (01 §3.9): `service.name`, and the pod name, else the
    instance id, else the service. None: no usable service name. False: a dropped container."""
    attrs = _attrs(resource)
    raw = attrs.get("service.name")
    try:
        named = names.normalise(raw) if isinstance(raw, str) and raw.strip() else None
    except InvalidName:
        return None
    if named is None:
        return None if not (isinstance(raw, str) and raw.strip()) else False
    for key, pod in (("k8s.pod.name", True), ("service.instance.id", False)):
        value = attrs.get(key)
        if not (isinstance(value, str) and value.strip()):
            continue
        try:
            part = names.normalise(value, pod=pod)
        except InvalidName:
            continue
        if part is not None:
            return named.service, part.component
    return named.service, named.component


def _records(
    request: Json, top: str, scope: str, leaf: str, rules: _Rules
) -> Iterator[tuple[tuple[str, str] | None, Json]]:
    """Every leaf record with its (service, component); None for a dropped container's record,
    which the caller counts. Records of an unnamed resource are skipped and logged (01 §6)."""
    unnamed = 0
    for resource in _items(request, top):
        found = [r for s in _items(resource, scope) for r in _items(s, leaf)]
        who = _identity(resource.get("resource", {}), rules.names)
        if who is None:
            unnamed += len(found)
            continue
        yield from ((who if isinstance(who, tuple) else None, r) for r in found)
    if unnamed:
        _log.info("infralume.rows_dropped", source=top, records=unnamed)


def _finish(columns: Mapping[str, list[Any]], contract: str, rules: _Rules) -> pa.Table:
    """The contract-typed table in canonical order (03 key, then the other columns, nulls first),
    without the rows of fault-tool services."""
    table = typed_table({k: pa.array(v) for k, v in columns.items()}, contract)
    key = contract_info(contract).key
    by = (*key, *(c for c in table.column_names if c not in key))
    table = table.take(_pc.sort_indices(table, sort_keys=[(c, "ascending", "at_start") for c in by]))
    return rules.scrub.drop_rows(table, ("service", "component"))


def _spans(request: Json, rules: _Rules) -> pa.Table:
    names = ("trace_id", "span_id", "parent_span_id", "service", "component", "operation", "kind",
             "start_ns", "end_ns", "status", "status_code", "attrs_json")  # fmt: skip
    cols: dict[str, list[Any]] = {n: [] for n in names}
    native: list[str] = []
    for who, span in _records(request, "resourceSpans", "scopeSpans", "spans", rules):
        if who is None:
            rules.scrub.dropped_rows += 1
            continue
        attrs = _attrs(span)
        codes = [v for k in _CODE_KEYS if isinstance(v := attrs.get(k), int) and not isinstance(v, bool)]
        trace, span_id = _hex(span.get("traceId")), _hex(span.get("spanId"))
        if trace is None or span_id is None:
            raise ValueError("a span has no traceId or spanId")
        kind = _KINDS[_enum(span.get("kind", 0), _KINDS, "SPAN_KIND_")]
        row = (trace, span_id, _hex(span.get("parentSpanId")), who[0], who[1] if who[1] != who[0] else None,
               rules.scrub.text(str(span.get("name", ""))), kind, _int(span["startTimeUnixNano"]),
               _int(span["endTimeUnixNano"]), None, codes[0] if codes else None,
               rules.scrub.attrs(attrs))  # fmt: skip
        for name, value in zip(names, row, strict=True):
            cols[name].append(value)
        status: Json = span.get("status", {})
        native.append(_STATUS[_enum(status.get("code", 0), _STATUS, "STATUS_CODE_")])
    if not native:
        return _finish(cols, "telemetry.spans", rules)
    # 01 §3.5: the native status wins; an UNSET span gets the HTTP/gRPC rule on its code.
    by_code = span_status(pa.array(cols["status_code"], pa.int64()), rules.status).to_pylist()
    cols["status"] = [n if n != _STATUS[0] else c for n, c in zip(native, by_code, strict=True)]
    return distinct_spans(_finish(cols, "telemetry.spans", rules))


def _points(metric: Json) -> Iterator[tuple[str, str, Json, object]] | None:
    """(name, metric_type, point, raw value) per series point of one metric (01 §3.9 table), or
    None for a kind the table has no row for."""
    name = str(metric["name"])
    if "gauge" in metric:
        return ((name, "gauge", p, _number(p)) for p in _items(metric["gauge"], "dataPoints"))
    data: Json = metric.get("sum", metric.get("histogram", {}))
    kind = _enum(data.get("aggregationTemporality", 0), _TEMPORALITY, "AGGREGATION_TEMPORALITY_")
    if _TEMPORALITY[kind] != "cumulative":
        return None
    if "sum" in metric:
        if data.get("isMonotonic") is not True:
            return ((name, "gauge", p, _number(p)) for p in _items(data, "dataPoints"))
        total = name if name.endswith("_total") else f"{name}_total"
        return ((total, "counter", p, _number(p)) for p in _items(data, "dataPoints"))
    return (
        (f"{name}_{part}", "counter", p, _int(p[part]) if part == "count" else p.get(part))
        for p in _items(data, "dataPoints")
        for part in ("count", "sum")
    )


def _number(point: Json) -> object:
    """A number point's value; None when it has none (the no-recorded-value flag)."""
    return _int(point["asInt"]) if "asInt" in point else point.get("asDouble")


def _metrics(request: Json, rules: _Rules) -> pa.Table:
    series: dict[tuple[str, str, str, int], tuple[str, str | None, str | None, list[float]]] = {}
    skipped = 0
    for who, metric in _records(request, "resourceMetrics", "scopeMetrics", "metrics", rules):
        points = _points(metric)
        if points is None:
            skipped += 1
            continue
        unit = str(metric["unit"]) if metric.get("unit") else None
        for base, metric_type, point, raw in points:
            value = math.nan if raw is None else float(cast("Any", raw))
            if not math.isfinite(value):  # 01 §6: NaN/inf points are dropped
                continue
            if who is None:
                rules.scrub.dropped_rows += 1
                continue
            attrs = _attrs(point)
            labels = {k: attrs[k] for k in METRIC_LABEL_KEYS if k in attrs}
            text = ",".join(
                f"{k}={v if isinstance(v, str) else canonical_json_str(normalize(v))}"
                for k, v in sorted(labels.items())
            )
            name = rules.scrub.text(f"{base}{{{text}}}" if labels else base)
            key = (who[0], who[1], name, _int(point["timeUnixNano"]))
            series.setdefault(key, (metric_type, unit, rules.scrub.attrs(labels), []))[3].append(value)
    if skipped:
        _log.info("infralume.otlp_metrics_skipped", metrics=skipped)
    rows = [  # equal keys are combined: counters summed, gauges averaged (01 §3.9); fsum is exact
        (t, *who, kind, attrs, math.fsum(vs) / (1 if kind == "counter" else len(vs)), unit, "otlp")
        for (*who, t), (kind, unit, attrs, vs) in series.items()
    ]
    names = ("t_ns", "service", "component", "name", "metric_type", "attrs_json", "value", "unit",
             "source_system")  # fmt: skip
    cols = {n: [r[i] for r in rows] for i, n in enumerate(names)}
    return _finish(cols, "telemetry.metrics", rules)


def _logs(request: Json, rules: _Rules) -> pa.Table:
    names = ("t_ns", "service", "component", "severity", "body", "trace_id", "span_id", "attrs_json")
    cols: dict[str, list[Any]] = {n: [] for n in names}
    untimed = 0
    for who, record in _records(request, "resourceLogs", "scopeLogs", "logRecords", rules):
        t_ns = _int(record.get("timeUnixNano", 0)) or _int(record.get("observedTimeUnixNano", 0))
        if t_ns == 0:  # 01 §6: a log without a timestamp is dropped
            untimed += 1
            continue
        if who is None:
            rules.scrub.dropped_rows += 1
            continue
        level = _enum(record.get("severityNumber", 0), _SEVERITIES, "SEVERITY_NUMBER_")
        body = _any(record.get("body", {}))
        text = body if isinstance(body, str) else "" if body is None else canonical_json_str(normalize(body))
        row = (t_ns, who[0], who[1], _LEVELS[(level - 1) // _PER_LEVEL] if level else None,
               rules.scrub.text(text), _hex(record.get("traceId")), _hex(record.get("spanId")),
               rules.scrub.attrs(_attrs(record)))  # fmt: skip
        for name, value in zip(names, row, strict=True):
            cols[name].append(value)
    if untimed:
        _log.info("infralume.rows_dropped", source="logs", rows=untimed)
    return _finish(cols, "telemetry.logs", rules)


def _convert(
    build: Callable[[Json, _Rules], pa.Table], top: str, request: Json, settings: Json
) -> tuple[pa.Table, Mapping[str, int]]:
    rules = _Rules(
        NameRules.from_config(settings, _NO_SYSTEM),
        # No code is an OTel status here (see the module docstring), so rule 1's set is empty.
        StatusRules(frozenset(), StatusRules.from_config(settings).http_error_min),
        Scrubber(ScrubRules.from_config(settings)),
    )
    try:
        if not isinstance(cast("object", request), Mapping) or (_TOPS - {top}) & request.keys():
            raise TypeError(f"not an OTLP/JSON request with {top}")
        table = build(request, rules)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:  # 01 §6: no partial output
        detail = f"malformed OTLP request: {type(exc).__name__}: {exc}"
        raise CaseRejected("invalid_capture", detail) from None
    counts = {"dropped_attributes": rules.scrub.dropped_attributes, "dropped_rows": rules.scrub.dropped_rows}
    return table, counts


def spans(request: Json, settings: Json) -> tuple[pa.Table, Mapping[str, int]]:
    """One ExportTraceServiceRequest → `telemetry.spans` and the scrub counts. Spans that end
    before they start, and repeats of a (trace, span) id, are dropped (01 §6)."""
    return _convert(_spans, "resourceSpans", request, settings)


def metrics(request: Json, settings: Json) -> tuple[pa.Table, Mapping[str, int]]:
    """One ExportMetricsServiceRequest → `telemetry.metrics` and the scrub counts; one row per
    (service, component, name, t_ns), with the label keys of 01 §3.9 folded into the name."""
    return _convert(_metrics, "resourceMetrics", request, settings)


def logs(request: Json, settings: Json) -> tuple[pa.Table, Mapping[str, int]]:
    """One ExportLogsServiceRequest → `telemetry.logs` and the scrub counts."""
    return _convert(_logs, "resourceLogs", request, settings)
