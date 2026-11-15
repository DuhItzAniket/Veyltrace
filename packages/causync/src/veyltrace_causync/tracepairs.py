"""Trace clock offsets per service from client/server span pairs (04-causync §3.2).

A client-like span `p` and its only child `c` in another service give the NTP on-wire estimate
`θ = ((c.start − p.start) + (c.end − p.end)) / 2`: callee clock minus caller clock under symmetric
network delay (RFC 5905). Per caller→callee pair the median θ is propagated breadth-first from the
root service. Client overhead biases θ by small amounts, so a pair's θ is applied only where the
data shows skew (children sticking out of their parents); otherwise it counts as 0.

A span is client-like when its kind is `client`, or when its kind is `unspecified`, its parent is
in its own service and its only child is in another one (the rule of 02-signalyth §3.3 without
the containment test: a skewed child lies outside its parent, which is what is measured here).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from veyltrace_causync.settings import AlignConfig

__all__ = ["PAIR_COLUMNS", "Offset", "PairStats", "pair_stats", "trace_offsets"]

_pc: Any = pc  # pyarrow-stubs type compute kernels with Unknown parts (as core's io.py)
PAIR_COLUMNS: Final = ("trace_id", "span_id", "parent_span_id", "service", "kind", "start_ns", "end_ns")


@dataclass(frozen=True)
class Offset:
    """One `alignment.offsets` entry (03 §5.1): `offset_ns` is added to the source's times."""

    source: str
    service: str | None
    offset_ns: int
    method: str
    confidence: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "service": self.service, "offset_ns": self.offset_ns,
            "method": self.method, "confidence": self.confidence,
        }  # fmt: skip


@dataclass(frozen=True)
class PairStats:
    """Client/server pairs of one caller→callee service pair: median θ (ns), the number of pairs,
    the share whose child sticks out of its parent, and the share whose θ has the median's sign."""

    theta_ns: float
    n: int
    violation_share: float
    sign_share: float


def pair_stats(spans: pa.Table) -> tuple[dict[tuple[str, str], PairStats], dict[str, int]]:
    """({(caller, callee): PairStats}, {service: spans}) from `telemetry.spans` (PAIR_COLUMNS)."""
    n = spans.num_rows
    services = [str(s) for s in spans.column("service").to_pylist()]
    counts: dict[str, int] = {}
    for name in services:
        counts[name] = counts.get(name, 0) + 1
    if n == 0:
        return {}, counts
    keys = _pc.binary_join_element_wise(spans.column("trace_id"), spans.column("span_id"), "\x00")
    parent_ids = _pc.cast(spans.column("parent_span_id"), pa.string())  # an all-null column is null-typed
    pkeys = _pc.binary_join_element_wise(spans.column("trace_id"), parent_ids, "\x00")
    found = _pc.fill_null(_pc.index_in(pkeys, value_set=keys), -1)
    parent = np.asarray(found.to_numpy(zero_copy_only=False), dtype=np.int64)
    start = np.asarray(spans.column("start_ns").to_numpy(), dtype=np.int64)
    end = np.asarray(spans.column("end_ns").to_numpy(), dtype=np.int64)
    kind = np.asarray(spans.column("kind").to_pylist(), dtype=object)
    names = sorted(counts)
    code = {name: i for i, name in enumerate(names)}
    svc = np.asarray([code[s] for s in services], dtype=np.int64)
    has_parent = parent >= 0
    children = np.bincount(parent[has_parent], minlength=n)
    child = np.where(has_parent)[0]
    p = parent[child]
    same_service_parent = has_parent & (svc[np.maximum(parent, 0)] == svc)
    client = (kind == "client") | ((kind == "unspecified") & same_service_parent)
    keep = client[p] & (children[p] == 1) & (svc[p] != svc[child])
    c, p = child[keep], p[keep]
    theta = ((start[c] - start[p]) + (end[c] - end[p])) / 2.0
    outside = (start[c] < start[p]) | (end[c] > end[p])
    stats: dict[tuple[str, str], PairStats] = {}
    edge = svc[p] * len(names) + svc[c]
    for e in np.unique(edge).tolist():
        members = edge == e
        th = theta[members]
        median = float(np.median(th))
        same_sign = (np.sign(th) == float(np.sign(median))).astype(np.float64)
        agree = float(same_sign.mean())
        stats[(names[e // len(names)], names[e % len(names)])] = PairStats(
            median, int(th.size), float(np.mean(outside[members])), agree
        )
    return stats, counts


def trace_offsets(spans: pa.Table, entry_services: list[str], cfg: AlignConfig) -> list[Offset]:
    """One `traces` offset per service with a span, sorted by service.

    Breadth-first from the root (the first entry service A→Z that has spans, else the service
    with the most spans) over pairs with at least `min_pairs` samples, neighbours by (pairs desc,
    name asc). The publish gate is per edge: along A→B, `offset(B) = offset(A) − θ_AB` when the
    A→B pairs show skew (|θ| at least `trace_min_offset_ms` and children sticking out of their
    parents often enough), else `offset(B) = offset(A)`; against the call direction the sign
    flips. So a callee on its caller's skewed clock inherits the caller's correction.
    Unreachable services get method `none`, as does every service when the case has no
    client/server pair at all (04 §6)."""
    stats, counts = pair_stats(spans)
    if not counts:
        return []
    entries = sorted(s for s in entry_services if s in counts)
    root = entries[0] if entries else min(counts, key=lambda s: (-counts[s], s))
    if not stats:
        return [Offset("traces", service, 0, "none", 0.0) for service in sorted(counts)]
    links: dict[str, list[tuple[int, str, float, PairStats]]] = {}
    for (caller, callee), st in stats.items():
        if st.n >= cfg.min_pairs:
            shown = (
                abs(st.theta_ns) >= cfg.trace_min_offset_ns and st.violation_share >= cfg.min_violation_share
            )
            theta = st.theta_ns if shown else 0.0
            links.setdefault(caller, []).append((-st.n, callee, -theta, st))
            links.setdefault(callee, []).append((-st.n, caller, theta, st))
    found: dict[str, tuple[float, PairStats | None]] = {root: (0.0, None)}
    queue = [root]
    for node in queue:  # the list grows while it is walked: breadth-first
        for _, other, delta, st in sorted(links.get(node, []), key=lambda link: link[:2]):
            if other not in found:
                found[other] = (found[node][0] + delta, st)
                queue.append(other)
    out: list[Offset] = []
    for service in sorted(counts):
        if service not in found:
            out.append(Offset("traces", service, 0, "none", 0.0))
            continue
        value, st = found[service]
        # the root defines the trace clock; elsewhere the edge that reached the service speaks
        confidence = 1.0 if st is None else st.n / (st.n + cfg.min_pairs) * st.sign_share
        out.append(Offset("traces", service, int(np.rint(value)), "trace_pairs", confidence))
    return out
