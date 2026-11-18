"""Normalising checked proposals (08 §3.6; 03 §9.1)."""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io
from veyltrace_core.canonical import canonical_json
from veyltrace_relentra.normalize import normalize_asks, normalize_proposals
from veyltrace_relentra.reply import CheckedAsk, CheckedClaim, CheckedProposal
from veyltrace_relentra.settings import brief_settings

SETTINGS = brief_settings(
    {
        "brief": {"max_proposals": 3},
        "budget": {"max_claims_per_proposal": 2, "max_hypotheses": 2},
        "schema": {"max_signal_enum": 64, "max_bytes": 16384, "exclude_fault_classes": ["unknown"]},
    }
)
A, B, C, D = "Eaaaaaaaaaa", "Ebbbbbbbbbb", "Ecccccccccc", "Edddddddddd"
SILENT = CheckedClaim("silent", {}, ())
ZSCORE = CheckedClaim("zscore_above", {"signal": "cpu", "k": 3.0}, (A,))


def _proposal(service: str = "cart", fault_class: str = "cpu", **changes: Any) -> CheckedProposal:
    fields: dict[str, Any] = {
        "indicator": "cpu",
        "claims": (ZSCORE,),
        "requested_trials": ("T10", "T2"),
        "rationale": "cpu rose first",
        **changes,
    }
    return CheckedProposal(service, fault_class, **fields)


def _document(proposals: list[dict[str, Any]], asks: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "schema_version": CONTRACTS["proposals"].version,
        "case_id": "59e0d31bcc42",
        "status": "complete",
        "mode": "brief",
        "model": None,
        "budget_used": {"turns": 1, "tokens_in": 1, "tokens_out": 1, "wall_ms": 1.0},
        "proposals": proposals,
        "asks": asks,
    }


def test_output_passes_the_contract_writer_with_its_sort_orders() -> None:
    proposals = normalize_proposals(
        [_proposal("frontend", claims=(ZSCORE, SILENT)), _proposal("cart", indicator=None)], SETTINGS
    )
    asks = normalize_asks([CheckedAsk("trial", "T8", "isolate"), CheckedAsk("context", "x", "why")])
    io.encode("proposals", _document(proposals, asks))  # schema, model and every x-sort order
    first = models.Proposal.model_validate(proposals[0])
    assert first.hypothesis.service == "cart" and first.hypothesis.indicator is None
    assert first.hypothesis.component is None
    assert first.requested_trials == ["T2", "T10"]  # trial order, not byte order
    assert first.claims[0].claim_id == f"{first.proposal_id}-1"


def test_proposal_id_is_a_hash_of_the_content() -> None:
    (one,) = normalize_proposals([_proposal()], SETTINGS)
    (same,) = normalize_proposals([_proposal(rationale="other words")], SETTINGS)
    (other,) = normalize_proposals([_proposal(claims=(SILENT,))], SETTINGS)
    assert one["proposal_id"] == same["proposal_id"] != other["proposal_id"]


def test_merging_unions_claims_cites_and_trials() -> None:
    first = _proposal(claims=(CheckedClaim("zscore_above", ZSCORE.args, (A, B)),), requested_trials=("T3",))
    second = _proposal(
        claims=(CheckedClaim("zscore_above", ZSCORE.args, (B, C, D)), SILENT),
        requested_trials=("T1", "T3"),
    )
    (merged,) = normalize_proposals([first, second], SETTINGS)
    assert merged["requested_trials"] == ["T1", "T3"]
    assert [c["predicate"] for c in merged["claims"]] == ["silent", "zscore_above"]
    assert merged["claims"][1]["cites"] == [A, B, C]  # the union, cut to the contract's 3


def test_the_first_indicator_in_canonical_order_is_kept() -> None:
    (merged,) = normalize_proposals([_proposal(indicator=None), _proposal(indicator="mem")], SETTINGS)
    assert merged["hypothesis"]["indicator"] == "mem"


def test_caps_keep_the_sorted_first() -> None:
    other = CheckedClaim("onset_before", {"other_service": "cart"}, ())
    proposals = [_proposal(s, claims=(ZSCORE, SILENT, other)) for s in ("frontend", "cart", "checkout")]
    out = normalize_proposals(proposals, SETTINGS)
    assert [p["hypothesis"]["service"] for p in out] == ["cart", "checkout"]
    assert [c["predicate"] for c in out[0]["claims"]] == ["onset_before", "silent"]


def test_asks_are_unique_sorted_and_capped() -> None:
    asks = [CheckedAsk("trial", t, "why") for t in ("T4", "T3", "T2", "T1", "T1")]
    assert [a["target"] for a in normalize_asks(asks)] == ["T1", "T2", "T3"]


_REPLY = [
    _proposal(claims=(ZSCORE, SILENT), rationale="one"),
    _proposal(claims=(CheckedClaim("zscore_above", ZSCORE.args, (B,)),), indicator=None, rationale="two"),
    _proposal("checkout", "mem", rationale="three"),
]


@given(st.permutations(_REPLY))
def test_the_order_of_the_reply_never_changes_the_output(reply: list[CheckedProposal]) -> None:
    base = canonical_json(normalize_proposals(_REPLY, SETTINGS))
    reversed_claims = [
        CheckedProposal(
            p.service, p.fault_class, p.indicator, p.claims[::-1], p.requested_trials[::-1], p.rationale
        )
        for p in reply
    ]
    assert canonical_json(normalize_proposals(reply, SETTINGS)) == base
    assert canonical_json(normalize_proposals(reversed_claims, SETTINGS)) == base
