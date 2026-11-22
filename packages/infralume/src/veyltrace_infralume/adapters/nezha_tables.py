"""Nezha raw files → the raw shapes `rcaeval_tables` converts (01 §3.3 `nezha`).

Why reshape instead of a second converter: names, scrubbing, severity, span de-duplication and the
row-drop accounting are the same rules for every dataset, and they live in `rcaeval_tables`. These
functions only rename and re-unit Nezha's columns, so both adapters share one implementation.

- Pod metrics: one row per minute. `Time` is parsed (whole seconds, UTC); the `TimeStamp` column is
  not used, because some pod files carry it 2·10^8 s off. Memory is converted from Mi to bytes (the
  unit `mem` has everywhere else); node-level columns are not service metrics and are left out.
- Logs: the body is the `log` field of the container's JSON line, or its inner `message` when that
  field is itself JSON (Online Boutique); severity comes from the inner `severity` or the level
  word at the start of a plain line (Train Ticket).
- Spans: nanosecond start and end are kept as microseconds, the unit RCAEval's spans have. Nezha
  records no status code, so every span is `unset`.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final, cast

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from veyltrace_infralume.names import strip_pod_suffix

__all__ = ["METRICS", "MIB", "raw_logs", "raw_metrics", "raw_spans"]

_pc: Any = pc  # pyarrow-stubs type compute kernels with Unknown parts (as rcaeval_tables)

MIB: Final = 1024 * 1024  # MemoryUsage(Mi) → bytes
_US: Final = 1000  # ns per microsecond

#: Nezha pod-metric column → canonical metric name. Server-side latency is the service's own
#: (`latency-NN`, RCAEval's spelling); client-side latency is that of its outgoing calls and gets a
#: name outside the latency family, so the two never share a signal. Columns not listed here
#: (`Node*`, `PodName`, `TimeStamp`) are not read.
METRICS: Final = {
    "CpuUsage(m)": "cpu",
    "CpuUsageRate(%)": "cpu_usage_rate",
    "MemoryUsage(Mi)": "mem",
    "MemoryUsageRate(%)": "memory_usage_rate",
    "SyscallRead": "syscall_read",
    "SyscallWrite": "syscall_write",
    "NetworkReceiveBytes": "network_receive_bytes",
    "NetworkTransmitBytes": "network_transmit_bytes",
    "PodServerLatencyP90(s)": "latency-90",
    "PodServerLatencyP95(s)": "latency-95",
    "PodServerLatencyP99(s)": "latency-99",
    "PodClientLatencyP90(s)": "client_p90",
    "PodClientLatencyP95(s)": "client_p95",
    "PodClientLatencyP99(s)": "client_p99",
    "PodWorkload(Ops)": "workload",
    "PodSuccessRate(%)": "success_rate",
}
_TIME_CHARS: Final = 19  # `YYYY-MM-DD HH:MM:SS` of `2022-08-22 03:51:19.607158889 +0000 UTC m=+0.11`
#: The level word of a plain log line, searched in its first characters only (a priori: the level
#: follows the clock time in Train Ticket's lines).
_LEVEL: Final = re.compile(r"\b(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\b")
_LEVEL_CHARS: Final = 64
ROOT: Final = "root"  # Nezha's ParentID of a trace's first span


def _strings(table: pa.Table, name: str) -> list[str | None]:
    return cast("list[str | None]", _pc.cast(table.column(name), pa.string()).to_pylist())


def raw_metrics(pod: pa.Table, service: str, window_ns: tuple[int, int]) -> pa.Table:
    """One pod's metric file as RCAEval's wide table: `time` (s) + `{service}_{metric}`, rows inside
    the half-open window only. An unparsable `Time` drops the row (null time)."""
    if "Time" not in pod.column_names or pod.num_rows == 0:
        return pa.Table.from_arrays([], names=[])
    text = _pc.utf8_slice_codeunits(_pc.cast(pod.column("Time"), pa.string()), 0, _TIME_CHARS)
    stamp = _pc.strptime(text, format="%Y-%m-%d %H:%M:%S", unit="s", error_is_null=True)
    seconds = np.asarray(_pc.cast(stamp, pa.int64()).fill_null(-1).to_numpy(zero_copy_only=False), np.int64)
    keep = (
        (seconds >= 0) & (seconds * 1_000_000_000 >= window_ns[0]) & (seconds * 1_000_000_000 < window_ns[1])
    )
    columns: dict[str, Any] = {"time": pa.array(seconds[keep].astype(np.float64))}
    for source, name in METRICS.items():
        if source not in pod.column_names:
            continue
        values = np.asarray(
            _pc.cast(pod.column(source), pa.float64()).fill_null(np.nan).to_numpy(zero_copy_only=False),
            np.float64,
        )[keep]
        columns[f"{service}_{name}"] = pa.array(values * MIB if name == "mem" else values)
    return pa.Table.from_arrays(list(columns.values()), names=list(columns))


def _message(line: str | None) -> tuple[str, str | None]:
    """(body, level) of one `Log` cell: the container line's `log` field, unwrapped once more when
    it is a JSON object with a `message`."""
    text = line or ""
    try:
        outer: object = json.loads(text)
    except ValueError:
        outer = None
    if isinstance(outer, dict) and isinstance(inner := cast("dict[str, object]", outer).get("log"), str):
        text = inner
    text = text.rstrip("\n")
    if text.startswith("{"):
        try:
            obj: object = json.loads(text)
        except ValueError:
            obj = None
        if isinstance(obj, dict) and isinstance(msg := cast("dict[str, object]", obj).get("message"), str):
            level = cast("dict[str, object]", obj).get("severity")
            return msg, level if isinstance(level, str) else None
    found = _LEVEL.search(text[:_LEVEL_CHARS])
    return text, found.group(1) if found else None


def raw_logs(logs: pa.Table) -> pa.Table:
    """Minute log files as RCAEval's log table: `timestamp` (ns), `container_name` (the pod name
    without its generated suffix), `pod_name`, `message`, `level`, and the ids as extra columns."""
    if "TimeUnixNano" not in logs.column_names or logs.num_rows == 0:
        return pa.Table.from_arrays([], names=[])
    pods = _strings(logs, "PodName")
    parsed = [_message(v) for v in _strings(logs, "Log")]
    ids = {
        out: pa.array([v or None for v in _strings(logs, src)], pa.string())
        for src, out in (("TraceID", "trace_id"), ("SpanID", "span_id"))
        if src in logs.column_names
    }
    columns: dict[str, Any] = {
        "timestamp": _pc.cast(logs.column("TimeUnixNano"), pa.int64()),
        "container_name": pa.array(
            [strip_pod_suffix(p.strip().lower()) if p else None for p in pods], pa.string()
        ),
        "pod_name": pa.array(pods, pa.string()),
        "message": pa.array([m for m, _ in parsed], pa.string()),
        "level": pa.array([lv for _, lv in parsed], pa.string()),
        **ids,
    }
    return pa.Table.from_arrays(list(columns.values()), names=list(columns))


def raw_spans(spans: pa.Table) -> pa.Table:
    """Minute trace files as RCAEval's span table: microsecond `startTime` and `duration`, the pod
    name without its suffix as `serviceName`, `root` parents emptied, no status code."""
    if "TraceID" not in spans.column_names or spans.num_rows == 0:
        return pa.Table.from_arrays([], names=[])
    start = np.asarray(_pc.cast(spans.column("StartTimeUnixNano"), pa.int64()).to_numpy(zero_copy_only=False))
    end = np.asarray(_pc.cast(spans.column("EndTimeUnixNano"), pa.int64()).to_numpy(zero_copy_only=False))
    pods = _strings(spans, "PodName")
    columns: dict[str, Any] = {
        "traceID": _pc.cast(spans.column("TraceID"), pa.string()),
        "spanID": _pc.cast(spans.column("SpanID"), pa.string()),
        "parentSpanID": pa.array(
            [None if v in (None, ROOT) else v for v in _strings(spans, "ParentID")], pa.string()
        ),
        "serviceName": pa.array(
            [strip_pod_suffix(p.strip().lower()) if p else None for p in pods], pa.string()
        ),
        "operationName": _pc.cast(spans.column("OperationName"), pa.string()),
        "startTime": pa.array(start // _US),
        "duration": pa.array((end // _US - start // _US).astype(np.float64)),
    }
    return pa.Table.from_arrays(list(columns.values()), names=list(columns))
