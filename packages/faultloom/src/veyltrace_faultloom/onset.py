"""Onset-table evidence atoms (06 §3.4): `silence` (R-08a); `onset_precedence` follows in R-08b.

Why: trials T1 and T4 need to know which services went silent, because a service that stops
reporting is never healthy (06 §3.4 "Silence"). Every service in U is computed the same way; a
service absent from both onsets.per_service and anomalies gets no atom, never a zero (06 §6).
"""

from __future__ import annotations

from typing import Final

from veyltrace_faultloom.atoms import Atom, engine_atom
from veyltrace_faultloom.inputs import AnomalyRow, EvidenceInputs

__all__ = ["SILENCE_WINDOW", "silence_atoms"]

SILENCE_WINDOW: Final = "incident"
_SILENCE_DETECTOR: Final = "silence"


def silence_atoms(view: EvidenceInputs) -> list[Atom]:
    """One `silence` atom per service in U that is in onsets.per_service or in any anomalies row.

    value 1.0 if the onsets entry is silent or a `silence`-detector row is above threshold. refs are
    the rows that made it 1.0, or every row examined when it is 0.0. component = the A→Z first
    component of a silent series when only series (not the onsets entry) made it 1.0.
    """
    of = view.onset_of
    seen = {r.service for r in view.anomalies}
    rows: dict[str, list[AnomalyRow]] = {}
    for r in view.anomalies:
        if r.detector == _SILENCE_DETECTOR:
            rows.setdefault(r.service, []).append(r)
    atoms: list[Atom] = []
    args = {"window": SILENCE_WINDOW}
    for c in view.universe:
        entry = of.get(c)
        if entry is None and c not in seen:
            continue
        mine = rows.get(c, [])
        hot = [r.series_id for r in mine if r.above_threshold]
        entry_ref = () if entry is None else (entry.ref,)
        if entry is not None and entry.silent:
            atoms.append(engine_atom("silence", c, args, value=1.0, unit=None, refs=(*entry_ref, *hot)))
        elif hot:
            component = min(r.component for r in mine if r.above_threshold)
            atoms.append(engine_atom("silence", c, args, value=1.0, unit=None, refs=hot, component=component))
        else:
            refs = (*entry_ref, *(r.series_id for r in mine))
            atoms.append(engine_atom("silence", c, args, value=0.0, unit=None, refs=refs))
    return atoms
