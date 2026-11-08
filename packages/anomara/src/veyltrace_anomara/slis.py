"""Entry-service SLIs for detect_alert: span call pairs, entry spans and their buckets (03-anomara §3.8).

Why a module of its own: `detect_alert` reads SLIs from traces and, for systems without traces,
from metrics; both builders return the same `Sli` series for the one scan in `alert`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, cast

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from veyltrace_anomara.series import FloatArray, IntArray
from veyltrace_anomara.settings import SloConfig

__all__ = [
    "ERRORS",
    "LATENCY",
    "TO_MS",
    "Sli",
    "metric_slis",
    "quantile_of",
    "span_call_pairs",
    "span_parents",
    "trace_slis",
]

#: pyarrow-stubs leave pyarrow.compute's signatures partly unknown (as in veyltrace_core.io).
_pc: Any = pc

#: Tie order between SLIs that breach in the same bucket (03-anomara §3.8 step 4).
LATENCY, ERRORS = 0, 1


@dataclass(frozen=True, eq=False)
class Sli:
    """One entry-service SLI on the `slo.bucket_s` grid: bucket starts and values (sorted)."""

    service: str
    signal: str
    kind: int  # LATENCY or ERRORS
    family: str
    unit: str
    t: IntArray
    x: FloatArray


def _strings(table: pa.Table, name: str) -> list[str | None]:
    return cast("list[str | None]", table.column(name).to_pylist())


def span_parents(spans: pa.Table) -> list[str | None]:
    """The service of each span's parent (None: root, or the parent is not in the trace)."""
    traces, ids, services = (
        _strings(spans, "trace_id"),
        _strings(spans, "span_id"),
        _strings(spans, "service"),
    )
    owner = {(tr, sp): sv for tr, sp, sv in zip(traces, ids, services, strict=True)}
    return [
        None if parent is None else owner.get((tr, parent))
        for tr, parent in zip(traces, _strings(spans, "parent_span_id"), strict=True)
    ]


def span_call_pairs(spans: pa.Table) -> list[tuple[str, str]]:
    """Sorted unique (parent service, child service) pairs of spans in different services (§3.8 step 1)."""
    services = _strings(spans, "service")
    pairs = {
        (p, str(c)) for p, c in zip(span_parents(spans), services, strict=True) if p is not None and p != c
    }
    return sorted(pairs)


def trace_slis(spans: pa.Table, parents: list[str | None], service: str, slo: SloConfig) -> list[Sli]:
    """`latency_p99` and `error_rate` of the service's entry spans per bucket (§3.8 step 2).

    Entry span: parent null, missing, or in another service, and not client-like (kind `client`;
    02-signalyth §3.3). Buckets with fewer than `slo.min_spans` entry spans are skipped. `parents`
    is `span_parents(spans)`, computed once per case.
    """
    services = _strings(spans, "service")
    kinds = _strings(spans, "kind")
    status = _strings(spans, "status")
    start = np.asarray(spans.column("start_ns").to_numpy(), dtype=np.int64)
    end = np.asarray(spans.column("end_ns").to_numpy(), dtype=np.int64)
    entry = np.asarray(
        [
            s == service and k != "client" and p != service
            for s, k, p in zip(services, kinds, parents, strict=True)
        ],
        dtype=np.bool_,
    )
    errors = np.asarray([st == "error" for st in status], dtype=np.bool_)[entry]
    duration_ms = (end[entry] - start[entry]) / 1e6
    buckets = np.floor_divide(start[entry], slo.bucket_ns)
    order = np.argsort(buckets, kind="stable")
    buckets, duration_ms, errors = buckets[order], duration_ms[order], errors[order]
    t: list[int] = []
    p99: list[float] = []
    err: list[float] = []
    for b in np.unique(buckets):
        pick = buckets == b
        if int(np.count_nonzero(pick)) < slo.min_spans:
            continue
        t.append(int(b) * slo.bucket_ns)
        p99.append(float(np.quantile(duration_ms[pick], 0.99, method="linear")))
        err.append(float(np.count_nonzero(errors[pick])) / float(np.count_nonzero(pick)))
    ts = np.asarray(t, dtype=np.int64)
    return [
        Sli(service, "latency_p99", LATENCY, "latency", "ms", ts, np.asarray(p99)),
        Sli(service, "error_rate", ERRORS, "errors", "ratio", ts, np.asarray(err)),
    ]


#: Unit -> factor to milliseconds (02-signalyth §3.2 step 2: s × 1000, us ÷ 1000). Unit definitions,
#: not tuned values; a missing or unknown unit is taken as already in ms.
TO_MS: Final[Mapping[str, float]] = {
    "s": 1000.0,
    "seconds": 1000.0,
    "ms": 1.0,
    "milliseconds": 1.0,
    "us": 0.001,
    "microseconds": 0.001,
    "ns": 1e-6,
    "nanoseconds": 1e-6,
}
_QUANTILE = re.compile(r"(?:-|p|quantile=)(0?\.\d+|\d+)", re.IGNORECASE)


def quantile_of(name: str) -> float:
    """The quantile a metric name encodes (`-90`, `p99`, `quantile=0.99`; 02-signalyth rule 5), or -1."""
    found = [m.group(1) for m in _QUANTILE.finditer(name)]
    if not found:
        return -1.0
    raw = found[-1]
    return float(raw) if "." in raw else float(f"0.{raw}")


def _rate(t: IntArray, v: FloatArray) -> tuple[IntArray, FloatArray]:
    """Per-second rate between consecutive points with Prometheus reset semantics, written at t₂."""
    if t.size < 2:
        return t[:0], v[:0]
    dv = np.diff(v)
    return t[1:], np.where(dv >= 0, dv, v[1:]) / (np.diff(t) / 1e9)


def metric_slis(metrics: pa.Table, service: str, slo: SloConfig) -> list[Sli]:
    """Metric SLIs of one entry service when there are no traces (03-anomara §3.8 step 2).

    Per component: the latency metric with the highest quantile in its name (A→Z on ties), in ms,
    and the first error metric A→Z; counters (Signalyth's name patterns) become per-second rates.
    The last value per `slo.bucket_s` bucket is the SLI value.
    """
    rows = metrics.filter(_pc.equal(metrics.column("service"), service))
    names = cast("list[str]", rows.column("name").to_pylist())
    components = cast("list[str]", rows.column("component").to_pylist())
    units = cast("list[str | None]", rows.column("unit").to_pylist())
    t_all = np.asarray(rows.column("t_ns").to_numpy(), dtype=np.int64)
    v_all = np.asarray(rows.column("value").to_numpy(), dtype=np.float64)
    out: list[Sli] = []
    for component in sorted(set(components)):
        own = sorted({n for c, n in zip(components, names, strict=True) if c == component})
        latency = sorted(
            (n for n in own if slo.latency_pattern.search(n)), key=lambda n: (-quantile_of(n), n)
        )
        errors = [n for n in own if slo.error_pattern.search(n) and n not in latency[:1]]
        for name, kind in [*((n, LATENCY) for n in latency[:1]), *((n, ERRORS) for n in errors[:1])]:
            pick = np.asarray(
                [c == component and n == name for c, n in zip(components, names, strict=True)], dtype=np.bool_
            )
            order = np.argsort(t_all[pick], kind="stable")
            t, v = t_all[pick][order], v_all[pick][order]
            unit = next((u for u, keep in zip(units, pick.tolist(), strict=True) if keep and u), None)
            if any(p.search(name) for p in slo.counter_patterns):
                t, v = _rate(t, v)
            if kind == LATENCY:
                v = v * TO_MS.get((unit or "ms").lower(), 1.0)
            if t.size == 0:
                continue
            last = np.flatnonzero(np.concatenate((np.diff(t // slo.bucket_ns) != 0, [True])))
            # Errors keep their own unit, so a ratio gets the 0.01 floor and a rate or count the 0.1 one.
            family, sli_unit = ("latency", "ms") if kind == LATENCY else ("errors", unit or "count")
            out.append(
                Sli(
                    service, name, kind, family, sli_unit, (t // slo.bucket_ns)[last] * slo.bucket_ns, v[last]
                )
            )
    return out
