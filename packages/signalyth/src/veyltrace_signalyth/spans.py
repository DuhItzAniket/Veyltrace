"""The span forest and the trace series (02 §3.3).

One pass builds, for every span of a case: its parent (by `parent_span_id`, or rebuilt by time
containment when a trace has no parent ids at all), whether it is client-like, whether it is an
entry span of its service, the visit it belongs to and its self-time. Client-like spans have no
self-time: their uncovered time is network and client overhead, reported on edges, never charged
to a service (02-signalyth AGENTS rule). Everything is NumPy over the spans sorted by
(`trace_id`, `start_ns`, `span_id`); the only loops are per trace without parent ids.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, cast

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

__all__ = ["Forest", "TraceRules", "bucket_quantiles", "build_forest", "trace_series"]

_pc: Any = pc  # pyarrow-stubs type compute kernels with Unknown parts (as core's io.py)
type Vec = np.ndarray[Any, Any]
NS: Final = 1_000_000_000
MS: Final = 1_000_000
QUANTILES: Final = (0.5, 0.99)
#: Above this, the vectorised interval union would overflow int64 (it offsets groups by the
#: longest span); the per-span fallback is exact but slower.
_INT_LIMIT: Final = 2**62
SPAN_COLUMNS: Final = (
    "trace_id", "span_id", "parent_span_id", "service", "operation", "kind", "start_ns", "end_ns", "status",
)  # fmt: skip


@dataclass(frozen=True)
class TraceRules:
    """`traces.*`, `buckets.traces_s`, `cp.*` (02 §4)."""

    bucket_ns: int
    reconstruct_parents: bool
    infer_client_spans: bool
    skew_tolerance_ns: int
    min_spans_per_quantile: int
    keep_fraction: float
    min_tree_fraction: float
    max_traces_per_window: int

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> TraceRules:
        t, cp = cast("Mapping[str, Any]", cfg["traces"]), cast("Mapping[str, Any]", cfg["cp"])
        mode = str(t["reconstruct_parents"])
        if mode not in ("if_missing", "never"):
            raise ValueError(f"traces.reconstruct_parents must be if_missing or never, got {mode!r}")
        return cls(
            bucket_ns=int(cast("Mapping[str, Any]", cfg["buckets"])["traces_s"]) * NS,
            reconstruct_parents=mode == "if_missing",
            infer_client_spans=bool(t["infer_client_spans"]),
            skew_tolerance_ns=round(float(t["skew_tolerance_ms"]) * MS),
            min_spans_per_quantile=int(t["min_spans_per_quantile"]),
            keep_fraction=float(t["keep_fraction"]),
            min_tree_fraction=float(cp["min_tree_fraction"]),
            max_traces_per_window=int(cp["max_traces_per_window"]),
        )


@dataclass(frozen=True)
class Forest:
    """Per-span arrays of one case, sorted by (trace_id, start_ns, span_id). `parent` is -1 for a
    root or an orphan; `visit` is the index of the visit's entry span, -1 for spans in no visit."""

    trace: Vec
    trace_ids: list[str]
    span_ids: Vec
    operation: Vec
    service: Vec
    services: list[str]
    start: Vec
    end: Vec
    error: Vec
    parent: Vec
    client: Vec
    entry: Vec
    self_ns: Vec
    visit: Vec

    @property
    def size(self) -> int:
        return int(self.start.size)


def sample_hash(case_id: str, trace_id: str) -> int:
    """sha256(case_id ‖ trace_id) as an integer (02 §3.3 step 6; 02 §3.4 cap): no RNG."""
    return int.from_bytes(hashlib.sha256(f"{case_id}{trace_id}".encode()).digest()[:8], "big")


def _keep(spans: pa.Table, case_id: str, fraction: float) -> pa.Table:
    if fraction >= 1.0:
        return spans
    ids = sorted(set(cast("list[str]", spans.column("trace_id").to_pylist())))
    kept = [t for t in ids if sample_hash(case_id, t) < fraction * 2**64]
    return spans.filter(_pc.is_in(spans.column("trace_id"), value_set=pa.array(kept, pa.string())))


def _containment(start: Vec, end: Vec, service: Vec) -> Vec:
    """Parents of one trace rebuilt by time containment: the shortest span of another service
    that contains the span (rcaeval_facts §Traces: a design rule)."""
    n = start.size
    parent = np.full(n, -1, dtype=np.int64)
    dur = end - start
    for b in range(n):
        inside = (service != service[b]) & (start <= start[b]) & (end >= end[b])
        if inside.any():
            idx = np.nonzero(inside)[0]
            parent[b] = int(idx[np.argmin(dur[idx])])  # ties: the first in key order
    return parent


def _covered(parent: Vec, start: Vec, end: Vec) -> Vec:
    """Per span, the length of the union of its children's intervals clipped to it."""
    n = start.size
    kids = np.nonzero(parent >= 0)[0]
    out = np.zeros(n, dtype=np.int64)
    if kids.size == 0:
        return out
    p = parent[kids]
    lo = np.clip(start[kids], start[p], end[p]) - start[p]
    hi = np.clip(end[kids], start[p], end[p]) - start[p]
    order = np.lexsort((lo, p))
    p, lo, hi = p[order], lo[order], hi[order]
    _, group = np.unique(p, return_inverse=True)
    width = int((end - start).max()) + 1
    if (int(group.max()) + 1) * width >= _INT_LIMIT:  # exact fallback, one parent at a time
        for i in range(p.size):
            j = i
            while j > 0 and p[j - 1] == p[i]:
                j -= 1
            reach = hi[j:i].max() if i > j else -1
            out[p[i]] += max(0, int(hi[i]) - max(int(lo[i]), int(reach)))
        return out
    off = group.astype(np.int64) * width
    reach = np.maximum.accumulate(off + hi)
    prev = np.concatenate((np.array([-1], dtype=np.int64), reach[:-1]))
    gain = np.maximum(0, off + hi - np.maximum(off + lo, prev))
    np.add.at(out, p, gain)
    return out


def build_forest(spans: pa.Table, rules: TraceRules, case_id: str) -> Forest:
    """The forest of `spans` (columns SPAN_COLUMNS) after the deterministic sampling hook."""
    spans = _keep(spans, case_id, rules.keep_fraction)
    order = _pc.sort_indices(spans, sort_keys=[(c, "ascending") for c in ("trace_id", "start_ns", "span_id")])
    s = spans.take(order)
    trace_codes = _pc.dictionary_encode(s.column("trace_id").combine_chunks())
    trace = np.asarray(trace_codes.indices.to_numpy(zero_copy_only=False), dtype=np.int64)
    svc_codes = _pc.dictionary_encode(s.column("service").combine_chunks())
    service = np.asarray(svc_codes.indices.to_numpy(zero_copy_only=False), dtype=np.int64)
    start = np.asarray(s.column("start_ns").to_numpy(), dtype=np.int64)
    end = np.maximum(np.asarray(s.column("end_ns").to_numpy(), dtype=np.int64), start)
    keys = _pc.binary_join_element_wise(s.column("trace_id"), s.column("span_id"), "\x00")
    parent_ids = _pc.cast(s.column("parent_span_id"), pa.string())  # an all-null column is null-typed
    pkeys = _pc.binary_join_element_wise(s.column("trace_id"), parent_ids, "\x00")
    found = _pc.index_in(pkeys, value_set=keys)
    parent = np.asarray(_pc.fill_null(found, -1).to_numpy(zero_copy_only=False), dtype=np.int64)
    has_id = np.asarray(parent_ids.is_valid().to_numpy(zero_copy_only=False), dtype=bool)
    n = start.size
    if rules.reconstruct_parents and n:
        bounds = np.flatnonzero(np.diff(trace)) + 1
        for a, b in zip(np.concatenate(([0], bounds)), np.concatenate((bounds, [n])), strict=True):
            if b - a > 1 and not has_id[a:b].any():
                local = _containment(start[a:b], end[a:b], service[a:b])
                parent[a:b] = np.where(local >= 0, local + a, -1)
    kind = np.asarray(s.column("kind").to_numpy(zero_copy_only=False), dtype=object)
    children = np.bincount(parent[parent >= 0], minlength=n)
    only_child = np.full(n, -1, dtype=np.int64)
    only_child[parent[parent >= 0]] = np.nonzero(parent >= 0)[0]
    tol = rules.skew_tolerance_ns
    c = np.where(children == 1, only_child, 0)
    inferred = (
        (kind == "unspecified") & (children == 1) & (service[c] != service)
        & (start[c] >= start - tol) & (end[c] <= end + tol)
    )  # fmt: skip
    client = (kind == "client") | (inferred if rules.infer_client_spans else False)
    p = np.where(parent >= 0, parent, 0)
    foreign = (parent < 0) | (service[p] != service)
    entry = foreign & ~client
    self_ns = np.where(client, 0, (end - start) - _covered(parent, start, end))
    up = np.where(entry, np.arange(n), np.where(~foreign, parent, -1))
    while True:  # pointer doubling to the visit's entry span (O(log depth) rounds)
        nxt = up.copy()
        live = up >= 0
        nxt[live] = up[up[live]]
        if np.array_equal(nxt, up):
            break
        up = nxt
    visit = np.where((up >= 0) & entry[np.maximum(up, 0)], up, -1)
    return Forest(
        trace=trace, trace_ids=cast("list[str]", trace_codes.dictionary.to_pylist()),
        span_ids=np.asarray(s.column("span_id").to_pylist(), dtype=object),
        operation=np.asarray(s.column("operation").to_pylist(), dtype=object), service=service,
        services=cast("list[str]", svc_codes.dictionary.to_pylist()), start=start, end=end,
        error=np.asarray(_pc.equal(s.column("status"), "error").to_numpy(zero_copy_only=False), dtype=bool),
        parent=parent, client=client, entry=entry, self_ns=self_ns, visit=visit,
    )  # fmt: skip


def bucket_quantiles(groups: Vec, values: Vec, min_n: int) -> dict[int, tuple[float, float]]:
    """{group: (p50, p99)} by exact linear quantiles (numpy `method="linear"`), groups with at
    least `min_n` values only."""
    out: dict[int, tuple[float, float]] = {}
    if values.size == 0:
        return out
    order = np.argsort(groups, kind="stable")
    g, v = groups[order], values[order]
    cuts = np.flatnonzero(np.diff(g)) + 1
    for a, b in zip(np.concatenate(([0], cuts)), np.concatenate((cuts, [g.size])), strict=True):
        if b - a >= min_n:
            q = np.quantile(v[a:b], QUANTILES, method="linear")
            out[int(g[a])] = (float(q[0]), float(q[1]))
    return out


def trace_series(f: Forest, rules: TraceRules, data_start: int, data_end: int) -> dict[str, list[Any]]:
    """Per-service trace series on the epoch-aligned bucket grid (02 §3.3 table): entry-span
    latency p50/p99, error rate and request rate, visit self-time p50/p99. `rps` is zero-filled
    from `data_start` to `data_end` for every service with an entry span; quantiles are written
    only for buckets with `min_spans_per_quantile` values; `error_rate` only where requests exist."""
    cols: dict[str, list[Any]] = {
        k: [] for k in ("service", "signal", "family", "klass", "unit", "t_ns", "value")
    }
    b = rules.bucket_ns
    e = np.nonzero(f.entry)[0]
    if e.size == 0:
        return cols
    bucket = (f.start[e] // b) * b
    n_buckets = int((data_end // b) - (data_start // b)) + 1
    first = (data_start // b) * b
    key = f.service[e] * n_buckets + (bucket - first) // b
    dur_ms = (f.end[e] - f.start[e]) / MS
    visit_self = np.zeros(f.size, dtype=np.float64)
    in_visit = f.visit >= 0
    np.add.at(visit_self, f.visit[in_visit], f.self_ns[in_visit])
    counts = np.bincount(key, minlength=len(f.services) * n_buckets)
    errors = np.bincount(key, weights=f.error[e].astype(np.float64), minlength=counts.size)
    lat = bucket_quantiles(key, dur_ms, rules.min_spans_per_quantile)
    self_q = bucket_quantiles(key, visit_self[e] / MS, rules.min_spans_per_quantile)

    def emit(svc: int, signal: str, family: str, klass: str, unit: str, k: int, value: float) -> None:
        row = (f.services[svc], signal, family, klass, unit, first + (k % n_buckets) * b, value)
        for name, item in zip(
            ("service", "signal", "family", "klass", "unit", "t_ns", "value"), row, strict=True
        ):
            cols[name].append(item)

    present = cast("set[int]", set(f.service[e].tolist()))
    for svc in sorted(present, key=lambda i: f.services[i]):
        for k in range(svc * n_buckets, (svc + 1) * n_buckets):
            emit(svc, "rps", "traffic", "context", "1/s", k, counts[k] / (b / NS))
            if counts[k]:
                emit(svc, "error_rate", "errors", "external", "ratio", k, errors[k] / counts[k])
            if k in lat:
                emit(svc, "latency_p50", "latency", "external", "ms", k, lat[k][0])
                emit(svc, "latency_p99", "latency", "external", "ms", k, lat[k][1])
            if k in self_q:
                emit(svc, "self_time_p50", "self_time", "internal", "ms", k, self_q[k][0])
                emit(svc, "self_time_p99", "self_time", "internal", "ms", k, self_q[k][1])
    return cols
