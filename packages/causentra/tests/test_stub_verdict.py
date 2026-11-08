"""Unit tests of the pure R-00 verdict builder (`stub.build_verdict`, `stub.proposal_outcomes`,
`stub.evidence_facts`, `stub.stub_trials`, `stub.stub_asks`)."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from veyltrace_causentra import stub
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.hashing import self_hash, sha256_json
from veyltrace_core.ids import case_id as make_case_id

CASE = make_case_id("synth-01")
RUN_A = "0123456789abcdef"
RUN_B = "fedcba9876543210"
PARAMS = "a" * 64
UNCALIBRATED = {"family": "uncalibrated", "sha256": sha256_json({"family": "uncalibrated"})}
#: The spec defaults the stub reads (09 §4): alpha 0.10, uncalibrated q_hat 0.0, proposals.max 5,
#: status.likely_max_set 3, asks.max 5.
DEFAULTS = stub.StubSettings(alpha=0.10, q_hat=0.0, proposals_max=5, likely_max_set=3, asks_max=5)
#: The R-00 synth inputs: no atom at all, no graph edge, traces and events present.
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
NO_LEADER_ASK = {"kind": "telemetry", "target": "all", "why": "no anomaly evidence in any source"}


def _settings(q_hat: float | None = 0.0, **changes: int) -> stub.StubSettings:
    return dataclasses.replace(DEFAULTS, q_hat=q_hat, **changes)


def _verdict(
    slate: models.Slate,
    *,
    proposals: models.Proposals | None = None,
    nodes: frozenset[str] = frozenset(),
    facts: stub.EvidenceFacts = NO_ATOMS,
    settings: stub.StubSettings = DEFAULTS,
    run_id: str = RUN_A,
) -> dict[str, Any]:
    return stub.build_verdict(
        case_id=CASE,
        run_id=run_id,
        slate=slate,
        proposals=proposals,
        graph_nodes=nodes,
        facts=facts,
        settings=settings,
        calibration=UNCALIBRATED,
        params_sha256=PARAMS,
    )


def _empty_slate() -> models.Slate:
    return models.Slate.model_validate(
        {
            "schema_version": "0.1.0",
            "case_id": CASE,
            "k": 5,
            "rankers_active": [],
            "fusion": {"method": "rrf", "k": 60, "weights": {}},
            "candidates": [],
            "all_scores": [],
        }
    )


def test_every_slate_candidate_is_ranked_in_slate_order_unverified(example_slate: models.Slate) -> None:
    verdict = _verdict(example_slate)
    ranked = verdict["ranked"]
    assert [r["service"] for r in ranked] == [c.service for c in example_slate.candidates]
    assert [r["rank"] for r in ranked] == list(range(1, len(example_slate.candidates) + 1))
    for entry, cand in zip(ranked, example_slate.candidates, strict=True):
        assert entry["component"] == cand.component
        assert entry["indicator"] == cand.indicator
        assert entry["fault_class"] == cand.fault_class
        assert entry["origin"] == "slate"
        assert entry["trials"] == stub.stub_trials(cand.service, NO_ATOMS)
        assert entry["v"] == 0.0
        assert entry["nonconformity"] == 1.0  # 09 §3.7: no leader


def test_fused_score_comes_from_all_scores_and_falls_back_to_the_candidate(
    example_slate: models.Slate,
) -> None:
    by_service = {s.service: s.fused_score for s in example_slate.all_scores}
    verdict = _verdict(example_slate)
    assert {r["service"]: r["fused_score"] for r in verdict["ranked"]} == {
        c.service: by_service[c.service] for c in example_slate.candidates
    }
    first = example_slate.candidates[0]
    trimmed = example_slate.model_copy(
        update={"all_scores": [s for s in example_slate.all_scores if s.service != first.service]}
    )
    assert _verdict(trimmed)["ranked"][0]["fused_score"] == first.fused_score


def test_status_is_inconclusive_without_a_leader(example_slate: models.Slate) -> None:
    for slate in (example_slate, _empty_slate()):
        verdict = _verdict(slate)
        assert verdict["status"] == "INCONCLUSIVE"
        assert verdict["root"] is None
        assert verdict["asks"] == [NO_LEADER_ASK]  # 09 §3.11 priority 6; the set is empty
        conf = verdict["confidence"]
        assert conf["level"] == "none"
        assert conf["margin"] == 0.0
        assert conf["alpha"] == DEFAULTS.alpha


def test_uncalibrated_q_hat_zero_gives_an_empty_set(example_slate: models.Slate) -> None:
    verdict = _verdict(example_slate)
    assert verdict["candidate_set"] == []
    assert verdict["confidence"]["q_hat"] == 0.0
    assert verdict["confidence"]["set_size"] == 0


@pytest.mark.parametrize(("q_hat", "members"), [(None, 5), (1.0, 5), (0.999999999, 0), (0.25, 0)])
def test_candidate_set_follows_s_le_q_hat(
    example_slate: models.Slate, q_hat: float | None, members: int
) -> None:
    verdict = _verdict(example_slate, settings=_settings(q_hat))
    assert len(verdict["candidate_set"]) == members
    assert verdict["confidence"]["set_size"] == members
    assert verdict["confidence"]["q_hat"] == q_hat
    expected = [r["service"] for r in verdict["ranked"]][:members]
    assert [c["service"] for c in verdict["candidate_set"]] == expected


def test_ranks_rcaeval_lists_the_pool_then_the_rest_of_the_universe(example_slate: models.Slate) -> None:
    verdict = _verdict(example_slate)
    pool = [f"{c.service}_{c.indicator}" for c in example_slate.candidates]
    rest = [f"{s.service}_unknown" for s in example_slate.all_scores[len(pool) :]]
    assert verdict["ranks_rcaeval"] == pool + rest
    assert len(set(verdict["ranks_rcaeval"])) == len(verdict["ranks_rcaeval"])


def test_empty_slate_gives_empty_lists() -> None:
    verdict = _verdict(_empty_slate())
    assert verdict["ranked"] == []
    assert verdict["candidate_set"] == []
    assert verdict["ranks_rcaeval"] == []


def test_verdict_hash_is_the_self_hash_and_ignores_run_id(example_slate: models.Slate) -> None:
    a = _verdict(example_slate, run_id=RUN_A)
    b = _verdict(example_slate, run_id=RUN_B)
    assert a["verdict_hash"] == self_hash("verdict", a)
    assert a["verdict_hash"] == b["verdict_hash"]
    assert a["run_id"] != b["run_id"]


@pytest.mark.parametrize("q_hat", [0.0, None])
def test_verdict_passes_the_contract_writer_checks(
    example_slate: models.Slate, example_proposals: models.Proposals, q_hat: float | None
) -> None:
    settings = _settings(q_hat)
    for slate in (example_slate, _empty_slate()):
        verdict = _verdict(
            slate, proposals=example_proposals, nodes=frozenset({"checkout"}), settings=settings
        )
        model = io.prepare("verdict", verdict)  # schema, x-sort orders and self hash
        assert isinstance(model, models.Verdict)


# --- proposal outcomes (09 §3.10 rows 1-2 only) ----------------------------------------------
def test_no_proposals_file_gives_no_outcomes() -> None:
    assert stub.proposal_outcomes(None, frozenset({"checkout"}), 5) == ([], [], 0)


@pytest.mark.parametrize("status", ["failed", "skipped"])
def test_failed_or_skipped_proposals_are_all_rejected_budget(
    example_proposals: models.Proposals, status: str
) -> None:
    proposals = example_proposals.model_copy(update={"status": status})
    accepted, rejected, undecided = stub.proposal_outcomes(proposals, frozenset({"checkout", "redis"}), 5)
    assert accepted == []
    assert undecided == 0
    assert rejected == [
        {"proposal_id": p.proposal_id, "reason": "budget"}
        for p in sorted(proposals.proposals, key=lambda p: p.proposal_id)
    ]


def test_proposals_beyond_max_are_rejected_budget(example_proposals: models.Proposals) -> None:
    ids = sorted(p.proposal_id for p in example_proposals.proposals)
    _accepted, rejected, undecided = stub.proposal_outcomes(
        example_proposals, frozenset({"checkout", "redis"}), 1
    )
    assert rejected == [{"proposal_id": ids[1], "reason": "budget"}]
    assert undecided == 1


def test_unknown_entity_is_rejected_and_known_ones_stay_undecided(
    example_proposals: models.Proposals,
) -> None:
    by_service = {p.hypothesis.service: p.proposal_id for p in example_proposals.proposals}
    accepted, rejected, undecided = stub.proposal_outcomes(example_proposals, frozenset({"checkout"}), 5)
    assert accepted == []  # the stub never accepts: acceptance is a verified claim
    assert rejected == [{"proposal_id": by_service["redis"], "reason": "unknown_entity"}]
    assert undecided == 1


def test_proposals_never_add_a_candidate(
    example_slate: models.Slate, example_proposals: models.Proposals
) -> None:
    nodes = frozenset({"checkout", "redis"})
    with_ai = _verdict(example_slate, proposals=example_proposals, nodes=nodes)
    without = _verdict(example_slate)
    assert with_ai["ranked"] == without["ranked"]
    assert all(r["origin"] == "slate" for r in with_ai["ranked"])


# --- existence facts, untestable trials (09 §3.4) and asks (09 §3.11) ---------------------------
def _atom(candidate: str, kind: str, args: dict[str, Any], origin: str = "engine") -> dict[str, Any]:
    return {"candidate": candidate, "kind": kind, "args_json": json.dumps(args), "origin": origin}


SOURCES = models.Sources(metrics=True, logs=True, traces=True, events=False)


def test_evidence_facts_names_the_services_of_each_atom_sort() -> None:
    rows = [
        _atom("a", "internal_anomaly", {"detector": "robust_z"}),
        _atom("b", "internal_anomaly", {"detector": "nsigma"}),
        _atom("c", "silence", {"window": "incident"}),
        _atom("a", "onset_precedence", {"scope": "self"}),
        _atom("b", "onset_precedence", {"scope": "dependents"}),
        _atom("d", "self_time_share", {"quantile": 0.5}),
        _atom("e", "intervention", {"series_id": "x"}),
        _atom("f", "claim_check", {}, origin="claim_check"),
    ]
    facts = stub.evidence_facts(rows, graph_edges=2, sources=SOURCES)
    assert facts.internal_series == {"a"}  # only the robust_z detector (09 §3.4 T1)
    assert facts.silence == {"c"}
    assert facts.self_onset == {"a"}  # only scope self (T2)
    assert facts.self_time_share == {"d"} and facts.intervention == {"e"}
    assert facts.anomaly_atoms and facts.graph_edges
    assert facts.traces and not facts.events
    assert stub.evidence_facts(list(reversed(rows)), graph_edges=2, sources=SOURCES) == facts


def test_claim_check_atoms_are_no_anomaly_evidence() -> None:
    rows = [_atom("a", "internal_anomaly", {"detector": "robust_z"}, origin="claim_check")]
    facts = stub.evidence_facts(rows, graph_edges=0, sources=SOURCES)
    assert not facts.anomaly_atoms and facts.internal_series == frozenset()


def test_no_atoms_fix_every_untestable_trial_with_its_spec_reason() -> None:
    trials = stub.stub_trials("cart", NO_ATOMS)
    assert [(t["id"], t["reason"]) for t in trials] == [
        ("T1", "no_internal_series"),
        ("T2", "no_onset"),
        ("T3", "no_graph_edges"),
        ("T4", "no_silence_status"),
        ("T5", "no_latency_increase"),
        ("T8", "intervention_unavailable"),
    ]
    assert all(t["result"] == "untestable" and t["atoms"] == [] for t in trials)


def test_trials_whose_precondition_fails_are_left_for_r10() -> None:
    facts = dataclasses.replace(
        NO_ATOMS,
        internal_series=frozenset({"cart"}),
        silence=frozenset({"cart"}),
        self_onset=frozenset({"cart"}),
        self_time_share=frozenset({"cart"}),
        intervention=frozenset({"cart"}),
        anomaly_atoms=True,
        graph_edges=True,
        events=False,
    )
    # Only T6 no_events is a fact here; T1-T5 and T8 need evaluation (R-10/R-12).
    assert [(t["id"], t["reason"]) for t in stub.stub_trials("cart", facts)] == [("T6", "no_events")]
    no_edges = dataclasses.replace(facts, graph_edges=False, traces=False)
    assert [(t["id"], t["reason"]) for t in stub.stub_trials("cart", no_edges)] == [
        ("T3", "no_graph_edges"),
        ("T4", "no_graph_edges"),  # silence atom present, descendants cannot be inspected
        ("T6", "no_events"),
    ]


def test_set_ask_fires_above_likely_max_set_and_asks_are_truncated(example_slate: models.Slate) -> None:
    verdict = _verdict(example_slate, settings=_settings(None))
    first = ",".join(c["service"] for c in verdict["candidate_set"][:3])
    set_ask = {"kind": "trial", "target": f"set:{first}", "why": "candidate set has 5 members"}
    assert verdict["asks"] == [set_ask, NO_LEADER_ASK]  # priority 4 before 6
    assert _verdict(example_slate, settings=_settings(None, likely_max_set=5))["asks"] == [NO_LEADER_ASK]
    assert _verdict(example_slate, settings=_settings(None, asks_max=1))["asks"] == [set_ask]


def test_no_leader_ask_needs_an_evidence_without_anomaly_atoms(example_slate: models.Slate) -> None:
    with_atoms = dataclasses.replace(NO_ATOMS, anomaly_atoms=True)
    assert _verdict(example_slate, facts=with_atoms)["asks"] == []
