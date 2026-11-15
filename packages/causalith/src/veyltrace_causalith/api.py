"""Engine entry point of Causalith (registered as `veyltrace.engines:causalith`; 05-causalith §2).

Pipeline step 4 (parallel with Causync): the dependency graph from what the system shows. Nodes
(services, edge endpoints and external hosts, with kinds, the shared entry rule and provenance) and
trace, log-mention and topology edges with their provenance; and the k best propagation paths
from every node to the entry services (05 §3.6).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from veyltrace_causalith.entry import entry_config, run_entry_services
from veyltrace_causalith.graph import Edge, external_hosts, node_kinds, span_attrs, trace_edges
from veyltrace_causalith.mentions import Matcher, log_edges, topology_edges
from veyltrace_causalith.paths import ranked_paths, reversed_graph
from veyltrace_causalith.settings import causalith_config
from veyltrace_contracts import models
from veyltrace_core import duck
from veyltrace_core.context import EngineResult, RunContext

__all__ = ["ENGINE", "run"]

ENGINE = "causalith"
#: Distinct (service, body) line counts over baseline and incident (05 §3.4: counting over distinct bodies).
_LOG_COUNTS = """
SELECT service, body, count(*) AS n FROM logs
WHERE (t_ns >= ? AND t_ns < ?) OR (t_ns >= ? AND t_ns < ?)
GROUP BY service, body ORDER BY service, body
"""


def _log_counts(ctx: RunContext, alert: models.Alert) -> list[tuple[str, str, int]]:
    logs = ctx.read_table("telemetry.logs", columns=["service", "t_ns", "body"])
    if logs.num_rows == 0:
        return []
    with duck.connect(ctx.config, ctx.run_dir) as con:
        con.register("logs", logs)
        found = con.execute(_LOG_COUNTS, [*alert.windows.baseline, *alert.windows.incident]).fetchall()
    return [(str(s), str(b), int(n)) for s, b, n in found]


def _anomalous_nodes(ctx: RunContext) -> frozenset[str]:
    """Services with an above-threshold external robust_z, or external/context silence (05 §3.6 step 1)."""
    rows = ctx.read_table(
        "anomalies", columns=["service", "klass", "detector", "above_threshold"]
    ).to_pylist()
    return frozenset(
        str(r["service"])
        for r in rows
        if r["above_threshold"]
        and (
            (r["detector"] == "robust_z" and r["klass"] == "external")
            or (r["detector"] == "silence" and r["klass"] in ("external", "context"))
        )
    )


def _merge(edges: dict[tuple[str, str], Edge], pairs: list[tuple[str, str]], tag: str) -> None:
    """Union by (src, dst): provenance grows; calls, weight and anomaly stay from traces (05 §3.4)."""
    for src, dst in pairs:
        if src != dst:
            edges.setdefault((src, dst), Edge(src, dst)).provenance.add(tag)


def run(ctx: RunContext) -> EngineResult:
    """Write `graph.nodes`, `graph.edges` and `graph.paths` for one run (05-causalith §2)."""
    manifest = ctx.read_model("case_manifest", models.CaseManifest)
    alert = ctx.read_model("alert", models.Alert)
    cfg = causalith_config(ctx.config)
    signal_edges = ctx.read_table("signal_cube.edges")
    spans = ctx.read_table("telemetry.spans", columns=["service", "kind", "attrs_json"])
    series = ctx.read_table("signal_cube.series", columns=["service", "source"])
    edges = trace_edges(signal_edges, cfg.edges)
    known = set(manifest.services) | {n for pair in edges for n in pair}
    externals = (
        external_hosts(spans, known, cfg.graph.external_min_calls) if cfg.graph.include_external else {}
    )
    nodes = sorted(known | set(externals))
    # Logs and topology hints only connect known nodes; they never create one (05 §3.1).
    matcher, node_set = Matcher.build(nodes), frozenset(nodes)
    _merge(edges, log_edges(_log_counts(ctx, alert), node_set, matcher, cfg.logs.min_mentions), "logs")
    events = ctx.read_table("telemetry.events", columns=["entity", "kind", "detail_json"]).to_pylist()
    hints = [(str(e["entity"]), str(e["kind"]), str(e["detail_json"])) for e in events]
    _merge(edges, topology_edges(hints, node_set, matcher), "topology")
    edges = dict(sorted(edges.items()))
    entries = run_entry_services(
        alert, signal_edges, manifest.services, manifest.system, entry_config(ctx.config)
    )
    kinds = node_kinds(
        nodes, frozenset(entries), frozenset(externals), span_attrs(spans, externals), cfg.kinds
    )
    # Provenance (05 §3.1): its edges' provenance; traces for span services and external hosts;
    # metrics for nodes with a source = metrics series.
    provenance: dict[str, set[str]] = {n: set() for n in nodes}
    for (src, dst), edge in edges.items():
        provenance[src] |= edge.provenance
        provenance[dst] |= edge.provenance
    sources = zip(series.column("service").to_pylist(), series.column("source").to_pylist(), strict=True)
    tagged = [(str(s), "traces") for s in spans.column("service").to_pylist()] + [
        (h, "traces") for h in externals
    ]
    for node, tag in tagged + [(str(s), "metrics") for s, src in sources if src == "metrics"]:
        if node in provenance:
            provenance[node].add(tag)
    node_rows: list[dict[str, Any]] = [
        {"node": n, "kind": kinds[n], "is_entry": n in entries, "provenance": sorted(provenance[n])}
        for n in nodes
    ]
    anomalous = _anomalous_nodes(ctx)
    arcs = [(e.src, e.dst, e.anomalous) for e in edges.values()]
    adj = reversed_graph(arcs, anomalous, entries, cfg.paths.non_anomalous_penalty)
    path_rows: list[dict[str, Any]] = [
        {"candidate": n, "path_rank": rank, "nodes": list(path), "anomalous_fraction": fraction}
        for n in nodes
        for rank, (path, fraction) in enumerate(
            ranked_paths(adj, n, frozenset(entries), anomalous, cfg.paths.k, cfg.paths.max_len), start=1
        )
    ]
    edge_rows = [asdict(e) | {"provenance": sorted(e.provenance)} for e in edges.values()]
    outputs = (
        ("graph.nodes", ctx.write("graph.nodes", node_rows)),
        ("graph.edges", ctx.write("graph.edges", edge_rows)),
        ("graph.paths", ctx.write("graph.paths", path_rows)),
    )
    metrics = {"nodes": len(nodes), "edges": len(edges), "paths": len(path_rows)}
    return EngineResult(engine=ENGINE, status="ok", outputs=outputs, metrics=metrics)
