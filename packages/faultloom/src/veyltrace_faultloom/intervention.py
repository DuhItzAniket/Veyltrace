"""`intervention` atoms for Causentra's trial T8 (06 §3.4, §3.6 step 6), written in the claim pass.

Why here: T8 asks whether a candidate's anomaly survives regressing out its parents. Causalith owns
that restricted conditional-independence test (05 §3.7) as a pure library function; FaultLoom turns
its result into evidence, so Causentra keeps reading atoms only (02 §6.9). The test runs for the
first `intervention.max_candidates` members of the decision pool D in `slate.all_scores` order, D
being the slate plus every proposed service in graph.nodes with a valid supporting claim that this
pass found true for it (the 02 §6.9 step 1 rule). An untestable result writes no atom, so T8 is
`untestable` for that candidate.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from veyltrace_causalith.ci import CIConfig, CIResult, intervention_test
from veyltrace_contracts import models
from veyltrace_core.canonical import canonical_json_str
from veyltrace_core.context import RunContext
from veyltrace_core.hashing import sha256_json
from veyltrace_faultloom.atoms import Atom, engine_atom
from veyltrace_faultloom.claims import EVALUATED_STATUSES
from veyltrace_faultloom.validation import CaseDomain, ValidClaim, validate

__all__ = ["KIND", "ci_config", "decision_pool", "intervention_atom", "intervention_atoms", "target_series"]

KIND: Final = "intervention"
#: The incident window, as for every anomaly-derived atom (06 §3.4).
WINDOW: Final = "incident"
#: parents_hash = the first 12 hex of sha256_json(CIResult.parents) (06 §3.4).
PARENTS_HASH_HEX: Final = 12
#: stat_resid is a robust z, the unit of the anomaly atoms (06 §3.4).
UNIT: Final = "z"
#: The signal_cube.series and graph.edges columns Causalith's intervention_test reads (05 §3.7).
SERIES_COLUMNS: Final = ("series_id", "service", "signal", "family", "source", "unit", "t_ns", "value")
EDGE_COLUMNS: Final = ("src", "dst", "weight", "anomalous")


def decision_pool(
    slate: models.Slate,
    proposals: models.Proposals | None,
    claim_rows: Iterable[Atom],
    domain: CaseDomain,
    nodes: frozenset[str],
) -> tuple[str, ...]:
    """D in `slate.all_scores` order (services without a score last, A→Z); 06 §3.6 step 6."""
    pool = {c.service for c in slate.candidates}
    if proposals is not None and proposals.status in EVALUATED_STATUSES:
        holding = {(a["candidate"], a["predicate"], a["args_json"]) for a in claim_rows if a["holds"] is True}
        for p in proposals.proposals:
            service = p.hypothesis.service
            for claim in p.claims:
                got = validate(claim.predicate, claim.args, domain)
                if (
                    service in nodes
                    and isinstance(got, ValidClaim)
                    and got.predicate.polarity == 1  # supports (06 §3.5)
                    and (service, got.predicate.name, canonical_json_str(got.args)) in holding
                ):
                    pool.add(service)
    order = {s.service: i for i, s in enumerate(slate.all_scores)}
    return tuple(sorted(pool, key=lambda s: (order.get(s, len(order)), s)))


def target_series(candidate: str, engine: Sequence[Atom]) -> str | None:
    """The refs series of c's top internal_anomaly{robust_z} atom (largest value, then smallest
    atom_id; its first ref), or None to let Causalith pick its default target (06 §3.4)."""
    tops = [
        a
        for a in engine
        if a["candidate"] == candidate
        and a["kind"] == "internal_anomaly"
        and json.loads(str(a["args_json"])).get("detector") == "robust_z"
    ]
    if not tops:
        return None
    top = min(tops, key=lambda a: (-_value(a), str(a["atom_id"])))
    found = top["refs"]
    refs = sorted(str(r) for r in found) if isinstance(found, list | tuple) else []
    return refs[0] if refs else None


def _value(atom: Atom) -> float:
    value = atom["value"]
    return float(value) if isinstance(value, int | float) else -math.inf


def intervention_atom(result: CIResult) -> Atom | None:
    """The atom of one testable result; None when Causalith marked it untestable (06 §3.4)."""
    if result.reason is not None or result.target_series_id is None or not math.isfinite(result.stat_resid):
        return None
    args = {
        "parents_hash": sha256_json(list(result.parents))[:PARENTS_HASH_HEX],
        "series_id": result.target_series_id,
        "window": WINDOW,
    }
    refs = (result.target_series_id, *result.parents)
    return engine_atom(KIND, result.candidate, args, value=result.stat_resid, unit=UNIT, refs=refs)


def intervention_atoms(
    ctx: RunContext, pool: Sequence[str], engine: Sequence[Atom], cfg: CIConfig, max_candidates: int
) -> list[Atom]:
    """One atom per testable member among the first `max_candidates` of D (06 §3.6 step 6), on the
    run's signal_cube.series, graph.edges and alert (the caller checks the tables exist)."""
    series = ctx.read_table("signal_cube.series", columns=list(SERIES_COLUMNS))
    edges = ctx.read_table("graph.edges", columns=list(EDGE_COLUMNS))
    alert = ctx.read_model("alert", models.Alert)
    out: list[Atom] = []
    for candidate in pool[:max_candidates]:
        result = intervention_test(series, edges, alert, candidate, cfg, target_series(candidate, engine))
        atom = intervention_atom(result)
        if atom is not None:
            out.append(atom)
    return out


def ci_config(causalith: Mapping[str, object], anomara: Mapping[str, object]) -> CIConfig:
    """Causalith's CI config from the run's `causalith` and `anomara` sections (05 §3.7)."""
    return CIConfig.from_sections(causalith, anomara)
