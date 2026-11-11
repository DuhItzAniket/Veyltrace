"""Engine entry point of Causatrix (registered as `veyltrace.engines:causatrix`).

Pipeline step 6 (07 §3.1): read `evidence` (engine atoms), `graph.nodes`, `graph.edges` and
`case_manifest`, rank every service of U with the enabled rankers, fuse them with gated RRF,
classify the top K and write `slate.json`. A pure function of those inputs and the config; the
signature `run(ctx: RunContext) -> EngineResult` is fixed (AGENTS §5).
"""

from __future__ import annotations

from typing import Final

from veyltrace_causatrix.config import ENGINE, config_from
from veyltrace_causatrix.rank import rank
from veyltrace_causatrix.slate import build_slate
from veyltrace_causatrix.views import engine_atoms, evidence_view, graph_view
from veyltrace_contracts import models
from veyltrace_core.context import EngineResult, RunContext

#: Columns this step reads (07 §2.1; atom_id breaks topI/topE ties, origin selects engine atoms).
EVIDENCE_COLUMNS: Final = (
    "atom_id",
    "candidate",
    "component",
    "kind",
    "args_json",
    "value",
    "refs",
    "origin",
)
NODE_COLUMNS: Final = ("node", "kind")
EDGE_COLUMNS: Final = ("src", "dst", "weight", "provenance")
#: EngineResult note when every ranker abstained, so `diagnose` and bench can see why the slate is empty.
NO_VOTE_NOTE: Final = "no ranker voted: empty slate (07 §3.1, §6)"


def run(ctx: RunContext) -> EngineResult:
    """Pipeline step 6: the slate (07 §6: absent evidence or graph.nodes fails the step)."""
    for required in ("evidence", "graph.nodes"):
        if not ctx.exists(required):
            return EngineResult(engine=ENGINE, status="failed", notes=(f"{required} is absent (07 §6)",))
    cfg = config_from(ctx.config, ctx.config.core)
    manifest = ctx.read_model("case_manifest", models.CaseManifest)
    rows = ctx.read_table("evidence", columns=EVIDENCE_COLUMNS).to_pylist()
    nodes = [
        (str(r["node"]), str(r["kind"]))
        for r in ctx.read_table("graph.nodes", columns=NODE_COLUMNS).to_pylist()
    ]
    edges = (
        ctx.read_table("graph.edges", columns=EDGE_COLUMNS).to_pylist() if ctx.exists("graph.edges") else []
    )
    graph = graph_view(manifest.services, nodes, edges, include_external=cfg.include_external)
    atoms = engine_atoms(rows)
    ev = evidence_view(atoms, graph.universe)
    result = rank(ev, graph, manifest.sources, cfg)
    slate = build_slate(manifest.case_id, result, ev, graph, cfg)
    digest = ctx.write("slate", slate)
    return EngineResult(
        engine=ENGINE,
        status="ok",
        outputs=(("slate", digest),),
        metrics={
            "universe": len(graph.universe),
            "engine_atoms": len(atoms),
            "graph_edges_in_u": len(graph.edges),
            "rankers_active": len(result.active),
            "candidates": len(slate["candidates"]),
        },
        notes=() if result.active else (NO_VOTE_NOTE,),
    )
