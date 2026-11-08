"""Trace edges of the dependency graph (05-causalith §3.4); nodes and kinds arrive with O-05b.

Why observed calls and not causal discovery: discovery F1 is 0.1–0.54 on 10–50-node graphs and most
graph-learning RCA scores like random (novel_building_blocks §Q4), so the graph is what the system
shows: calls in traces, hints in events, mentions in logs, each edge with its provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa

__all__ = ["Edge", "EdgeRules", "trace_edges"]


@dataclass(frozen=True)
class EdgeRules:
    """`edges.*` (05 §4): when an edge counts as anomalous in the incident window."""

    latency_ratio: float
    latency_min_ms: float
    error_delta: float
    silence_min_baseline_calls: int


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
