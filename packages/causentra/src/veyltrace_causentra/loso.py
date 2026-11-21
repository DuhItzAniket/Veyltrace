"""Leave-one-source-out re-ranking for trial T9 (09 §3.4).

Why: a candidate that leaves the top K as soon as one telemetry source is dropped rests on a
single channel, which is the in-run version of the telemetry-ablation protocol (09 §3.4 notes,
04 §5). For every present source s, Causatrix's pure `rank()` runs again on the engine atoms whose
`atom_sources` exclude s and on the call edges whose provenance is not only s, with s switched off
in the sources. That is one `rank()` call per present source (at most 4), computed once per case.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from veyltrace_causatrix.config import CausatrixConfig
from veyltrace_causatrix.rank import rank
from veyltrace_causatrix.views import Atom, EvidenceView, GraphView, evidence_view, graph_view
from veyltrace_contracts.models import Sources
from veyltrace_core.canonical import canonical_json_str
from veyltrace_faultloom.sources import atom_sources

#: The telemetry sources T9 may drop, sorted (03 §2.1 case_manifest.sources).
SOURCES: Final = ("events", "logs", "metrics", "traces")
#: T9 applies when at least this many sources are present (09 §3.4 "≥ 2 of {metrics, logs, traces,
#: events}"): with one source there is nothing to leave out.
MIN_SOURCES: Final = 2
#: Written in the claim pass for T8, after the slate (06 §3.6): not part of what rank() saw at step 6.
INTERVENTION: Final = "intervention"

#: One re-ranking: (dropped source, U in rank() order without it).
Ablation = tuple[str, tuple[str, ...]]


def present(sources: Sources) -> tuple[str, ...]:
    """The present sources, sorted."""
    return tuple(s for s in SOURCES if getattr(sources, s))


def sources_of(atom: Atom) -> frozenset[str]:
    """FaultLoom's `atom_sources` of a parsed atom (06 §3.3)."""
    row = {"refs": list(atom.refs), "kind": atom.kind, "args_json": canonical_json_str(dict(atom.args))}
    return atom_sources(row)


def without(source: str, atoms: Iterable[Atom], graph: GraphView) -> tuple[EvidenceView, GraphView]:
    """The evidence and graph views with `source` left out (09 §3.4 T9), over the same U."""
    kept = [a for a in atoms if a.kind != INTERVENTION and source not in sources_of(a)]
    edges = [
        {"src": e.src, "dst": e.dst, "weight": e.weight, "provenance": list(e.provenance)}
        for e in graph.edges
        if not set(e.provenance) <= {source}
    ]
    # U is already resolved: rebuild it from itself so external nodes are neither added nor dropped.
    nodes = sorted(graph.kinds.items())
    view = graph_view(graph.universe, nodes, edges, include_external=True)
    return evidence_view(kept, view.universe), view


def ablations(
    ev: EvidenceView, graph: GraphView, sources: Sources, cfg: CausatrixConfig
) -> tuple[Ablation, ...]:
    """(source, rank() order of U without it) per present source; empty with fewer than 2 sources."""
    names = present(sources)
    if len(names) < MIN_SOURCES:
        return ()
    out: list[Ablation] = []
    for source in names:
        ev_s, graph_s = without(source, ev.atoms, graph)
        off = sources.model_copy(update={source: False})
        out.append((source, rank(ev_s, graph_s, off, cfg).order))
    return tuple(out)
