"""Graph evidence atoms (06 §3.4): `onset_precedence` and `propagation`.

Why: trial T2 (precedence) needs each service's aligned onset relative to the incident onset and to
its anomalous callers; trial T3 (propagation) needs how much of the observed anomaly is explained
by what c can reach, the "explanatory coverage" check. Anomalies propagate from a callee to its
callers, so both walk the call graph against the call direction. Every service in U is computed
the same way; a missing onset or an empty graph gives no atom, never a zero (06 §6).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from typing import Final

from veyltrace_faultloom.atoms import Atom, engine_atom
from veyltrace_faultloom.inputs import AnomalyRow, CallEdge, EvidenceInputs, ServiceOnset
from veyltrace_faultloom.onset import silent_services

__all__ = ["NS_PER_MS", "callers", "onset_atoms", "propagation_atoms"]

#: ns -> ms for onset differences (03 §1 Units: durations in ms).
NS_PER_MS: Final = 1_000_000


def callers(edges: Iterable[CallEdge]) -> Mapping[str, frozenset[str]]:
    """Transitive callers of every callee: d with a path d -> ... -> c (06 §3.4), c excluded.

    BFS over sorted adjacency, so cycles are harmless (06 §3.9).
    """
    up: dict[str, set[str]] = {}
    for e in edges:
        up.setdefault(e.dst, set()).add(e.src)
    found: dict[str, frozenset[str]] = {}
    for start in sorted(up):
        seen: set[str] = set()
        queue = deque(sorted(up[start]))
        while queue:
            node = queue.popleft()
            if node not in seen:
                seen.add(node)
                queue.extend(sorted(up.get(node, ())))
        found[start] = frozenset(seen - {start})
    return found


def _max_z(rows: Iterable[AnomalyRow], klasses: frozenset[str]) -> Mapping[str, float]:
    best: dict[str, float] = {}
    for r in rows:
        if r.klass in klasses and r.detector == "robust_z":
            best[r.service] = max(best.get(r.service, r.score), r.score)
    return best


def _ms(delta_ns: int) -> float:
    return delta_ns / NS_PER_MS


def _scoped(kind: str, window: str) -> Callable[[str, str, float, str | None, Iterable[str]], Atom]:
    def build(c: str, scope: str, value: float, unit: str | None, refs: Iterable[str]) -> Atom:
        return engine_atom(kind, c, {"scope": scope, "window": window}, value=value, unit=unit, refs=refs)

    return build


def onset_atoms(view: EvidenceInputs) -> list[Atom]:
    """`onset_precedence` atoms of every service in U with an onset (06 §3.4).

    self: (onset(c) - t_onset) in ms. dependents: fraction of D(c) (transitive callers with an
    onset and external robust_z >= k_anom) that c precedes or ties within tol_ns.
    internal_vs_external: external - internal aligned onset in ms (positive = internal first).
    """
    of, up, atom = view.onset_of, callers(view.edges), _scoped("onset_precedence", "onset")
    ext_z = _max_z(view.anomalies, frozenset({"external"}))
    atoms: list[Atom] = []
    for c in view.universe:
        entry = of.get(c)
        t = None if entry is None else entry.onset_ns
        if entry is None or t is None:
            continue
        atoms.append(atom(c, "self", _ms(t - view.t_onset_ns), "ms", (entry.ref,)))
        deps = _dependents(up.get(c, frozenset()), of, ext_z, view.k_anom)
        if deps:
            first = sum(1 for _, t_d in deps if t <= t_d + view.tol_ns) / len(deps)
            atoms.append(atom(c, "dependents", first, None, (entry.ref, *(d.ref for d, _ in deps))))
        if entry.internal_ns is not None and entry.external_ns is not None:
            gap = _ms(entry.external_ns - entry.internal_ns)
            atoms.append(atom(c, "internal_vs_external", gap, "ms", (entry.ref,)))
    return atoms


def _dependents(
    up: frozenset[str], of: Mapping[str, ServiceOnset], ext_z: Mapping[str, float], k_anom: float
) -> list[tuple[ServiceOnset, int]]:
    """D(c) with each onset: callers with an onset and max external robust_z >= k_anom, A→Z."""
    found: list[tuple[ServiceOnset, int]] = []
    for d in sorted(up):
        entry = of.get(d)
        t_d = None if entry is None else entry.onset_ns
        if entry is not None and t_d is not None and d in ext_z and ext_z[d] >= k_anom:
            found.append((entry, t_d))
    return found


def propagation_atoms(view: EvidenceInputs) -> list[Atom]:
    """`propagation` atoms of every service in U (06 §3.4), on the reversed call graph.

    entry: fraction of anomalous entry services (onsets.entry_services | is_entry, external
    robust_z >= k_anom) that c reaches, c reaching itself. anomalous: fraction of the other
    anomalous services of U (internal or external robust_z >= k_anom, or silent) that c reaches.
    path: anomalous_fraction of c's rank-1 graph.paths row. refs: the graph rows used.
    """
    up, atom = callers(view.edges), _scoped("propagation", "incident")
    ext_z = _max_z(view.anomalies, frozenset({"external"}))
    any_z = _max_z(view.anomalies, frozenset({"internal", "external"}))
    entries = set(view.entry_services) | {n.node for n in view.nodes if n.is_entry}
    hot_entries = sorted(s for s in entries if s in ext_z and ext_z[s] >= view.k_anom)
    silent = silent_services(view)
    anomalous = sorted(s for s in view.universe if (s in any_z and any_z[s] >= view.k_anom) or s in silent)
    paths = {p.candidate: p for p in view.paths if p.path_rank == 1}
    atoms: list[Atom] = []
    for c in view.universe:
        reach = up.get(c, frozenset()) | {c}
        used = tuple(e.ref for e in view.edges if e.dst in reach)
        others = [s for s in anomalous if s != c]
        for scope, targets in (("entry", hot_entries), ("anomalous", others)):
            if view.edges and targets:
                atoms.append(atom(c, scope, sum(1 for s in targets if s in reach) / len(targets), None, used))
        path = paths.get(c)
        if path is not None:
            atoms.append(atom(c, "path", path.anomalous_fraction, None, (path.ref,)))
    return atoms
