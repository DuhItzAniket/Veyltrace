"""Planted decoy proposals, `protocol.inject_proposals` (04 §5.2, §9; H2b; R-16 B4, #399).

"One fabricated proposal per case for a healthy service with false claims" (04 §5.2), `n` per case
drawn with `seed` (04 §9). For each AI-arm run of a case and seed, bench writes the run's recorded
proposals plus `n` planted ones as a derived run (core's `external_proposals`, written at the
relentra step: no model call) that restarts from FaultLoom on the source run's upstream outputs.
It cannot restart later: a finished run's `evidence.parquet` is the claim-pass version, which core
refuses as FaultLoom's main output. The planted run is the row with variant `plant-<n>`; H2b's
`decoy_top1_change` compares its top-1 with the source row's.

A priori choices (04 names none): a **healthy** service is any of the case's services other than
the answer key's root (coarse names; no-fault cases: any), drawn without replacement by numpy's
generator seeded with (seed, case id). Its hypothesis is a CPU fault, and its two claims are false
for a healthy service: its onset precedes the root's (`onset_before`) and its CPU robust z is at
least 3 (`zscore_above`, k = the 3-sigma rule of `core.thresholds.anomaly_z`). FaultLoom's claim
pass evaluates them like any proposal's; whether they hold is measured, never assumed. Proposal ids
follow 08 §2.2 (P + 8 hex of the hypothesis and claims without ids), and the derived proposals are
sorted as 03 §9.1 requires, so they pass the contract writer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from veyltrace_bench.experiment import ProposalDraw
from veyltrace_bench.metrics import coarse_service
from veyltrace_contracts.models import Proposals
from veyltrace_core.context import EXTERNAL_PROPOSALS_MODE
from veyltrace_core.hashing import sha256_json

PLANT = "plant"  # bench_result.variant plant-<n> (03 §13.2: a bench variant of the case run)
RESTART_STEP = "faultloom"  # the last step whose inputs a finished run still holds unchanged
DECOY_FAULT = {"fault_class": "cpu", "indicator": "cpu"}  # a priori: the most common RCAEval fault
ZSCORE_K = 3.0  # a priori: core.thresholds.anomaly_z, the 3-sigma rule (02 §6.3)
RATIONALE = "planted decoy proposal (bench, 04 §5.2 H2b)"


def variant(draw: ProposalDraw) -> str:
    return f"{PLANT}-{draw.n}"


def decoys(services: Sequence[str], root: str | None, case_id: str, draw: ProposalDraw) -> list[str]:
    """`draw.n` healthy services of the case (fewer if it has fewer), in draw order."""
    healthy = sorted(s for s in services if root is None or coarse_service(s) != coarse_service(root))
    gen = np.random.default_rng([draw.seed, int(case_id, 16)])
    picks = gen.choice(len(healthy), size=min(draw.n, len(healthy)), replace=False) if healthy else []
    return [healthy[int(i)] for i in picks]


def _proposal(service: str, root: str | None) -> dict[str, Any]:
    claims: list[dict[str, Any]] = [
        {"predicate": "zscore_above", "args": {"k": ZSCORE_K, "signal": "cpu"}, "cites": []}
    ]
    if root is not None:
        claims.insert(0, {"predicate": "onset_before", "args": {"other_service": root}, "cites": []})
    hypothesis = {"service": service, "component": None, **DECOY_FAULT}
    pid = "P" + sha256_json({"hypothesis": hypothesis, "claims": claims})[:8]
    numbered = [{"claim_id": f"{pid}-{i}", **c} for i, c in enumerate(claims, 1)]
    fields = {"proposal_id": pid, "hypothesis": hypothesis, "claims": numbered}
    return fields | {"requested_trials": [], "rationale": RATIONALE}


def planted(
    recorded: Proposals, services: Sequence[str], root: str | None, draw: ProposalDraw
) -> dict[str, Any]:
    """The derived run's proposals: the recorded ones plus the planted, as external proposals."""
    base = recorded.model_dump(mode="json")
    added = [_proposal(s, root) for s in decoys(services, root, recorded.case_id, draw)]
    every = [*base["proposals"], *added]
    every.sort(key=lambda p: (p["hypothesis"]["service"], p["hypothesis"]["fault_class"], p["proposal_id"]))
    return base | {"mode": EXTERNAL_PROPOSALS_MODE, "model": None, "status": "complete", "proposals": every}
