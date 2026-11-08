"""Entry-service SLIs for detect_alert: span call pairs, entry spans and their buckets (03-anomara §3.8).

Why a module of its own: `detect_alert` reads SLIs from traces and, for systems without traces,
from metrics; both builders return the same `Sli` series for the one scan in `alert`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
import pyarrow as pa

from veyltrace_anomara.series import FloatArray, IntArray
from veyltrace_anomara.settings import SloConfig

__all__ = ["ERRORS", "LATENCY", "Sli", "span_call_pairs", "span_parents", "trace_slis"]

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
