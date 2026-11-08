"""FaultLoom R-00 stub, both passes wired end to end; the engine pass has R-06's anomaly atoms.

Why this exists: the Reason engines must run on synth through the pipeline before their algorithms
land (07 roadmap R-00, "stub: schema-valid evidence on synth"). The stub reads every input of
06 §2.1 through the run context, derives the shared values (U, tol_ns, windows; claim-pass pool)
and writes `evidence` only through the contract writer. The engine pass writes R-06's anomaly
atoms (`veyltrace_faultloom.atoms`); every other kind of 03 §7 comes with R-08 (with the predicate
library and the symmetric claim pass), and intervention atoms with R-12, so none is written yet.
Absence is honest ("absence is no atom", 06 §6); a 0.0 value would look like a healthy measurement.

Claim pass: engine atoms are read back and rewritten unchanged (06 §2.2), so the evidence file is
byte-identical before and after when no claim is evaluated.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from veyltrace_contracts import models
from veyltrace_core.context import EngineResult, RunContext
from veyltrace_core.errors import ContractValidationError
from veyltrace_faultloom.atoms import KINDS, Atom, anomaly_atoms, check_unique, drop_disabled
from veyltrace_faultloom.graph import onset_atoms, propagation_atoms
from veyltrace_faultloom.inputs import (
    CLAIM_REQUIRED,
    MAIN_REQUIRED,
    EvidenceInputs,
    load_inputs,
    missing_required,
)
from veyltrace_faultloom.onset import silence_atoms

__all__ = ["ENGINE", "STUB_NOTE", "claim_pool", "engine_atoms", "run_claim_pass", "run_main"]

ENGINE: Final = "faultloom"
#: EngineResult.notes entry of every stub result. It starts with veyltrace_core.cli.STUB_MARK
#: ("stub: "), so diagnose warns that the run's outputs are not analysis.
STUB_NOTE: Final = "stub: FaultLoom R-08 in progress: no change, peer, log, trace or claim atoms yet"
#: proposals.status values whose proposals the claim pass would evaluate (03 §9.1).
_EVALUATED_STATUSES: Final = frozenset({"complete", "budget_exhausted"})


def _failed(missing: tuple[str, ...]) -> EngineResult:
    # 06 §6: a required contract file absent fails the step; the pipeline stops.
    return EngineResult(
        engine=ENGINE,
        status="failed",
        notes=(STUB_NOTE, f"required input(s) absent: {', '.join(missing)} (06 §6)"),
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
    return (STUB_NOTE, *view.notes, *absent, *extra)


def engine_atoms(ctx: RunContext, view: EvidenceInputs) -> list[Atom]:
    """Every engine atom of U built so far, minus `atoms.disabled` (06 §3.1 step 2, §9); ids unique."""
    detectors = (str(d) for d in ctx.config["atoms"]["detectors"])
    found = [
        *anomaly_atoms(view.anomalies, view.universe, detectors),
        *onset_atoms(view),
        *propagation_atoms(view),
        *silence_atoms(view),
    ]
    atoms = drop_disabled(found, (str(k) for k in ctx.config["atoms"]["disabled"]))
    check_unique(atoms)
    return atoms


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


def _claim_count(proposals: models.Proposals | None) -> int:
    if proposals is None or proposals.status not in _EVALUATED_STATUSES:
        return 0
    return sum(len(p.claims) for p in proposals.proposals)


def run_claim_pass(ctx: RunContext) -> EngineResult:
    """Claim pass (pipeline step 8): carry the main-pass evidence forward unchanged.

    No claim is evaluated (R-08) and no intervention atom is computed (R-12). The step is
    `degraded` when proposals.json is schema-invalid (06 §6) or when it holds claims the stub
    cannot evaluate, so a run with real proposals is never reported as fully checked.
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
    claims = _claim_count(proposals)

    evidence = ctx.read_table("evidence")
    digest = ctx.write("evidence", evidence)

    extra = list(problems)
    if claims:
        extra.append(f"{claims} claim(s) not evaluated: the predicate library arrives in R-08 (06 §3.5)")
    metrics: Mapping[str, int | float] = {
        **_input_metrics(view),
        "atoms": evidence.num_rows,
        "atoms.claim_check": 0,
        "claims.seen": claims,
        "claims.evaluated": 0,
        "pool": len(pool),
    }
    return EngineResult(
        engine=ENGINE,
        status="degraded" if extra else "ok",
        outputs=(("evidence", digest),),
        metrics=metrics,
        notes=_notes(view, *extra),
    )
