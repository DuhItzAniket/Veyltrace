"""Engine entry point of Causalith (registered as `veyltrace.engines:causalith`; 05-causalith §2).

Pipeline step 4 (parallel with Causync): the dependency graph from what the system shows. Nodes
(services, edge endpoints and external hosts, with kinds, the shared entry rule and provenance) and
trace edges; log and topology edges (O-05c) and paths (O-05d) follow, so `graph.paths` is empty.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from veyltrace_causalith.entry import entry_config, run_entry_services
from veyltrace_causalith.graph import external_hosts, node_kinds, span_attrs, trace_edges
from veyltrace_causalith.settings import causalith_config
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.context import EngineResult, RunContext

__all__ = ["ENGINE", "run"]

ENGINE = "causalith"


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
    edge_rows = [asdict(e) | {"provenance": sorted(e.provenance)} for e in edges.values()]
    outputs = (
        ("graph.nodes", ctx.write("graph.nodes", node_rows)),
        ("graph.edges", ctx.write("graph.edges", edge_rows)),
        ("graph.paths", ctx.write("graph.paths", io.empty_table("graph.paths"))),
    )
    metrics = {"nodes": len(nodes), "edges": len(edges)}
    return EngineResult(engine=ENGINE, status="ok", outputs=outputs, metrics=metrics)
