"""Causatrix's view of its inputs: the universe U, the call graph G and the 07 §2.1 quantities.

Why plain views: `rank()` and `classify()` are pure functions of them, and Causentra rebuilds them
on filtered atoms and edges for trial T9 (09 §3.4), so they are built from rows, never from a run
directory. Only engine atoms count; `claim_check` atoms do not exist at step 6 and are ignored if
present (07 §2.1). Everything is keyed and iterated in sorted order.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, cast

#: Atom kinds and arguments read here (03 §7); the public names are the classes and builders.
INTERNAL: Final = "internal_anomaly"
EXTERNAL: Final = "external_anomaly"
ONSET: Final = "onset_precedence"
CHANGE: Final = "change_proximity"
SPECTRUM: Final = "spectrum"
SILENCE: Final = "silence"
ROBUST_Z: Final = "robust_z"
NSIGMA: Final = "nsigma"
ORIGIN_ENGINE: Final = "engine"
#: graph.nodes.kind that joins U only with core.universe.include_external (06 §2.1).
EXTERNAL_KIND: Final = "external"
Row = Mapping[str, Any]


def universe(
    services: Iterable[str], nodes: Iterable[tuple[str, str]], *, include_external: bool
) -> tuple[str, ...]:
    """U = case_manifest.services plus graph.nodes of kind != external (06 §2.1), sorted A→Z."""
    members = set(services)
    members.update(node for node, kind in nodes if include_external or kind != EXTERNAL_KIND)
    return tuple(sorted(members))


# --- evidence -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Atom:
    """One engine evidence atom (03 §7), with `args_json` parsed into `args`."""

    atom_id: str
    candidate: str
    component: str | None
    kind: str
    args: Mapping[str, Any]
    value: float
    refs: tuple[str, ...] = ()


def _atom(row: Row) -> Atom:
    args: object = json.loads(str(row["args_json"]))
    component = row["component"]
    return Atom(
        atom_id=str(row["atom_id"]),
        candidate=str(row["candidate"]),
        component=None if component is None else str(component),
        kind=str(row["kind"]),
        args=MappingProxyType(cast(dict[str, Any], args) if isinstance(args, dict) else {}),
        value=float(row["value"]),
        refs=tuple(str(r) for r in cast(Sequence[str] | None, row.get("refs")) or ()),
    )


def engine_atoms(rows: Iterable[Row]) -> tuple[Atom, ...]:
    """Engine atoms (`origin = engine`) of evidence rows, sorted by (candidate, kind, atom_id)."""
    atoms = (_atom(row) for row in rows if row["origin"] == ORIGIN_ENGINE)
    return tuple(sorted(atoms, key=lambda a: (a.candidate, a.kind, a.atom_id)))


@dataclass(frozen=True)
class ServiceEvidence:
    """The 07 §2.1 quantities of one service: 0, +inf or None when no atom exists.

    internal = I, external = E (max robust_z values), nsigma = NS, silent = Sil, spectrum = SP,
    change = CH (max values), onset_ms = the self onset; top_internal / top_external = topI / topE.
    """

    internal: float = 0.0
    external: float = 0.0
    nsigma: float = 0.0
    silent: float = 0.0
    spectrum: float = 0.0
    change: float = 0.0
    onset_ms: float = math.inf
    top_internal: Atom | None = None
    top_external: Atom | None = None


def _top(atoms: Sequence[Atom]) -> Atom | None:
    """The atom with the largest value; ties go to the smallest atom_id (07 §2.1 topI/topE)."""
    return min(atoms, key=lambda a: (-a.value, a.atom_id)) if atoms else None


def _max(atoms: Iterable[Atom]) -> float:
    return max((a.value for a in atoms), default=0.0)


def _service_evidence(own: Sequence[Atom]) -> ServiceEvidence:
    def anomaly(kind: str, detector: str) -> list[Atom]:
        return [a for a in own if a.kind == kind and a.args.get("detector") == detector]

    internal, external = anomaly(INTERNAL, ROBUST_Z), anomaly(EXTERNAL, ROBUST_Z)
    onsets = [a.value for a in own if a.kind == ONSET and a.args.get("scope") == "self"]
    return ServiceEvidence(
        internal=_max(internal),
        external=_max(external),
        nsigma=_max([*anomaly(INTERNAL, NSIGMA), *anomaly(EXTERNAL, NSIGMA)]),
        silent=_max(a for a in own if a.kind == SILENCE),
        spectrum=_max(a for a in own if a.kind == SPECTRUM),
        change=_max(a for a in own if a.kind == CHANGE),
        onset_ms=min(onsets, default=math.inf),
        top_internal=_top(internal),
        top_external=_top(external),
    )


@dataclass(frozen=True)
class EvidenceView:
    """The engine atoms of the services in U, each service's 07 §2.1 quantities, and the ranker
    channels of 07 §3.3 (any robust_z / nsigma anomaly atom, any spectrum / change atom)."""

    universe: tuple[str, ...]
    atoms: tuple[Atom, ...]
    services: Mapping[str, ServiceEvidence]
    has_robust_z: bool
    has_nsigma: bool
    has_spectrum: bool
    has_change: bool

    def of(self, service: str) -> ServiceEvidence:
        """The quantities of `service` (all defaults outside U)."""
        return self.services.get(service, ServiceEvidence())

    def atoms_of(self, service: str, kind: str) -> tuple[Atom, ...]:
        return tuple(a for a in self.atoms if a.candidate == service and a.kind == kind)


def evidence_view(atoms: Iterable[Atom], members: Iterable[str]) -> EvidenceView:
    """The view of `atoms` over U = `members`; atoms about other candidates are dropped."""
    members_sorted = tuple(sorted(set(members)))
    by_service: dict[str, list[Atom]] = {s: [] for s in members_sorted}
    for atom in sorted(atoms, key=lambda a: (a.candidate, a.kind, a.atom_id)):
        if atom.candidate in by_service:
            by_service[atom.candidate].append(atom)
    kept = tuple(a for s in members_sorted for a in by_service[s])
    anomalies = [a for a in kept if a.kind in (INTERNAL, EXTERNAL)]
    return EvidenceView(
        universe=members_sorted,
        atoms=kept,
        services=MappingProxyType({s: _service_evidence(by_service[s]) for s in members_sorted}),
        has_robust_z=any(a.args.get("detector") == ROBUST_Z for a in anomalies),
        has_nsigma=any(a.args.get("detector") == NSIGMA for a in anomalies),
        has_spectrum=any(a.kind == SPECTRUM for a in kept),
        has_change=any(a.kind == CHANGE for a in kept),
    )


def component_of(service: str, ev: EvidenceView) -> str | None:
    """A candidate's component (07 §2.2): from topI, else topE; None if absent or equal to s."""
    facts = ev.of(service)
    top = facts.top_internal or facts.top_external
    return top.component if top is not None and top.component != service else None


# --- graph --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Edge:
    """One call edge caller → callee of `graph.edges` (03 §6.2)."""

    src: str
    dst: str
    weight: float
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class GraphView:
    """U, graph.nodes.kind of the nodes in U, and G = graph.edges restricted to U, sorted by
    (src, dst), self-edges dropped (07 §3.8); `callees(u)` lists u's out-edges in callee order."""

    universe: tuple[str, ...]
    kinds: Mapping[str, str]
    edges: tuple[Edge, ...]
    out: Mapping[str, tuple[Edge, ...]]

    @property
    def has_edges(self) -> bool:
        return bool(self.edges)

    def callees(self, node: str) -> tuple[Edge, ...]:
        return self.out.get(node, ())


def graph_view(
    services: Iterable[str], nodes: Iterable[tuple[str, str]], edges: Iterable[Row], *, include_external: bool
) -> GraphView:
    """U (06 §2.1) and G from case_manifest.services, (node, kind) pairs and edge rows."""
    node_list = sorted(set(nodes))
    members = universe(services, node_list, include_external=include_external)
    in_u = set(members)
    pairs = [(str(e["src"]), str(e["dst"]), e) for e in edges]
    kept = [
        Edge(
            src, dst, float(e["weight"]), tuple(sorted(str(p) for p in cast(Sequence[str], e["provenance"])))
        )
        for src, dst, e in sorted(pairs, key=lambda t: t[:2])
        if src != dst and src in in_u and dst in in_u
    ]
    out: dict[str, list[Edge]] = {}
    for edge in kept:
        out.setdefault(edge.src, []).append(edge)
    return GraphView(
        universe=members,
        kinds=MappingProxyType({n: k for n, k in node_list if n in in_u}),
        edges=tuple(kept),
        out=MappingProxyType({u: tuple(v) for u, v in sorted(out.items())}),
    )
