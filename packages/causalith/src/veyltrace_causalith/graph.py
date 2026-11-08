"""Nodes, node kinds and trace edges of the dependency graph (05-causalith §3.1, §3.2, §3.4).

Why observed calls and not causal discovery: discovery F1 is 0.1–0.54 on 10–50-node graphs and most
graph-learning RCA scores like random (novel_building_blocks §Q4), so the graph is what the system
shows: calls in traces, hints in events, mentions in logs, each edge with its provenance.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

import pyarrow as pa

__all__ = ["Edge", "EdgeRules", "KindRules", "external_hosts", "node_kinds", "span_attrs", "trace_edges"]

NAME = re.compile(r"^[a-z0-9][a-z0-9.-]*$")  # 03 §1 name pattern for nodes
CACHE_SYSTEMS = frozenset({"redis", "memcached"})  # 05 §3.2 order 2: db.system values that are caches


@dataclass(frozen=True)
class EdgeRules:
    """`edges.*` (05 §4): when an edge counts as anomalous in the incident window."""

    latency_ratio: float
    latency_min_ms: float
    error_delta: float
    silence_min_baseline_calls: int


@dataclass(frozen=True)
class KindRules:
    """`node_kinds.*` (05 §4): name patterns for db, cache and queue nodes."""

    db: Sequence[re.Pattern[str]]
    cache: Sequence[re.Pattern[str]]
    queue: Sequence[re.Pattern[str]]


@dataclass
class Edge:
    """One merged edge (03 §6.2); `calls_incident`, `anomalous` stay None without trace data."""

    src: str
    dst: str
    provenance: set[str] = field(default_factory=set[str])
    calls_incident: int | None = None
    weight: float = 1.0
    anomalous: bool | None = None


def _rows(table: pa.Table) -> list[dict[str, Any]]:
    return table.to_pylist()


def _ratio_up(inc: float | None, base: float | None, rules: EdgeRules) -> bool:
    if inc is None or base is None:
        return False
    return inc >= (1.0 + rules.latency_ratio) * base and inc - base >= rules.latency_min_ms


def trace_edges(edges: pa.Table, rules: EdgeRules) -> dict[tuple[str, str], Edge]:
    """One edge per (caller, callee) present in either window of `signal_cube.edges` (05 §3.4)."""
    by_pair: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in _rows(edges):
        by_pair.setdefault((str(row["caller"]), str(row["callee"])), {})[str(row["window"])] = row
    totals: dict[tuple[str, str], int] = {}
    for (src, _), windows in by_pair.items():
        for window, row in windows.items():
            totals[src, window] = totals.get((src, window), 0) + int(row["calls"])
    out: dict[tuple[str, str], Edge] = {}
    for (src, dst), windows in sorted(by_pair.items()):
        b, i = windows.get("baseline"), windows.get("incident")
        calls = int(i["calls"]) if i else 0
        if totals.get((src, "incident"), 0) > 0:
            weight = calls / totals[src, "incident"]
        elif b is not None and totals.get((src, "baseline"), 0) > 0:
            weight = int(b["calls"]) / totals[src, "baseline"]
        else:
            weight = 1.0
        if i is None:  # a missing row means calls = 0 in that window (03 §3.2)
            anomalous = b is not None and int(b["calls"]) >= rules.silence_min_baseline_calls
        elif b is None:
            anomalous = float(i["error_rate"]) >= rules.error_delta
        else:
            anomalous = (
                _ratio_up(i["p99_callee_ms"], b["p99_callee_ms"], rules)
                or _ratio_up(i["p99_gap_ms"], b["p99_gap_ms"], rules)
                or float(i["error_rate"]) - float(b["error_rate"]) >= rules.error_delta
            )
        out[src, dst] = Edge(src, dst, {"traces"}, calls, weight, bool(anomalous))
    return out


def _attrs(raw: object) -> Mapping[str, Any]:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        value: object = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return cast("Mapping[str, Any]", value) if isinstance(value, dict) else {}


def _host(value: object) -> str | None:
    """Lowercase host without port (05 §3.1), or None when it is not a valid node name."""
    if not isinstance(value, str) or not value:
        return None
    host = value.strip().lower().rsplit("@", 1)[-1]
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host if NAME.match(host) else None


def _known(host: str, services: frozenset[str]) -> bool:
    return host in services or host.split(".", 1)[0] in services


def external_hosts(
    spans: pa.Table, services: Iterable[str], min_calls: int
) -> dict[str, list[Mapping[str, Any]]]:
    """External hosts of client spans (`server.address`, else `peer.service`) that are no known
    service and have at least `min_calls` spans, with those spans' attributes (05 §3.1)."""
    known = frozenset(services)
    found: dict[str, list[Mapping[str, Any]]] = {}
    for row in _rows(spans.select(["kind", "attrs_json"])):
        if row["kind"] != "client":
            continue
        attrs = _attrs(row["attrs_json"])
        host = _host(attrs.get("server.address")) or _host(attrs.get("peer.service"))
        if host is not None and not _known(host, known):
            found.setdefault(host, []).append(attrs)
    return {h: a for h, a in sorted(found.items()) if len(a) >= min_calls}


def node_kinds(
    nodes: Sequence[str],
    entries: frozenset[str],
    externals: frozenset[str],
    span_attrs: Mapping[str, Sequence[Mapping[str, Any]]],
    rules: KindRules,
) -> dict[str, str]:
    """`graph.nodes.kind`, first match wins (05 §3.2): entry, cache, db, queue, external, service."""
    out: dict[str, str] = {}
    for node in nodes:
        attrs = span_attrs.get(node, ())
        systems = {str(a["db.system"]).lower() for a in attrs if a.get("db.system")}
        messaging = any(a.get("messaging.system") for a in attrs)
        if node in entries:
            kind = "entry"
        elif systems & CACHE_SYSTEMS or any(p.search(node) for p in rules.cache):
            kind = "cache"
        elif systems or any(p.search(node) for p in rules.db):
            kind = "db"
        elif messaging or any(p.search(node) for p in rules.queue):
            kind = "queue"
        elif node in externals:
            kind = "external"
        else:
            kind = "service"
        out[node] = kind
    return out


def span_attrs(
    spans: pa.Table, externals: Mapping[str, Sequence[Mapping[str, Any]]]
) -> dict[str, list[Mapping[str, Any]]]:
    """Attributes that describe each node (05 §3.2): a service's own non-client spans, and for an
    external host the client spans that call it. A client span describes its callee, so a service
    whose client spans carry `db.system` (it *calls* a database) does not become a db itself."""
    out: dict[str, list[Mapping[str, Any]]] = {host: list(attrs) for host, attrs in externals.items()}
    for row in _rows(spans.select(["service", "kind", "attrs_json"])):
        if row["kind"] == "client":
            continue
        attrs = _attrs(row["attrs_json"])
        if attrs:
            out.setdefault(str(row["service"]), []).append(attrs)
    return out
