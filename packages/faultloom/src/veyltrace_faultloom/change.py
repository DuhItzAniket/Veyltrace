"""Change, peer and log evidence atoms (06 §3.4): `change_proximity`, `peer_contrast`,
`log_new_template`, `log_error_rate`.

Why: trial T6 needs how close a change on c came before its onset, T7 whether c's affected replica
differs from its peers, and the log atoms carry the error-keyword signal that let SimpleRCA reach
0.83 Top-1 on RE3-SS and RE3-TT (06 §3.4 "Log atoms"). Every service in U is computed the same way;
a missing source gives no atom (06 §6).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Final

from veyltrace_core.errors import ConfigError
from veyltrace_faultloom.atoms import Atom, engine_atom
from veyltrace_faultloom.inputs import AnomalyRow, ChangeRow, EvidenceInputs, TemplateRow

__all__ = ["change_atoms", "log_atoms", "median", "peer_atoms"]

_NS_PER_S: Final = 1_000_000_000
#: Scope of a change that maps to no single service (06 §2.1, §11 Q6).
_CLUSTER: Final = "cluster"


def median(values: Iterable[float]) -> float:
    """Median (06 §3.4): an even count averages the sorted middle pair; no values is a ValueError."""
    xs = sorted(values)
    if not xs:
        raise ValueError("median of no values")
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else math.fsum(xs[mid - 1 : mid + 1]) / 2


def _owners(change: ChangeRow, components: Mapping[str, frozenset[str]]) -> list[str]:
    """Services a change maps to: entity == s, or entity is a component of s (06 §2.1)."""
    if change.scope == _CLUSTER:
        return []
    return sorted(s for s, comps in components.items() if change.entity == s or change.entity in comps)


def change_atoms(view: EvidenceInputs) -> list[Atom]:
    """`change_proximity` per (c, change) with proximity > 0, and `peer_contrast{changes}` per c;
    none when the case has no events (06 §6)."""
    if not view.sources.events:
        return []
    members = frozenset(view.universe)
    components = {s: view.components.get(s, frozenset()) for s in view.universe}
    by_service: dict[str, list[ChangeRow]] = {}
    for change in view.changes:
        for s in _owners(change, components):
            if s in members:
                by_service.setdefault(s, []).append(change)
    atoms: list[Atom] = []
    for c in sorted(by_service):
        mine = by_service[c]
        for ch in mine:
            if ch.proximity > 0:
                args = {"change_id": ch.change_id, "event_kind": ch.kind, "window": "onset"}
                refs = (ch.change_id,)
                atoms.append(
                    engine_atom("change_proximity", c, args, value=ch.proximity, unit=None, refs=refs)
                )
        gaps = [ch.peer_contrast for ch in mine if ch.peer_contrast is not None]
        if gaps:
            top = max(gaps)
            refs = (ch.change_id for ch in mine if ch.peer_contrast == top)
            args = {"source": "changes", "window": "onset"}
            atoms.append(engine_atom("peer_contrast", c, args, value=top, unit="z", refs=refs))
    return atoms


def peer_atoms(view: EvidenceInputs, min_components: int) -> list[Atom]:
    """`peer_contrast{anomalies}`: top component's max internal robust_z minus the median of the
    other components' max, for services with >= `min_components` (at least 2) such components."""
    if min_components < 2:
        raise ConfigError(f"faultloom.peer.min_components must be >= 2, got {min_components}")
    per: dict[str, dict[str, list[AnomalyRow]]] = {}
    for r in view.anomalies:
        if r.klass == "internal" and r.detector == "robust_z":
            per.setdefault(r.service, {}).setdefault(r.component, []).append(r)
    atoms: list[Atom] = []
    for c in view.universe:
        comps = per.get(c, {})
        if len(comps) < min_components:
            continue
        best = {k: max(r.score for r in rows) for k, rows in comps.items()}
        top = max(best.values())
        lead = min(k for k, v in best.items() if v == top)
        gap = top - median(v for k, v in best.items() if k != lead)
        refs = (r.series_id for k, rows in comps.items() for r in rows if r.score == best[k])
        args = {"source": "anomalies", "window": "incident"}
        atoms.append(engine_atom("peer_contrast", c, args, value=gap, unit="z", refs=refs, component=lead))
    return atoms


def _window_s(window: tuple[int, int]) -> float:
    return (window[1] - window[0]) / _NS_PER_S


def log_atoms(view: EvidenceInputs, min_count: int) -> list[Atom]:
    """`log_new_template` (error_level_only false and true) and `log_error_rate` per c with
    templates, when the case has logs (06 §3.4 "Log atoms")."""
    if not view.sources.logs:
        return []
    per: dict[str, list[TemplateRow]] = {}
    for t in view.templates:
        per.setdefault(t.service, []).append(t)
    dur_base, dur_inc = _window_s(view.w_base), _window_s(view.w_inc)
    atoms: list[Atom] = []
    for c in view.universe:
        rows = per.get(c, [])
        if not rows:
            continue
        fresh = [t for t in rows if t.count_baseline == 0 and t.count_incident >= min_count]
        for errors_only in (False, True):
            new = [t.template_id for t in fresh if t.error_level or not errors_only]
            args = {"error_level_only": errors_only, "min_count": min_count, "window": "incident"}
            atoms.append(engine_atom("log_new_template", c, args, value=len(new), unit="count", refs=new))
        if dur_base > 0 and dur_inc > 0:  # a zero-length window has no rate
            err = [t for t in rows if t.error_level]
            inc = math.fsum(t.count_incident for t in err) / dur_inc
            rate = inc - math.fsum(t.count_baseline for t in err) / dur_base
            refs = [t.template_id for t in err]
            atoms.append(
                engine_atom(
                    "log_error_rate", c, {"window": "incident"}, value=rate, unit="lines/s", refs=refs
                )
            )
    return atoms
