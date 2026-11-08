"""Property tests of the R-00 verdict builder (09 §7 "AI cannot remove", order invariance)."""

from __future__ import annotations

import json
import re
from typing import Any, get_args

from hypothesis import given
from hypothesis import strategies as st

from veyltrace_causentra import stub
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.hashing import sha256_json
from veyltrace_core.ids import case_id as make_case_id

CASE = make_case_id("synth-01")
RUN = "0123456789abcdef"
UNCALIBRATED = {"family": "uncalibrated", "sha256": sha256_json({"family": "uncalibrated"})}
INDICATORS: tuple[str, ...] = get_args(models.Indicator)
FAULT_CLASSES: tuple[str, ...] = get_args(models.FaultClass)
MODES: tuple[str, ...] = get_args(models.Mode)
SERVICES = st.from_regex(r"\A[a-z][a-z0-9-]{0,7}\Z")
SCORES = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
TRIAL_IDS: tuple[str, ...] = get_args(models.TrialId)
#: verdict.ranked[].trials[].reason pattern (contracts/schemas/verdict.schema.json).
REASON = re.compile(r"^[a-z_]+(:[A-Za-z0-9_.,-]+)?$")
KINDS = st.sampled_from(
    [
        "internal_anomaly",
        "external_anomaly",
        "onset_precedence",
        "silence",
        "self_time_share",
        "intervention",
        "propagation",
        "claim_check",
    ]
)


@st.composite
def facts_of(draw: st.DrawFn, services: list[str]) -> stub.EvidenceFacts:
    def subset() -> frozenset[str]:
        return frozenset(draw(st.lists(st.sampled_from(services)))) if services else frozenset()

    return stub.EvidenceFacts(
        internal_series=subset(),
        silence=subset(),
        self_onset=subset(),
        self_time_share=subset(),
        intervention=subset(),
        anomaly_atoms=draw(st.booleans()),
        graph_edges=draw(st.booleans()),
        traces=draw(st.booleans()),
        events=draw(st.booleans()),
    )


@st.composite
def slates(draw: st.DrawFn) -> models.Slate:
    universe = draw(st.lists(SERVICES, min_size=0, max_size=8, unique=True))
    k = draw(st.integers(min_value=1, max_value=6))
    scores = [{"service": s, "fused_score": round(draw(SCORES), 9)} for s in universe]
    scores.sort(key=lambda s: (-s["fused_score"], s["service"]))
    top = scores[:k]
    candidates = [
        {
            "rank": i,
            "service": s["service"],
            "component": None,
            "indicator": draw(st.sampled_from(INDICATORS)),
            "mode": draw(st.sampled_from(MODES)),
            "fault_class": draw(st.sampled_from(FAULT_CLASSES)),
            "fused_score": s["fused_score"],
            "ranker_ranks": {},
            "ranker_scores": {},
        }
        for i, s in enumerate(top, start=1)
    ]
    return models.Slate.model_validate(
        {
            "schema_version": "0.1.0",
            "case_id": CASE,
            "k": k,
            "rankers_active": [],
            "fusion": {"method": "rrf", "k": 60, "weights": {}},
            "candidates": candidates,
            "all_scores": scores,
        }
    )


@st.composite
def proposal_sets(draw: st.DrawFn, services: list[str]) -> models.Proposals:
    names = services + draw(st.lists(SERVICES, max_size=2))
    ids = draw(st.lists(st.from_regex(r"\AP[0-9a-f]{8}\Z"), max_size=7, unique=True))
    proposals = [
        {
            "proposal_id": pid,
            "hypothesis": {
                "service": draw(st.sampled_from(names)) if names else "svc",
                "component": None,
                "fault_class": "cpu",
                "indicator": None,
            },
            "claims": [],
            "requested_trials": [],
            "rationale": "",
        }
        for pid in ids
    ]
    return models.Proposals.model_validate(
        {
            "schema_version": "0.1.0",
            "case_id": CASE,
            "status": draw(st.sampled_from(["complete", "budget_exhausted", "failed", "skipped"])),
            "mode": "brief",
            "model": None,
            "budget_used": {"turns": 0, "tokens_in": 0, "tokens_out": 0, "wall_ms": 0.0},
            "proposals": proposals,
            "asks": [],
        }
    )


NO_ATOMS = stub.EvidenceFacts(
    internal_series=frozenset(),
    silence=frozenset(),
    self_onset=frozenset(),
    self_time_share=frozenset(),
    intervention=frozenset(),
    anomaly_atoms=False,
    graph_edges=False,
    traces=True,
    events=True,
)


def _build(
    slate: models.Slate,
    proposals: models.Proposals | None,
    nodes: frozenset[str],
    q_hat: float | None,
    facts: stub.EvidenceFacts = NO_ATOMS,
    asks_max: int = 5,
) -> dict[str, Any]:
    return stub.build_verdict(
        case_id=CASE,
        run_id=RUN,
        slate=slate,
        proposals=proposals,
        graph_nodes=nodes,
        facts=facts,
        settings=stub.StubSettings(
            alpha=0.10, q_hat=q_hat, proposals_max=5, likely_max_set=3, asks_max=asks_max
        ),
        calibration=UNCALIBRATED,
        params_sha256="b" * 64,
    )


@given(data=st.data(), slate=slates(), q_hat=st.one_of(st.none(), SCORES))
def test_ranked_keeps_every_slate_candidate_in_order_whatever_the_proposals(
    data: st.DataObject, slate: models.Slate, q_hat: float | None
) -> None:
    services = [c.service for c in slate.candidates]
    proposals = data.draw(st.one_of(st.none(), proposal_sets(services)))
    nodes = frozenset(data.draw(st.lists(st.sampled_from(services))) if services else [])
    verdict = _build(slate, proposals, nodes, q_hat)
    assert [r["service"] for r in verdict["ranked"]] == services
    assert [r["rank"] for r in verdict["ranked"]] == list(range(1, len(services) + 1))
    assert verdict["status"] == "INCONCLUSIVE" and verdict["root"] is None
    assert verdict["confidence"]["set_size"] == len(verdict["candidate_set"])
    universe = [s.service for s in slate.all_scores]
    assert sorted(entry.rsplit("_", 1)[0] for entry in verdict["ranks_rcaeval"]) == sorted(universe)
    io.prepare("verdict", verdict)  # always contract-valid


@given(data=st.data(), slate=slates())
def test_verdict_is_invariant_to_input_row_order(data: st.DataObject, slate: models.Slate) -> None:
    services = [c.service for c in slate.candidates]
    proposals = data.draw(proposal_sets(services))
    nodes = list(services)
    base = _build(slate, proposals, frozenset(nodes), 0.0)
    shuffled_slate = slate.model_copy(
        update={
            "candidates": data.draw(st.permutations(slate.candidates)),
            "all_scores": data.draw(st.permutations(slate.all_scores)),
        }
    )
    shuffled_props = proposals.model_copy(
        update={"proposals": data.draw(st.permutations(proposals.proposals))}
    )
    again = _build(shuffled_slate, shuffled_props, frozenset(data.draw(st.permutations(nodes))), 0.0)
    assert again["verdict_hash"] == base["verdict_hash"]
    assert again == base


@given(data=st.data(), slate=slates())
def test_each_proposal_gets_at_most_one_outcome_and_none_is_accepted(
    data: st.DataObject, slate: models.Slate
) -> None:
    services = [c.service for c in slate.candidates]
    proposals = data.draw(proposal_sets(services))
    nodes = frozenset(services)
    accepted, rejected, undecided = stub.proposal_outcomes(proposals, nodes, 5)
    ids = [r["proposal_id"] for r in rejected]
    assert accepted == []
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids)
    assert len(ids) + undecided == len(proposals.proposals)


@given(data=st.data(), slate=slates(), q_hat=st.one_of(st.none(), SCORES))
def test_trials_are_untestable_in_id_order_and_asks_bounded(
    data: st.DataObject, slate: models.Slate, q_hat: float | None
) -> None:
    services = [c.service for c in slate.candidates]
    facts = data.draw(facts_of(services))
    asks_max = data.draw(st.integers(min_value=0, max_value=5))
    verdict = _build(slate, None, frozenset(services), q_hat, facts, asks_max)
    for entry in verdict["ranked"]:
        ids = [t["id"] for t in entry["trials"]]
        assert ids == sorted(ids, key=TRIAL_IDS.index) and len(ids) == len(set(ids))
        assert set(ids) <= {"T1", "T2", "T3", "T4", "T5", "T6", "T8"}  # T7, T9, T10 need evaluation
        assert facts.traces or "T5" not in ids  # T5 applies only with traces (09 §3.4)
        assert all(t["result"] == "untestable" and REASON.match(t["reason"]) for t in entry["trials"])
    assert len(verdict["asks"]) <= asks_max
    io.prepare("verdict", verdict)


@given(data=st.data())
def test_evidence_facts_are_invariant_to_row_order(data: st.DataObject) -> None:
    services = data.draw(st.lists(SERVICES, min_size=1, max_size=4, unique=True))
    rows = [
        {
            "candidate": data.draw(st.sampled_from(services)),
            "kind": data.draw(KINDS),
            "args_json": json.dumps(
                {
                    "detector": data.draw(st.sampled_from(["robust_z", "nsigma"])),
                    "scope": data.draw(st.sampled_from(["self", "dependents"])),
                }
            ),
            "origin": data.draw(st.sampled_from(["engine", "claim_check"])),
        }
        for _ in range(data.draw(st.integers(min_value=0, max_value=12)))
    ]
    sources = models.Sources(metrics=True, logs=True, traces=True, events=True)
    base = stub.evidence_facts(rows, graph_edges=1, sources=sources)
    assert stub.evidence_facts(data.draw(st.permutations(rows)), graph_edges=1, sources=sources) == base
