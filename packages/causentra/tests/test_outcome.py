"""Tests of step 5, asks, proposal outcomes and ranks_rcaeval (09 §3.8–§3.12, the §3.14 asks)."""

from __future__ import annotations

import itertools
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from veyltrace_causatrix.views import Atom, evidence_view, graph_view
from veyltrace_causentra.config import config_from
from veyltrace_causentra.decision import Candidate, Decision, decide
from veyltrace_causentra.inputs import CausentraInputs, Claim, load_inputs
from veyltrace_causentra.outcome import asks, labels, no_fault, proposal_outcomes, ranks_rcaeval, status_of
from veyltrace_causentra.trials import TrialResult
from veyltrace_contracts import models
from veyltrace_core.config import load_section_file
from veyltrace_core.testing import make_context

CFG = config_from(load_section_file("causentra"), load_section_file("core"))
CASE = "59e0d31bcc42"
_IDS = itertools.count(1)
OK4 = tuple(TrialResult(t, "pass", None, ()) for t in ("T1", "T2", "T3", "T4"))


def _c(service: str, v: float, trials: tuple[TrialResult, ...] = OK4) -> Candidate:
    return Candidate(service, "slate", v, v, trials, v)


def _d(ranked: list[Candidate], members: int, margin: float) -> Decision:
    s = {c.service: 0.0 for c in ranked}
    return Decision(
        tuple(ranked),
        ranked[0] if ranked and ranked[0].v > 0 else None,
        s,
        tuple(ranked[:members]),
        margin,
        frozenset(),
    )


def test_status_rules_in_order() -> None:
    a, b = _c("a", 1.0), _c("b", 0.6)
    assert status_of(_d([a, b], 1, 0.4), True, CFG) == ("NO_FAULT", "none")
    assert status_of(_d([a, b], 1, 0.30), False, CFG) == ("CONFIRMED", "high")
    assert status_of(_d([a, b], 1, 0.2), False, CFG) == ("LIKELY", "medium")
    assert status_of(_d([a, b], 3, 0.15), False, CFG) == ("LIKELY", "medium")
    assert status_of(_d([a, b, _c("c", 0.5), _c("d", 0.5)], 4, 0.4), False, CFG) == ("INCONCLUSIVE", "low")
    assert status_of(_d([a, b], 1, 0.14), False, CFG) == ("INCONCLUSIVE", "low")
    unsure = _c("a", 1.0, (*OK4[:1], TrialResult("T2", "untestable", "no_onset", ()), *OK4[2:]))
    assert status_of(_d([unsure, b], 1, 1.0), False, CFG) == (
        "INCONCLUSIVE",
        "low",
    )  # untestable is not a pass
    assert status_of(_d([unsure, b], 1, 1.0), False, replace(CFG, disabled=("T2",)))[0] == "CONFIRMED"
    assert status_of(_d([_c("a", 0.0)], 0, 0.0), False, CFG) == ("INCONCLUSIVE", "none")


@pytest.fixture
def base(synth01_dir: Path) -> CausentraInputs:
    ctx = make_context("causentra", synth01_dir)
    return load_inputs(ctx, config_from(ctx.config, ctx.config.core))


def _z(cand: str, kind: str, z: float) -> Atom:
    args = {"detector": "robust_z", "family": "latency", "source": "traces", "window": "incident"}
    return Atom(f"E{next(_IDS):010x}", cand, None, kind, args, z)


def _with(base: CausentraInputs, atoms: list[Atom], **changes: Any) -> CausentraInputs:
    members = ["a", "b", "c"]
    return replace(
        base,
        ev=evidence_view(atoms, members),
        graph=graph_view(members, [], [], include_external=False),
        **changes,
    )


def test_09_3_14_asks(base: CausentraInputs) -> None:
    trials = (
        *OK4,
        TrialResult("T6", "untestable", "no_events", ()),
        TrialResult("T8", "untestable", "intervention_unavailable", ()),
    )
    a, b = _c("a", 1.1, trials), _c("b", 0.8625)
    inp = _with(base, [_z("a", "internal_anomaly", 9.0)])
    on = _d([a, b], 2, 0.215909091)
    assert asks(on, "LIKELY", inp, CFG) == [
        {"kind": "telemetry", "target": "events", "why": "T6 untestable without events"}
    ]
    off = _d([replace(a, v=1.0), replace(b, v=0.8625)], 2, 0.1375)
    assert asks(off, "INCONCLUSIVE", inp, CFG) == [
        {"kind": "telemetry", "target": "events", "why": "T6 untestable without events"},
        {"kind": "context", "target": "b", "why": "runner-up within margin 0.1375"},
    ]
    assert asks(on, "CONFIRMED", inp, CFG) == [] and asks(on, "NO_FAULT", inp, CFG) == []


def test_ask_priorities_and_truncation(base: CausentraInputs) -> None:
    bad = (
        TrialResult("T1", "fail", "no_internal_anomaly", ()),
        TrialResult("T2", "untestable", "no_onset", ()),
        *OK4[2:],
    )
    four = [_c("a", 1.0, bad), _c("b", 0.9), _c("c", 0.9), _c("d", 0.9)]
    got = asks(_d(four, 4, 0.1), "INCONCLUSIVE", _with(base, [_z("a", "internal_anomaly", 9.0)]), CFG)
    assert [(x["kind"], x["target"]) for x in got] == [
        ("trial", "T1:a"),
        ("trial", "T2:a"),
        ("trial", "set:a,b,c"),
        ("context", "b"),
    ]
    assert got[0]["why"] == "mandatory trial T1 failed: no_internal_anomaly"
    assert got[1]["why"] == "mandatory trial T2 untestable: no_onset"
    assert len(asks(_d(four, 4, 0.1), "INCONCLUSIVE", base, replace(CFG, asks_max=2))) == 2
    quiet = asks(_d(four, 4, 0.1), "INCONCLUSIVE", base, replace(CFG, disabled=("T1", "T2")))
    assert [x["target"] for x in quiet] == ["set:a,b,c", "b"]  # disabled trials raise no ask


def test_no_evidence_ask_uses_values_not_atom_existence(base: CausentraInputs) -> None:
    empty = _d([], 0, 0.0)
    no_ask = {"kind": "telemetry", "target": "all", "why": "no anomaly evidence in any source"}
    assert asks(empty, "INCONCLUSIVE", _with(base, []), CFG) == [no_ask]
    healthy = [
        _z(s, "internal_anomaly", 0.0) for s in ("a", "b", "c")
    ]  # R-06: healthy atoms are not evidence
    assert asks(empty, "INCONCLUSIVE", _with(base, healthy), CFG) == [no_ask]
    assert asks(empty, "INCONCLUSIVE", _with(base, [*healthy, _z("b", "external_anomaly", 3.0)]), CFG) == []


def test_no_fault_statistic(base: CausentraInputs) -> None:
    def nf(atoms: list[Atom]) -> bool:
        return no_fault(_with(base, atoms, entry_services=("a",)))

    assert not nf([])  # no robust_z atom: M is undefined, never NO_FAULT
    assert nf([_z("a", "external_anomaly", 3.0), _z("b", "internal_anomaly", 1.0)])  # log1p(3) <= tau
    assert not nf([_z("a", "external_anomaly", 3.1)])
    assert nf([_z("a", "internal_anomaly", 0.5), _z("b", "external_anomaly", 10.0)])  # b is not an entry
    assert not nf([_z("a", "internal_anomaly", 0.5), _z("c", "internal_anomaly", 3.5)])
    silent = Atom(f"E{next(_IDS):010x}", "c", None, "silence", {"window": "incident"}, 1.0)
    assert not nf([_z("a", "internal_anomaly", 0.5), silent])


def _slate(scores: dict[str, float], k: int) -> models.Slate:
    order = sorted(scores, key=lambda s: (-round(scores[s], 9), s))
    base = {
        "component": None,
        "indicator": "cpu",
        "mode": "resource",
        "fault_class": "cpu",
        "ranker_ranks": {},
    }
    cands = [
        {**base, "rank": i, "service": s, "fused_score": scores[s], "ranker_scores": {}}
        for i, s in enumerate(order[:k], 1)
    ]
    fusion = {"method": "rrf", "k": 60, "weights": {"prism_m": 1.0}}
    all_scores = [{"service": s, "fused_score": scores[s]} for s in order]
    return models.Slate.model_validate(
        {"schema_version": "0.1.0", "case_id": CASE, "k": k, "rankers_active": ["prism_m"], "fusion": fusion}
        | {"candidates": cands, "all_scores": all_scores}
    )


def _proposals(status: str, *specs: tuple[str, str]) -> models.Proposals:
    items = [
        {
            "proposal_id": pid,
            "hypothesis": {"service": svc, "component": None, "fault_class": "cpu", "indicator": None},
            "claims": [{"claim_id": f"{pid}-1", "predicate": "silent", "args": {}, "cites": []}],
            "requested_trials": [],
            "rationale": "",
        }
        for pid, svc in specs
    ]
    budget = {"turns": 1, "tokens_in": 1, "tokens_out": 1, "wall_ms": 1.0}
    return models.Proposals.model_validate(
        {"schema_version": "0.1.0", "case_id": CASE, "status": status, "mode": "external", "model": None}
        | {"budget_used": budget, "proposals": items, "asks": []}
    )


def test_proposal_outcomes_and_ranks(base: CausentraInputs) -> None:
    holds = (Claim("E00000000a1", "b", "silent", "{}", True), Claim("E00000000a2", "c", "silent", "{}", True))
    specs = [
        ("P00000001", "c"),
        ("P00000002", "zz"),
        ("P00000003", "a"),
        ("P00000004", "b"),
        ("P00000005", "c"),
    ]
    atoms = [
        _z("a", "internal_anomaly", 9.0),
        _z("b", "internal_anomaly", 1.0),
        _z("c", "internal_anomaly", 5.0),
    ]
    inp = _with(base, atoms, slate=_slate({"a": 0.05, "b": 0.04, "c": 0.01}, 1))
    inp = replace(
        inp, claims=holds, graph_nodes=frozenset({"a", "b", "c"}), proposals=_proposals("complete", *specs)
    )
    d = decide(inp, replace(CFG, proposals_max=4))
    accepted, rejected = proposal_outcomes(d, inp, replace(CFG, proposals_max=4))
    # c passes T1 (z 5) and is accepted; b (z 1) is admitted but fails the mandatory T1.
    assert accepted == ["P00000001"] and rejected == [
        {"proposal_id": "P00000002", "reason": "unknown_entity"},
        {"proposal_id": "P00000003", "reason": "claim_false"},
        {"proposal_id": "P00000004", "reason": "trial_failed"},
        {"proposal_id": "P00000005", "reason": "budget"},
    ]
    skipped = replace(inp, proposals=_proposals("failed", *specs[:1]))
    assert proposal_outcomes(d, skipped, CFG) == ([], [{"proposal_id": "P00000001", "reason": "budget"}])
    assert labels("a", inp).indicator == "cpu"  # slate label
    assert (labels("b", inp).indicator, labels("c", inp).indicator) == ("unknown", "latency")  # classify()
    assert ranks_rcaeval(d, inp)[: len(d.ranked)] == [
        f"{c.service}_{labels(c.service, inp).indicator}" for c in d.ranked
    ]
    assert sorted(r.split("_")[0] for r in ranks_rcaeval(d, inp)) == ["a", "b", "c"]
