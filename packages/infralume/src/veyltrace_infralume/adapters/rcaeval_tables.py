"""RCAEval raw tables → canonical telemetry rows (01 §3.3), for the `rcaeval` adapter.

Pure functions over Arrow tables already read from one case: wide metrics unpivoted at the first
`_` with NaN/±inf points dropped, log lines with severity and an epoch-unit check, spans in
nanoseconds with the 01 §3.5 status. Names go through `NameRules` (§3.4) and every string column
through the case's `Scrubber` (§3.6), which counts the rows it drops. No file access here: the
adapter reads files through its allow-list and hands the tables over.
"""

from __future__ import annotations

from collections.abc import Mapping
from fnmatch import fnmatchcase
from typing import Any, Final, cast

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from veyltrace_core.io import arrow_schema, empty_table
from veyltrace_core.log import get_logger
from veyltrace_infralume.names import NameRules
from veyltrace_infralume.scrub import Scrubber
from veyltrace_infralume.status import StatusRules, span_status

__all__ = [
    "NS",
    "SEVERITY",
    "SPAN_COLUMNS",
    "UNITS",
    "epoch_ns",
    "logs_table",
    "metrics_table",
    "spans_table",
]

# pyarrow-stubs type compute kernels with Unknown parts; core's io.py uses the same Any alias.
_pc: Any = pc

_log = get_logger(__name__)

type Vec = np.ndarray[Any, Any]

NS: Final = 1_000_000_000

#: Epoch magnitudes (a priori: seconds have 10 digits until 2286): below 1e11 s, 1e14 ms, 1e17 us.
_EPOCH_UNITS: Final = ((10**11, NS), (10**14, 10**6), (10**17, 10**3))

#: 01 §3.3: `mem` is bytes, `latency-*` seconds (a trailing-minute p50/p90 / 1000); others unknown.
UNITS: Final = (("mem", "bytes"), ("latency-*", "s"))

#: `level` values → canonical severity (01 §3.3); anything else is null.
SEVERITY: Final = {
    "trace": "TRACE", "debug": "DEBUG", "info": "INFO", "warn": "WARN", "warning": "WARN",
    "err": "ERROR", "error": "ERROR", "critical": "FATAL", "fatal": "FATAL",
}  # fmt: skip

#: Log columns with a canonical place, and dropped ones (`time` is an HH:MM string; Signalyth mines
#: its own templates instead of `cluster_id`/`log_template`). Any other column goes to attrs_json.
_LOG_COLUMNS: Final = frozenset({"timestamp", "container_name", "message", "level", "pod_name"})

_LOG_DROPPED: Final = frozenset({"time", "cluster_id", "log_template"})

_SPAN_IDS: Final = ("traceID", "spanID", "parentSpanID")

SPAN_COLUMNS: Final = (
    *_SPAN_IDS, "serviceName", "methodName", "operationName",
    "startTime", "startTimeMillis", "duration", "statusCode",
)  # fmt: skip


def epoch_ns(values: Vec) -> Vec:
    """Unix times in s, ms, us or ns → ns, the unit read from the largest magnitude (the Hugging
    Face logs store seconds, not the nanoseconds rcaeval_facts documents)."""
    top = int(np.abs(values).max()) if values.size else 0
    return values.astype(np.int64) * np.int64(next((f for lim, f in _EPOCH_UNITS if top < lim), 1))


def _np(col: Any, dtype: Any) -> Vec:
    return np.asarray(
        col.to_numpy(zero_copy_only=False) if isinstance(col, pa.Array) else col.to_numpy(), dtype
    )


def _array(col: Any) -> pa.Array[Any]:
    return cast("pa.Array[Any]", col.combine_chunks() if isinstance(col, pa.ChunkedArray) else col)


def _col(table: pa.Table, name: str, kind: Any) -> Any:
    """Column `name` as `kind` (an all-null column arrives with Arrow's null type), or nulls of
    `kind` when the source file lacks it."""
    if name in table.column_names:
        return _pc.cast(table.column(name), kind)
    nulls: Any = cast("Any", pa).nulls(table.num_rows, kind)  # pa.nulls overloads are partly Unknown
    return nulls


def _strings(values: Vec) -> pa.Array[Any]:
    return pa.array(values, pa.string())


def _table(columns: Mapping[str, Any], contract: str | None = None) -> pa.Table:
    """A table from named columns, typed as the contract's fields when one is named (pa.table's
    stub overloads carry Unknown parts)."""
    if contract is None:
        return pa.Table.from_arrays(list(columns.values()), names=list(columns))
    schema: Any = arrow_schema(contract)
    fields = [schema.field(name) for name in columns]
    arrays = [
        _pc.cast(pa.array(cast("Vec", v)) if isinstance(v, np.ndarray) else v, f.type)
        for v, f in zip(columns.values(), fields, strict=True)
    ]
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def _names(col: Any, rules: NameRules, *, pod: bool = False) -> tuple[Vec, Vec, Vec]:
    """Per row (service, component, kept) for a raw name column; each distinct value normalised once."""
    encoded = _pc.dictionary_encode(col.combine_chunks() if isinstance(col, pa.ChunkedArray) else col)
    named = [
        rules.normalise(v, pod=pod) if v else None
        for v in cast("list[str | None]", encoded.dictionary.to_pylist())
    ]
    codes = _np(encoded.indices.fill_null(-1), np.int64)  # -1 picks the trailing "missing" entry
    service = np.array([n.service if n else None for n in named] + [None], dtype=object)[codes]
    component = np.array([n.component if n else None for n in named] + [None], dtype=object)[codes]
    return service, component, np.array([n is not None for n in named] + [False], dtype=bool)[codes]


def _unless_equal(component: Vec, service: Vec) -> Vec:
    """Span components: null unless they say more than the service (03 §2.4 `component?`)."""
    out = component.copy()
    out[component == service] = None
    return out


def _unit(name: str) -> str | None:
    return next((unit for pattern, unit in UNITS if fnmatchcase(name, pattern)), None)


def metrics_table(raw: pa.Table, rules: NameRules, scrub: Scrubber) -> pa.Table:
    """Wide `time` + `{service}_{metric}` columns → long rows; NaN/±inf points dropped (01 §3.3)."""
    if "time" not in raw.column_names:
        return empty_table("telemetry.metrics")
    t_ns = _np(raw.column("time"), np.float64).round().astype(np.int64) * np.int64(NS)
    parts: list[tuple[Vec, Vec, str, str, str, str | None]] = []
    for column in sorted(c for c in raw.column_names if not c.startswith("time")):  # `time.1` too
        prefix, _, metric = column.partition("_")
        values = _np(raw.column(column), np.float64)
        finite = np.isfinite(values)
        named = rules.normalise(prefix) if prefix and metric else None
        if named is None:
            scrub.dropped_rows += int(finite.sum())
            continue
        parts.append((t_ns[finite], values[finite], named.service, named.component, metric, _unit(metric)))
    if not parts:
        return empty_table("telemetry.metrics")
    sizes = [len(p[0]) for p in parts]

    def repeat(i: int) -> Vec:
        return np.repeat(np.array([p[i] for p in parts], dtype=object), sizes)

    table = _table({
        "t_ns": np.concatenate([p[0] for p in parts]), "service": _strings(repeat(2)),
        "component": _strings(repeat(3)), "name": scrub.text_column(_strings(repeat(4))),
        "value": np.concatenate([p[1] for p in parts]), "unit": _strings(repeat(5)),
        "source_system": _strings(np.full(sum(sizes), "prom", dtype=object)),
    }, "telemetry.metrics")  # fmt: skip
    return scrub.drop_rows(table, ("service", "component"))


def logs_table(raw: pa.Table, rules: NameRules, scrub: Scrubber) -> pa.Table:
    """One row per log line: ns time, normalised service, severity, body verbatim but for folder
    tokens (01 §3.3); a null message is an empty body (the line still counts)."""
    if "timestamp" not in raw.column_names or "container_name" not in raw.column_names:
        return empty_table("telemetry.logs")
    service, component, keep = _names(raw.column("container_name"), rules)
    if "pod_name" in raw.column_names:
        _, pod_component, pod_ok = _names(raw.column("pod_name"), rules, pod=True)
        component = np.where(pod_ok, pod_component, component)
    keep &= _np(raw.column("timestamp").is_valid(), bool)
    scrub.dropped_rows += int((~keep).sum())
    raw, service, component = raw.filter(pa.array(keep)), service[keep], component[keep]
    n = raw.num_rows
    level = _col(raw, "level", pa.string()).to_pylist()
    extras = sorted(c for c in raw.column_names if c not in _LOG_COLUMNS | _LOG_DROPPED)
    records: list[dict[str, object]] = (
        cast("list[dict[str, object]]", raw.select(extras).to_pylist()) if extras else [{}] * n
    )
    table = _table({
        "t_ns": epoch_ns(_np(raw.column("timestamp"), np.int64)), "service": _strings(service),
        "component": _strings(component),
        "severity": pa.array([SEVERITY.get(str(v).strip().lower()) if v else None for v in level],
                             pa.string()),
        "body": scrub.text_column(_pc.fill_null(_col(raw, "message", pa.string()), "")),
        "attrs_json": pa.array([scrub.attrs({k: v for k, v in r.items() if v is not None})
                                for r in records], pa.string()),
    }, "telemetry.logs")  # fmt: skip
    return scrub.drop_rows(table, ("service", "component"))


def spans_table(raw: pa.Table, rules: NameRules, status: StatusRules, scrub: Scrubber) -> pa.Table:
    """Spans in ns (us `startTime`, else ms `startTimeMillis`), operation = methodName if set else
    operationName, kind unspecified, status by 01 §3.5; negative durations and repeated span ids
    (first in key order kept) are dropped and logged (01 §6)."""
    if "traceID" not in raw.column_names or raw.num_rows == 0:
        return empty_table("telemetry.spans")
    service, component, keep = _names(raw.column("serviceName"), rules)
    scrub.dropped_rows += int((~keep).sum())
    raw, service, component = raw.filter(pa.array(keep)), service[keep], component[keep]
    cols = raw.column_names
    micros = _col(raw, "startTime", pa.int64())
    millis = (
        _np(_pc.fill_null(raw.column("startTimeMillis"), 0), np.int64) if "startTimeMillis" in cols else 0
    )
    start = np.where(
        _np(micros.is_valid(), bool), _np(_pc.fill_null(micros, 0), np.int64) * 1000, millis * 10**6
    )
    end = start + _np(_pc.fill_null(raw.column("duration"), 0), np.float64).round().astype(np.int64) * 1000
    method = _col(raw, "methodName", pa.string())
    has_method = _np(_pc.fill_null(_pc.greater(_pc.utf8_length(method), 0), False), bool)
    code = _col(raw, "statusCode", pa.float64())
    as_float = code
    codes = _pc.cast(_pc.round(_pc.if_else(_pc.is_nan(as_float), None, as_float)), pa.int32())
    parent = _col(raw, "parentSpanID", pa.string())
    table = _table({
        "trace_id": _col(raw, "traceID", pa.string()), "span_id": _col(raw, "spanID", pa.string()),
        "parent_span_id": _pc.if_else(_pc.equal(parent, ""), None, parent), "service": _strings(service),
        "component": _strings(_unless_equal(component, service)),
        "operation": scrub.text_column(
            _pc.if_else(pa.array(has_method), method, _col(raw, "operationName", pa.string()))),
        "kind": _strings(np.full(raw.num_rows, "unspecified", dtype=object)),
        "start_ns": start, "end_ns": end,
        "status": span_status(_array(_pc.cast(codes, pa.int64())), status),
        "status_code": codes,
    }, "telemetry.spans")  # fmt: skip
    valid = table.filter(_pc.greater_equal(table.column("end_ns"), table.column("start_ns")))
    order = _pc.sort_indices(valid, sort_keys=[(c, "ascending") for c in ("trace_id", "start_ns", "span_id")])
    ranked = valid.take(order).append_column("_rank", pa.array(np.arange(valid.num_rows, dtype=np.int64)))
    firsts = ranked.group_by(["trace_id", "span_id"]).aggregate([("_rank", "min")]).column("_rank_min")
    kept = ranked.filter(_pc.is_in(ranked.column("_rank"), value_set=firsts)).drop_columns(["_rank"])
    if kept.num_rows != table.num_rows:
        _log.info(
            "infralume.spans_dropped",
            negative=table.num_rows - valid.num_rows,
            duplicate=valid.num_rows - kept.num_rows,
        )
    return scrub.drop_rows(kept, ("service", "component"))
