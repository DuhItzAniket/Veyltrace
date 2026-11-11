"""FaultLoom's two passes (02 §4): the engine pass (step 5) and the symmetric claim pass (step 8).

Engine pass: every engine atom kind of 06 §3.4 for every service in U, minus `atoms.disabled`,
written only through the contract writer (06 §3.1). Claim pass: the main-pass evidence is read back
unchanged and the `claim_check` atoms of 06 §3.6 are appended, so engine atoms are byte-identical
before and after (06 §2.2). `intervention` atoms (06 §3.6 step 6, trial T8) are R-12, so Causentra
marks T8 untestable until then; every claim-pass result says so in a note.
"""

from __future__ import annotations

from typing import Final

from veyltrace_contracts import models
from veyltrace_core.context import EngineResult, RunContext
from veyltrace_core.errors import ContractValidationError
from veyltrace_faultloom.atoms import KINDS, Atom, anomaly_atoms, check_unique, drop_disabled
from veyltrace_faultloom.change import change_atoms, log_atoms, peer_atoms
from veyltrace_faultloom.claims import claim_atoms, valid_claims
from veyltrace_faultloom.graph import onset_atoms, propagation_atoms
from veyltrace_faultloom.inputs import (
    CLAIM_REQUIRED,
    MAIN_REQUIRED,
    EvidenceInputs,
    load_inputs,
    missing_required,
)
from veyltrace_faultloom.onset import silence_atoms
from veyltrace_faultloom.predicates import ClaimView
from veyltrace_faultloom.trace import critical_path_atoms, edge_gap_atoms, self_time_atoms, spectrum_atoms
from veyltrace_faultloom.validation import domain_of

__all__ = ["ENGINE", "INTERVENTION_NOTE", "claim_pool", "engine_atoms", "run_claim_pass", "run_main"]

ENGINE: Final = "faultloom"
#: Note of every claim-pass result until R-12 adds the T8 intervention atoms (06 §3.6 step 6).
INTERVENTION_NOTE: Final = "no intervention atoms yet (R-12): Causentra marks T8 untestable"


def _failed(missing: tuple[str, ...]) -> EngineResult:
    # 06 §6: a required contract file absent fails the step; the pipeline stops.
    return EngineResult(
        engine=ENGINE,
        status="failed",
        notes=(f"required input(s) absent: {', '.join(missing)} (06 §6)",),
    )


def _input_metrics(view: EvidenceInputs) -> dict[str, int | float]:
    metrics: dict[str, int | float] = {f"rows.{name}": count for name, count in view.rows.items()}
    metrics["universe"] = len(view.universe)
    metrics["inputs_absent"] = len(view.absent)
    return metrics


def _notes(view: EvidenceInputs, *extra: str) -> tuple[str, ...]:
    absent = tuple(
        f"optional input absent: {name} (no rows, 06 §6)" for name in view.absent if name != "alignment"
    )
    return (*view.notes, *absent, *extra)


def engine_atoms(ctx: RunContext, view: EvidenceInputs) -> list[Atom]:
    """Every engine atom of U built so far, minus `atoms.disabled` (06 §3.1 step 2, §9); ids unique."""
    detectors = (str(d) for d in ctx.config["atoms"]["detectors"])
    found = [
        *anomaly_atoms(view.anomalies, view.universe, detectors),
        *onset_atoms(view),
        *propagation_atoms(view),
        *change_atoms(view),
        *peer_atoms(view, int(ctx.config["peer"]["min_components"])),
        *log_atoms(view, int(ctx.config["templates"]["min_count"])),
        *silence_atoms(view),
        *_trace_atoms(ctx, view),
    ]
    atoms = drop_disabled(found, (str(k) for k in ctx.config["atoms"]["disabled"]))
    check_unique(atoms)
    return atoms


def _trace_atoms(ctx: RunContext, view: EvidenceInputs) -> list[Atom]:
    spectrum, self_time = ctx.config["spectrum"], ctx.config["self_time"]
    return [
        *spectrum_atoms(view, str(spectrum["formula"]), str(spectrum["weighting"])),
        *critical_path_atoms(view),
        *self_time_atoms(view, str(self_time["quantile"]), float(self_time["min_total_increase_ms"])),
        *edge_gap_atoms(view, int(ctx.config["edge_gap"]["min_calls"])),
    ]


def run_main(ctx: RunContext) -> EngineResult:
    """Engine pass (pipeline step 5): read every input, write the engine atoms of U (06 §3.1)."""
    missing = missing_required(ctx, MAIN_REQUIRED)
    if missing:
        return _failed(missing)
    view = load_inputs(ctx)
    atoms = engine_atoms(ctx, view)
    digest = ctx.write("evidence", atoms)
    metrics = _input_metrics(view)
    metrics["atoms"] = len(atoms)
    for kind in KINDS:
        metrics[f"atoms.{kind}"] = sum(1 for a in atoms if a["kind"] == kind)
    return EngineResult(
        engine=ENGINE, status="ok", outputs=(("evidence", digest),), metrics=metrics, notes=_notes(view)
    )


def claim_pool(
    slate: models.Slate, proposals: models.Proposals | None, nodes: frozenset[str]
) -> tuple[str, ...]:
    """Claim-pass pool P = slate services | proposed services that are graph nodes, A→Z (06 §3.6 step 2).

    A proposed service outside graph.nodes has no data in the case (Causentra rejects it as
    unknown_entity), so it is left out. The result depends only on the sets, never on order.
    """
    pool = {c.service for c in slate.candidates}
    if proposals is not None:
        pool.update(p.hypothesis.service for p in proposals.proposals if p.hypothesis.service in nodes)
    return tuple(sorted(pool))


def _read_proposals(ctx: RunContext) -> tuple[models.Proposals | None, tuple[str, ...]]:
    """proposals.json, or None with the reason: absent (AI off, 06 §3.6 step 1) or schema-invalid
    (06 §6: claim pass skipped, status degraded)."""
    if not ctx.exists("proposals"):
        return None, ()
    try:
        return ctx.read_model("proposals", models.Proposals, validate=True), ()
    except ContractValidationError as exc:
        return None, (f"proposals.json is schema-invalid, claims skipped (06 §6): {exc}",)


def run_claim_pass(ctx: RunContext) -> EngineResult:
    """Claim pass (pipeline step 8): engine atoms carried forward, claim_check atoms appended.

    Every distinct valid (predicate, args) pair runs for every candidate of the claim-pass pool
    (06 §3.6). The step is `degraded` only when proposals.json is schema-invalid (06 §6).
    """
    missing = missing_required(ctx, CLAIM_REQUIRED)
    if missing:
        return _failed(missing)
    view = load_inputs(ctx)
    slate = ctx.read_model("slate", models.Slate)
    if slate.case_id != ctx.case_id:
        msg = f"case_id {slate.case_id!r} is not the run's case {ctx.case_id!r}"
        raise ContractValidationError("slate", msg)
    proposals, problems = _read_proposals(ctx)
    pool = claim_pool(slate, proposals, view.node_names)
    # Only engine rows are carried forward, so re-running the step never duplicates claim atoms.
    engine: list[Atom] = [a for a in ctx.read_table("evidence").to_pylist() if a["origin"] == "engine"]
    claims, rejected = valid_claims(proposals, domain_of(view, ctx.config))
    found = claim_atoms(ClaimView(view, tuple(engine)), pool, claims)
    added = drop_disabled(found, (str(k) for k in ctx.config["atoms"]["disabled"]))
    check_unique([*engine, *added])
    digest = ctx.write("evidence", [*engine, *added])
    metrics: dict[str, int | float] = {
        **_input_metrics(view),
        "atoms": len(engine) + len(added),
        "atoms.claim_check": len(added),
        "claims.seen": sum(len(p.claims) for p in proposals.proposals) if proposals is not None else 0,
        "claims.valid": len(claims),
        "pool": len(pool),
    }
    metrics.update({f"claims.rejected.{reason}": n for reason, n in rejected.items()})
    return EngineResult(
        engine=ENGINE,
        status="degraded" if problems else "ok",
        outputs=(("evidence", digest),),
        metrics=metrics,
        notes=_notes(view, *problems, INTERVENTION_NOTE),
    )
