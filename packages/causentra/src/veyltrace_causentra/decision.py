"""Decision steps 1–3, 6 and the uncalibrated set of 09 §3.2–§3.7.

Step 1: the decision pool is the slate plus the services of admitted proposals (a supporting claim
that code found true for that service). Step 2: S0 = fused score / pool maximum. Step 3:
V = S0 × Π trial factors × (1 + clip(Σ w·polarity·holds)), rounded to 9 decimals before any
comparison. Step 6: order by (−V9, internal-first, earliest onset, name); the leader is the first
candidate if its V9 > 0. Nonconformity s = 1 − V9 / V9(leader) and the set {s ≤ q̂} follow
(uncalibrated q̂ = 0 keeps the leader and exact ties). Everything is a function of sets, sorted
before use, so proposal and claim order never matter (09 §5).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from veyltrace_causentra.config import CausentraConfig
from veyltrace_causentra.inputs import DECIMALS, CausentraInputs, Claim
from veyltrace_causentra.trials import FAIL, PASS, TrialResult, run_trials, trial_inputs
from veyltrace_contracts import models
from veyltrace_contracts.predicates import PREDICATES
from veyltrace_core.canonical import canonical_json_str

SLATE: Final = "slate"
PROPOSAL: Final = "proposal"
#: proposals.status values whose proposals may enter the decision pool (09 §3.2).
ELIGIBLE: Final = frozenset({"complete", "budget_exhausted"})
_POLARITY: Final = {p.name: (1.0 if p.polarity == "supports" else -1.0) for p in PREDICATES}


@dataclass(frozen=True)
class Candidate:
    """One decision-pool candidate after steps 2–3 (V is V9, already rounded)."""

    service: str
    origin: str
    fused: float
    s0: float
    trials: tuple[TrialResult, ...]
    v: float


@dataclass(frozen=True)
class Decision:
    """The ordered pool, its leader, nonconformity per service, the set C, and the margin m."""

    ranked: tuple[Candidate, ...]
    leader: Candidate | None
    nonconformity: dict[str, float]
    candidate_set: tuple[Candidate, ...]
    margin: float
    admitted: frozenset[str]


def eligible_proposals(proposals: models.Proposals | None, cfg: CausentraConfig) -> list[models.Proposal]:
    """The first `proposals.max` proposals by proposal_id, if the run's status allows any (09 §3.2)."""
    if proposals is None or proposals.status not in ELIGIBLE:
        return []
    return sorted(proposals.proposals, key=lambda p: p.proposal_id)[: cfg.proposals_max]


def claim_holds(claims: Iterable[Claim], service: str, claim: models.Claim) -> bool | None:
    """`holds` of the claim_check atom of (predicate, canonical args) for `service`; None if absent."""
    args = canonical_json_str(dict(claim.args))
    found = [
        c.holds
        for c in claims
        if c.candidate == service and c.predicate == claim.predicate and c.args_json == args
    ]
    return found[0] if found else None


def admitted(inp: CausentraInputs, cfg: CausentraConfig) -> dict[str, str]:
    """proposal_id → service of every admitted proposal (09 §3.2 conditions 1–2)."""
    out: dict[str, str] = {}
    for p in eligible_proposals(inp.proposals, cfg):
        service = p.hypothesis.service
        supported = any(
            _POLARITY.get(c.predicate) == 1.0 and claim_holds(inp.claims, service, c) is True
            for c in p.claims
        )
        if service in inp.graph_nodes and supported:
            out[p.proposal_id] = service
    return out


def claim_sum(service: str, claims: Iterable[Claim], cfg: CausentraConfig) -> float:
    """clip(Σ w_p · polarity_p · holds_p(c)) over c's distinct claim-pass pairs (09 §3.5)."""
    weights = dict(cfg.weights)
    terms = sorted(
        weights[c.predicate] * _POLARITY[c.predicate]
        for c in claims
        if c.candidate == service and c.holds is True and c.predicate in weights
    )
    return min(max(math.fsum(terms), cfg.clip_low), cfg.clip_high)


def trial_factor(trials: Iterable[TrialResult], cfg: CausentraConfig) -> float:
    """Π factor over the written trials; a `trials.disabled` trial counts 1 (09 §3.5, §9)."""
    f, product = cfg.factors, 1.0
    for t in trials:
        if t.id in cfg.disabled:
            continue
        mandatory = t.id in cfg.mandatory
        if t.result == PASS:
            product *= f.passed
        elif t.result == FAIL:
            product *= f.fail_mandatory if mandatory else f.fail_supporting
        else:
            product *= f.untestable_mandatory if mandatory else f.untestable_supporting
    return product


def verified(s0: float, trials: Iterable[TrialResult], csum: float, cfg: CausentraConfig) -> float:
    """V9 = round(S0 × Π factor × (1 + clipped claim sum), 9) (09 §3.5)."""
    return round(s0 * trial_factor(trials, cfg) * (1.0 + csum), DECIMALS)


def decide(inp: CausentraInputs, cfg: CausentraConfig) -> Decision:
    """Steps 1–3 and 6, nonconformity and the set C at the run's q̂ (09 §3.2–§3.7)."""
    proposed = admitted(inp, cfg)
    slate_services = {c.service for c in inp.slate.candidates}
    origins = {s: SLATE for s in slate_services} | {
        s: PROPOSAL for s in proposed.values() if s not in slate_services
    }
    fused = {s.service: s.fused_score for s in inp.slate.all_scores}
    top = max((fused.get(s, 0.0) for s in origins), default=0.0)
    t_in = trial_inputs(inp, cfg)
    pool: list[Candidate] = []
    for service in sorted(origins):
        s0 = fused.get(service, 0.0) / top if top > 0 else 0.0
        trials = run_trials(service, t_in)
        v = verified(s0, trials, claim_sum(service, inp.claims, cfg), cfg)
        pool.append(Candidate(service, origins[service], fused.get(service, 0.0), s0, trials, v))

    def key(c: Candidate) -> tuple[float, int, float, str]:
        f = inp.ev.of(c.service)
        return (-c.v, 0 if f.internal >= cfg.k_anom else 1, f.onset_ms, c.service)

    ranked = tuple(sorted(pool, key=key))
    leader = ranked[0] if ranked and ranked[0].v > 0 else None
    s = {c.service: round(1.0 - c.v / leader.v, DECIMALS) if leader else 1.0 for c in ranked}
    members = [c for c in ranked if inp.q_hat is None or s[c.service] <= inp.q_hat]
    runner_up = s[ranked[1].service] if len(ranked) > 1 else 1.0  # m = s(runner-up), 1.0 without one
    margin = runner_up if leader is not None else 0.0
    return Decision(
        ranked=ranked,
        leader=leader,
        nonconformity=s,
        candidate_set=tuple(sorted(members, key=lambda c: -c.v)),  # stable: ties keep ranked order
        margin=margin,
        admitted=frozenset(proposed),
    )
