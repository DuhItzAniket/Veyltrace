"""Assemble `verdict.json` from the decision (09 §2.2, §3.13; 03 §10).

Every float is already the 9-decimal value the decision compared, so canonical JSON changes
nothing, and `verdict_hash` = sha256 of the canonical verdict without `verdict_hash` and `run_id`
(a replay must reproduce the hash of the recorded run).
"""

from __future__ import annotations

from typing import Any

from veyltrace_causentra.config import CausentraConfig
from veyltrace_causentra.decision import Candidate, Decision
from veyltrace_causentra.inputs import CausentraInputs
from veyltrace_causentra.outcome import asks, labels, proposal_outcomes, ranks_rcaeval
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core.hashing import self_hash


def _ranked(position: int, c: Candidate, d: Decision, inp: CausentraInputs) -> dict[str, Any]:
    lab = labels(c.service, inp)
    return {
        "rank": position,
        "service": c.service,
        "component": lab.component,
        "indicator": lab.indicator,
        "fault_class": lab.fault_class,
        "v": c.v,
        "nonconformity": d.nonconformity[c.service],
        "fused_score": c.fused,
        "origin": c.origin,
        "trials": [t.as_json() for t in c.trials],
    }


def build_verdict(
    *,
    run_id: str,
    inp: CausentraInputs,
    cfg: CausentraConfig,
    d: Decision,
    status: str,
    level: str,
    calibration: dict[str, str],
    params_sha256: str,
) -> dict[str, Any]:
    """The verdict mapping with its verdict_hash (pure; no I/O)."""
    top = d.leader if status != "NO_FAULT" else None
    root = None
    if top is not None:
        lab = labels(top.service, inp)
        root = {"service": top.service, "component": lab.component, "indicator": lab.indicator}
        root |= {"fault_class": lab.fault_class, "mode": lab.mode}
    members = [] if status == "NO_FAULT" else list(d.candidate_set)
    candidate_set = [
        {"service": c.service, "component": labels(c.service, inp).component, "v": c.v}
        | {"nonconformity": d.nonconformity[c.service]}
        for c in members
    ]
    accepted, rejected = proposal_outcomes(d, inp, cfg)
    verdict: dict[str, Any] = {
        "schema_version": CONTRACTS["verdict"].version,
        "case_id": inp.manifest.case_id,
        "run_id": run_id,
        "status": status,
        "root": root,
        "candidate_set": candidate_set,
        "ranked": [_ranked(i, c, d, inp) for i, c in enumerate(d.ranked, start=1)],
        "confidence": {
            "level": level,
            "margin": d.margin,
            "alpha": cfg.alpha,
            "q_hat": inp.q_hat,
            "set_size": len(candidate_set),
        },
        "asks": asks(d, status, inp, cfg),
        "ranks_rcaeval": ranks_rcaeval(d, inp),
        "proposals_accepted": accepted,
        "proposals_rejected": rejected,
        "calibration": calibration,
        "params_sha256": params_sha256,
    }
    verdict["verdict_hash"] = self_hash("verdict", verdict)
    return verdict
