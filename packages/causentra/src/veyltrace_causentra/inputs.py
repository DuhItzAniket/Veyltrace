"""The 09 §2.1 inputs of one Causentra run, read once through the contract loaders.

U, the call graph G and the per-service quantities I, E, Sil, onset_ms come from Causatrix's views,
"exactly as in 07 §2.1" (09 §2.1). claim_check atoms are kept apart: only the claim pass writes
them, and the decision reads only their `holds` (02 §6.9 step 3). Optional inputs that are absent
read as empty (09 §6); a schema-invalid proposals.json counts as no proposals (06 §6).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from veyltrace_causatrix.config import CausatrixConfig
from veyltrace_causatrix.config import config_from as causatrix_config
from veyltrace_causatrix.views import EvidenceView, GraphView, engine_atoms, evidence_view, graph_view
from veyltrace_causentra.config import CausentraConfig
from veyltrace_contracts import models
from veyltrace_core.context import RunContext
from veyltrace_core.errors import ContractValidationError

#: Decimals every comparison and every verdict float uses (09 §5; 03 §1 canonical JSON).
DECIMALS: Final = 9
CLAIM_ORIGIN: Final = "claim_check"


@dataclass(frozen=True)
class Claim:
    """One claim_check atom: a library predicate evaluated for one candidate (03 §7)."""

    atom_id: str
    candidate: str
    predicate: str
    args_json: str
    holds: bool | None


@dataclass(frozen=True)
class CausentraInputs:
    """What the trials and the decision read (09 §2.1). q_hat None is +∞ (03 §10); tau_nf is the
    calibrated NO_FAULT threshold or no_fault.default_tau; degraded: schema-invalid proposals."""

    manifest: models.CaseManifest
    slate: models.Slate
    ev: EvidenceView
    graph: GraphView
    graph_nodes: frozenset[str]
    claims: tuple[Claim, ...]
    entry_services: tuple[str, ...]
    tol_ms: float
    proposals: models.Proposals | None
    q_hat: float | None
    tau_nf: float
    causatrix: CausatrixConfig
    notes: tuple[str, ...]
    degraded: bool


def _check_case(name: str, found: str, expected: str) -> None:
    if found != expected:
        raise ContractValidationError(name, f"case_id {found!r} does not match the run's {expected!r}")


def _proposals(ctx: RunContext) -> tuple[models.Proposals | None, tuple[str, ...]]:
    if not ctx.exists("proposals"):
        return None, ()
    try:
        proposals = ctx.read_model("proposals", models.Proposals, validate=True)
    except ContractValidationError as exc:
        return None, (f"proposals.json is schema-invalid: no valid proposals (06 §6): {exc}",)
    _check_case("proposals", proposals.case_id, ctx.case_id)
    return proposals, ()


def load_inputs(ctx: RunContext, cfg: CausentraConfig) -> CausentraInputs:
    """Read the run's inputs; `slate` and `evidence` must exist (the caller checks, 09 §6)."""
    manifest = ctx.read_model("case_manifest", models.CaseManifest)
    _check_case("case_manifest", manifest.case_id, ctx.case_id)
    if manifest.dataset != ctx.dataset:
        raise ContractValidationError("case_manifest", f"dataset {manifest.dataset!r} is not {ctx.dataset!r}")
    slate = ctx.read_model("slate", models.Slate)
    _check_case("slate", slate.case_id, ctx.case_id)
    xcfg = causatrix_config(ctx.with_config("causatrix").config, ctx.config.core)
    rows = ctx.read_table("evidence").to_pylist()
    nodes = [
        (str(r["node"]), str(r["kind"]))
        for r in ctx.read_table("graph.nodes", columns=["node", "kind"]).to_pylist()
    ]
    edge_columns = ["src", "dst", "weight", "provenance"]
    edges = (
        ctx.read_table("graph.edges", columns=edge_columns).to_pylist() if ctx.exists("graph.edges") else []
    )
    graph = graph_view(manifest.services, nodes, edges, include_external=xcfg.include_external)
    claims = sorted(
        (
            Claim(
                str(r["atom_id"]), str(r["candidate"]), str(r["predicate"]), str(r["args_json"]), r["holds"]
            )
            for r in rows
            if r["origin"] == CLAIM_ORIGIN
        ),
        key=lambda c: (c.candidate, c.predicate, c.args_json, c.atom_id),
    )
    onsets = ctx.read_model("onsets", models.Onsets)
    alignment = ctx.read_model("alignment", models.Alignment) if ctx.exists("alignment") else None
    proposals, notes = _proposals(ctx)
    absent = [n for n in ("graph.edges", "alignment") if not ctx.exists(n)]
    calibration = ctx.config.calibration
    if calibration is None:
        q_hat: float | None = cfg.uncalibrated_q_hat
    else:
        q_hat = None if calibration.q_hat is None or math.isinf(calibration.q_hat) else calibration.q_hat
    calibrated_tau = calibration is not None and calibration.no_fault.calibrated
    return CausentraInputs(
        manifest=manifest,
        slate=slate,
        ev=evidence_view(engine_atoms(rows), graph.universe),
        graph=graph,
        graph_nodes=frozenset(n for n, _ in nodes),
        claims=tuple(claims),
        entry_services=tuple(sorted(set(onsets.entry_services))),
        tol_ms=0.0 if alignment is None else alignment.tolerance_ns / 1e6,
        proposals=proposals,
        q_hat=q_hat,
        tau_nf=calibration.no_fault.tau_nf if calibration is not None and calibrated_tau else cfg.default_tau,
        causatrix=xcfg,
        notes=(*notes, *(f"optional input absent: {n} (read as empty; 09 §6)" for n in absent)),
        degraded=bool(notes),
    )
