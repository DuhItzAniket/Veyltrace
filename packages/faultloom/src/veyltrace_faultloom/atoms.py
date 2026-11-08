"""Anomaly evidence atoms (R-06): `internal_anomaly` and `external_anomaly` (06 §3.4), stable ids.

Why: they carry Anomara's per-series scores to the rankers and the verifier. Anomara writes one row
per series and detector even below threshold (03 §4.1), so healthy services get atoms too, which
lets rankers order them. Every service in U is treated alike; nothing here ranks or drops one. The
output depends only on the set of input rows, never on their order (06 §5).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Final

from veyltrace_core.canonical import JSONLike, canonical_json_str
from veyltrace_core.errors import ConfigError, ContractValidationError
from veyltrace_core.ids import atom_id
from veyltrace_faultloom import ALGO_VERSION
from veyltrace_faultloom.inputs import AnomalyRow

__all__ = ["ANOMALY_WINDOW", "KIND_OF_KLASS", "PRODUCER", "UNIT_OF_DETECTOR", "anomaly_atoms", "check_unique"]

#: evidence.producer (03 §7); the algorithm revision, not the release, so goldens do not churn.
PRODUCER: Final = f"faultloom@{ALGO_VERSION}"
#: Atom kind per anomalies.klass (06 §3.4); context-klass series have none (06 §11 Q4).
KIND_OF_KLASS: Final[Mapping[str, str]] = MappingProxyType(
    {"internal": "internal_anomaly", "external": "external_anomaly"}
)
#: Unit per detector (06 §3.4 "Units"); atoms.detectors may name only these.
UNIT_OF_DETECTOR: Final[Mapping[str, str]] = MappingProxyType(
    {"robust_z": "z", "nsigma": "sigma", "silence": "score"}
)
#: Anomara scores every series over the incident window (03 §4.1, 06 §3.4).
ANOMALY_WINDOW: Final = "incident"

type Atom = dict[str, JSONLike]
#: (kind, candidate, detector, family, source): one anomaly atom.
type _Key = tuple[str, str, str, str, str]


def anomaly_atoms(
    rows: Iterable[AnomalyRow], universe: Iterable[str], detectors: Iterable[str]
) -> list[Atom]:
    """One evidence row per (klass, service in U, detector, family, source) with ≥ 1 row (06 §3.4).

    value = max score over the group (all components); component = the maximising row's, A→Z on
    ties, null when it is the service; refs = every series_id attaining the maximum. A NaN or ±inf
    score is a contract error (03 §1): max() over it would depend on row order.
    """
    pool = tuple(rows)
    bad = sorted(f"{r.series_id}/{r.detector}" for r in pool if not math.isfinite(r.score))
    if bad:
        msg = f"scores are not finite (03 §1): {bad}"
        raise ContractValidationError("anomalies", msg)
    wanted = frozenset(detectors)
    unknown = sorted(wanted - UNIT_OF_DETECTOR.keys())
    if unknown:
        known = sorted(UNIT_OF_DETECTOR)
        msg = f"faultloom.atoms.detectors: {unknown} have no anomaly-atom unit (06 §3.4 defines {known})"
        raise ConfigError(msg)
    members = frozenset(universe)
    groups: dict[_Key, list[AnomalyRow]] = {}
    for row in pool:
        kind = KIND_OF_KLASS.get(row.klass)
        if kind is None or row.service not in members or row.detector not in wanted:
            continue
        groups.setdefault((kind, row.service, row.detector, row.family, row.source), []).append(row)
    atoms = [_atom(key, groups[key]) for key in sorted(groups)]
    check_unique(atoms)
    return atoms


def _atom(key: _Key, group: list[AnomalyRow]) -> Atom:
    kind, candidate, detector, family, source = key
    value = max(r.score for r in group)
    top = [r for r in group if r.score == value]
    component = min(r.component for r in top)
    args = {"detector": detector, "family": family, "source": source, "window": ANOMALY_WINDOW}
    return {
        "atom_id": atom_id(kind, candidate, args),
        "candidate": candidate,
        "component": None if component == candidate else component,
        "kind": kind,
        "predicate": None,
        "args_json": canonical_json_str(args),
        "value": value,
        "unit": UNIT_OF_DETECTOR[detector],
        "window": ANOMALY_WINDOW,
        "refs": sorted({r.series_id for r in top}),
        "origin": "engine",
        "holds": None,
        "producer": PRODUCER,
    }


def check_unique(atoms: Iterable[Atom]) -> None:
    """Raise if two different atoms share an atom_id: never drop one, atoms are cited by id (06 §3.1)."""
    seen: dict[JSONLike, tuple[JSONLike, ...]] = {}
    for atom in atoms:
        ident = (atom["kind"], atom["candidate"], atom["args_json"])
        prior = seen.setdefault(atom["atom_id"], ident)
        if prior != ident:
            msg = f"atom_id {atom['atom_id']} collides: {prior} and {ident} (06 §3.1 step 3)"
            raise ContractValidationError("evidence", msg)
