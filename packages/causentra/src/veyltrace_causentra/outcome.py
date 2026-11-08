"""Decision step 5 and the verdict fields derived from it (09 §3.8–§3.12).

Status rules apply in order: NO_FAULT, CONFIRMED, LIKELY, else INCONCLUSIVE, with the fixed margins
c_high = 0.30 and c_med = 0.15 (02 §6.9). Asks come from a fixed template table, never from the
proposer. Every proposal gets exactly one outcome, checked in the 09 §3.10 order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from veyltrace_causatrix.classify import classify
from veyltrace_causentra.config import CausentraConfig
from veyltrace_causentra.decision import Candidate, Decision, eligible_proposals
from veyltrace_causentra.inputs import DECIMALS, CausentraInputs
from veyltrace_causentra.trials import FAIL, PASS, UNTESTABLE
from veyltrace_contracts.predicates import PREDICATES

#: Untestable reasons that mean "a telemetry source is absent" (09 §3.11 priority 2).
SOURCE_OF_REASON: Final = {"no_events": "events"}
NO_EVIDENCE_WHY: Final = "no anomaly evidence in any source"
_LIBRARY: Final = frozenset(p.name for p in PREDICATES)


@dataclass(frozen=True)
class Labels:
    """A candidate's component, indicator, fault_class and mode (from the slate, else classify())."""

    component: str | None
    indicator: str
    fault_class: str
    mode: str


def labels(service: str, inp: CausentraInputs) -> Labels:
    """Slate candidates keep the slate's labels; others are classified by code (09 §3.9, §3.12)."""
    for c in inp.slate.candidates:
        if c.service == service:
            return Labels(c.component, c.indicator, c.fault_class, c.mode)
    got = classify(service, inp.ev, inp.graph, inp.causatrix)
    return Labels(got.component, got.indicator, got.fault_class, got.mode)


def no_fault(inp: CausentraInputs) -> bool:
    """09 §3.8: no silent service and M = log1p(max(E(entry), I(s))) ≤ τ_nf, from robust_z atoms.

    M is a maximum over robust_z atoms, so it is undefined without any: a case with no robust_z
    anomaly atom is never NO_FAULT (missing telemetry is not health, 02 §9).
    """
    services = inp.ev.universe
    if not inp.ev.has_robust_z or any(inp.ev.of(s).silent == 1.0 for s in services):
        return False
    entry = [inp.ev.of(e).external for e in inp.entry_services if e in services]
    stat = math.log1p(max([*entry, *(inp.ev.of(s).internal for s in services)], default=0.0))
    return round(stat, DECIMALS) <= round(inp.tau_nf, DECIMALS)


def mandatory_ok(c: Candidate, cfg: CausentraConfig) -> bool:
    """Every mandatory trial of c passed (untestable is not a pass); disabled trials do not count."""
    return all(t.result == PASS for t in c.trials if t.id in cfg.mandatory and t.id not in cfg.disabled)


def status_of(d: Decision, nf: bool, cfg: CausentraConfig) -> tuple[str, str]:
    """(status, confidence.level) by the 09 §3.9 rules, first match wins."""
    if nf:
        return "NO_FAULT", "none"
    top, size = d.leader, len(d.candidate_set)
    if top is not None and mandatory_ok(top, cfg):
        if size == 1 and d.margin >= round(cfg.c_high, DECIMALS):
            return "CONFIRMED", "high"
        if size <= cfg.likely_max_set and d.margin >= round(cfg.c_med, DECIMALS):
            return "LIKELY", "medium"
    return "INCONCLUSIVE", "low" if top is not None else "none"


def anomalous_evidence(inp: CausentraInputs, cfg: CausentraConfig) -> bool:
    """Some service shows anomaly by value: I, E or NS ≥ k_anom, or Sil = 1 (healthy 0.0 atoms do not)."""
    return any(
        max(f.internal, f.external, f.nsigma) >= cfg.k_anom or f.silent == 1.0
        for f in (inp.ev.of(s) for s in inp.ev.universe)
    )


def asks(d: Decision, status: str, inp: CausentraInputs, cfg: CausentraConfig) -> list[dict[str, str]]:
    """The 09 §3.11 asks of a LIKELY or INCONCLUSIVE verdict: sorted, de-duplicated, truncated."""
    if status not in ("LIKELY", "INCONCLUSIVE"):
        return []
    found: set[tuple[int, str, str, str]] = set()
    top = d.leader
    if top is not None:
        for t in (t for t in top.trials if t.id not in cfg.disabled):
            mandatory = t.id in cfg.mandatory
            if t.result == FAIL and mandatory:
                found.add((1, "trial", f"{t.id}:{top.service}", f"mandatory trial {t.id} failed: {t.reason}"))
            elif t.result == UNTESTABLE and t.reason in SOURCE_OF_REASON:
                source = SOURCE_OF_REASON[t.reason]
                found.add((2, "telemetry", source, f"{t.id} untestable without {source}"))
            elif t.result == UNTESTABLE and mandatory:
                found.add(
                    (3, "trial", f"{t.id}:{top.service}", f"mandatory trial {t.id} untestable: {t.reason}")
                )
        if len(d.ranked) >= 2 and d.margin < round(cfg.c_med, DECIMALS):
            found.add((5, "context", d.ranked[1].service, f"runner-up within margin {d.margin}"))
    if len(d.candidate_set) > cfg.likely_max_set:
        first = ",".join(c.service for c in d.candidate_set[:3])
        found.add((4, "trial", f"set:{first}", f"candidate set has {len(d.candidate_set)} members"))
    if top is None and not anomalous_evidence(inp, cfg):
        found.add((6, "telemetry", "all", NO_EVIDENCE_WHY))
    return [{"kind": k, "target": t, "why": w} for _, k, t, w in sorted(found)[: cfg.asks_max]]


def proposal_outcomes(
    d: Decision, inp: CausentraInputs, cfg: CausentraConfig
) -> tuple[list[str], list[dict[str, str]]]:
    """(accepted ids, rejected {proposal_id, reason}) in the 09 §3.10 order, sorted by proposal_id.

    `bad_args` needs FaultLoom's validate() and is not decided yet: such a proposal, never admitted,
    is rejected `claim_false` (a decision for the lead until validate() is importable).
    """
    if inp.proposals is None:
        return [], []
    eligible = {p.proposal_id for p in eligible_proposals(inp.proposals, cfg)}
    mandatory = set(cfg.mandatory) - set(cfg.disabled)
    failed = {c.service for c in d.ranked if any(t.result == FAIL and t.id in mandatory for t in c.trials)}
    accepted: list[str] = []
    rejected: list[dict[str, str]] = []
    for p in sorted(inp.proposals.proposals, key=lambda p: p.proposal_id):
        if p.proposal_id not in eligible:
            reason = "budget"
        elif p.hypothesis.service not in inp.graph_nodes:
            reason = "unknown_entity"
        elif p.proposal_id not in d.admitted:
            reason = (
                "unknown_predicate" if any(c.predicate not in _LIBRARY for c in p.claims) else "claim_false"
            )
        elif p.hypothesis.service in failed:
            reason = "trial_failed"
        else:
            accepted.append(p.proposal_id)
            continue
        rejected.append({"proposal_id": p.proposal_id, "reason": reason})
    return accepted, rejected


def ranks_rcaeval(d: Decision, inp: CausentraInputs) -> list[str]:
    """`{service}_{indicator}`: the pool in ranked order, then the rest of all_scores (09 §3.12)."""
    order = [c.service for c in d.ranked]
    order += [
        s.service
        for s in sorted(inp.slate.all_scores, key=lambda s: (-round(s.fused_score, DECIMALS), s.service))
    ]
    seen: dict[str, None] = dict.fromkeys(order)
    return [f"{s}_{labels(s, inp).indicator}" for s in seen]
