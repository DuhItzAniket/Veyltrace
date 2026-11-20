"""Checking and salvaging a model reply (08 §3.2, §3.4, §7 A1-A3)."""

from __future__ import annotations

from typing import Any

import pytest

from veyltrace_core.config import load_section_file
from veyltrace_core.testing import repo_root
from veyltrace_faultloom.predicates import LIBRARY
from veyltrace_faultloom.validation import CaseDomain
from veyltrace_relentra.reply import check_reply
from veyltrace_relentra.schema import EMPTY, build_enums
from veyltrace_relentra.settings import brief_settings

SETTINGS = brief_settings(
    {
        "brief": {"max_proposals": 3, "max_repairs": 1},
        "budget": {"max_claims_per_proposal": 4, "max_hypotheses": 5, "max_prompt_tokens": 12288},
        "sampler": {
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 20,
            "presence_penalty": 1.5,
            "thinking": False,
            "seed_index": 0,
            "max_tokens": {"brief": 1024},
        },
        "schema": {"max_signal_enum": 64, "max_bytes": 16384, "exclude_fault_classes": ["unknown"]},
        "cards": {"k": 6, "k_min": 3, "pool_context_n": 10},
        "prompt": {"chars_per_token": 3.5, "include_brief": True, "permute_slate": False},
    }
)
NODES = ["cart", "checkout", "frontend"]
SIGNALS = ["cpu", "error_rate"]
ATOMS = ["Eaaaaaaaaaa", "Ebbbbbbbbbb", "Ecccccccccc", "Edddddddddd"]
ENUMS = build_enums(NODES, SIGNALS, ATOMS, SETTINGS)
_PREDICATES = load_section_file("faultloom", config_dir=repo_root() / "config")["predicates"]
DOMAIN = CaseDomain(
    frozenset(NODES),
    frozenset(SIGNALS),
    {n: {p: (r["min"], r["max"]) for p, r in ps.items()} for n, ps in _PREDICATES.items()},
)
#: One valid claim per predicate: (signal, other, x) and the arguments it must map to (08 §3.4).
SLOTS: dict[str, tuple[str, str, float, dict[str, Any]]] = {
    "zscore_above": ("cpu", EMPTY, 3.0, {"signal": "cpu", "k": 3.0}),
    "onset_before": (EMPTY, "frontend", 0.0, {"other_service": "frontend"}),
    "edge_anomalous": (EMPTY, "frontend", 0.0, {"callee": "frontend"}),
    "self_time_share_above": (EMPTY, EMPTY, 0.5, {"x": 0.5}),
    "change_before_onset": (EMPTY, EMPTY, 60000.0, {"max_ms": 60000.0}),
    "template_new_in_incident": (EMPTY, EMPTY, 2.6, {"min_count": 3}),
    "error_rate_above": (EMPTY, EMPTY, 0.1, {"x": 0.1}),
    "silent": (EMPTY, EMPTY, 0.0, {}),
    "on_critical_path": (EMPTY, EMPTY, 0.2, {"min_share": 0.2}),
    "peer_gap_above": (EMPTY, EMPTY, 2.0, {"x": 2.0}),
}


def _claim(predicate: str = "zscore_above", **changes: Any) -> dict[str, Any]:
    signal, other, x, _ = SLOTS[predicate]
    return {"predicate": predicate, "signal": signal, "other": other, "x": x, "cites": [], **changes}


def _proposal(service: str = "cart", fault_class: str = "cpu", **changes: Any) -> dict[str, Any]:
    return {
        "service": service,
        "fault_class": fault_class,
        "indicator": "cpu",
        "claims": [_claim()],
        "requested_trials": ["T10", "T2"],
        "rationale": "cpu rose first",
        **changes,
    }


def _check(*proposals: dict[str, Any], asks: list[Any] | None = None) -> Any:
    return check_reply({"proposals": list(proposals), "asks": asks or []}, ENUMS, DOMAIN, SETTINGS)


def test_slots_cover_the_whole_library() -> None:
    assert set(SLOTS) == set(LIBRARY)


@pytest.mark.parametrize("predicate", sorted(SLOTS))
def test_every_predicate_maps_its_slots_to_named_arguments(predicate: str) -> None:
    checked = _check(_proposal(claims=[_claim(predicate)]))
    assert checked.problems == ()
    assert dict(checked.proposals[0].claims[0].args) == SLOTS[predicate][3]  # never a `subject` key


@pytest.mark.parametrize(
    ("change", "text"),
    [
        ({"other": EMPTY}, "needs 'other'"),
        ({"other": "paymentservice-v2"}, "unknown service"),
        ({"predicate": "made_up"}, "unknown predicate"),
        ({"x": True}, "finite number"),
        ({"cites": ["Eeeeeeeeeee"]}, "evidence cards"),
        ({"cites": ATOMS}, "at most 3"),
        ({"cites": [["Eaaaaaaaaaa"]]}, "evidence cards"),  # unhashable items must not raise
        ({"cites": [{}]}, "evidence cards"),
        ({"x": 10**400}, "finite number"),  # JSON integers are unbounded
    ],
)
def test_a_bad_claim_is_dropped_and_the_good_one_stays(change: dict[str, Any], text: str) -> None:
    good = _claim("silent")
    checked = _check(_proposal(claims=[good, {**_claim("onset_before"), **change}]))
    assert len(checked.proposals) == 1 and len(checked.proposals[0].claims) == 1
    assert text in str(checked.problems[0]) and checked.problems[0].path == "proposals[0].claims[1]"
    assert [d.kind for d in checked.drops] == ["drop_claim"]


def test_an_out_of_range_threshold_is_bad_args() -> None:
    checked = _check(_proposal(claims=[_claim(x=1000.0)]))  # k is limited to [1, 100]
    assert checked.proposals == () and "bad_args" in str(checked.problems[0])
    assert [d.kind for d in checked.drops] == ["drop_claim", "drop_proposal"]


@pytest.mark.parametrize(
    "change",
    [
        {"service": "paymentservice-v2"},
        {"fault_class": "unknown"},
        {"indicator": "cpu_usage"},
        {"requested_trials": ["T11"]},
        {"requested_trials": [["T1"]]},
        {"rationale": "x" * 281},
        {"extra": 1},
    ],
)
def test_an_invalid_hypothesis_drops_the_proposal(change: dict[str, Any]) -> None:
    checked = _check(_proposal(**change), _proposal("checkout"))
    assert [p.service for p in checked.proposals] == ["checkout"]
    assert [d.kind for d in checked.drops] == ["drop_proposal"]


@pytest.mark.parametrize("value", [None, [], "text", 3])
def test_anything_but_the_reply_object_salvages_nothing(value: object) -> None:
    checked = check_reply(value, ENUMS, DOMAIN, SETTINGS)
    assert checked.proposals == () and checked.asks == () and checked.problems


@pytest.mark.parametrize("reply", [{}, {"asks": "none"}, {"asks": [], "extra": 1}])
def test_a_bad_top_level_key_keeps_the_valid_proposals(reply: dict[str, Any]) -> None:
    checked = check_reply({"proposals": [_proposal()], **reply}, ENUMS, DOMAIN, SETTINGS)
    assert [p.service for p in checked.proposals] == ["cart"] and checked.problems


def test_a_reply_without_proposals_keeps_its_asks() -> None:
    ask = {"kind": "trial", "target": "T8", "why": "isolate"}
    checked = check_reply({"asks": [ask]}, ENUMS, DOMAIN, SETTINGS)
    assert [a.target for a in checked.asks] == ["T8"] and checked.problems[0].path == "reply"


def test_lists_over_their_limit_are_problems_and_are_cut() -> None:
    checked = _check(*[_proposal() for _ in range(4)])
    assert len(checked.proposals) == 3 and "at most 3" in str(checked.problems[0])


def test_a_bad_ask_is_reported_and_left_out() -> None:
    good = {"kind": "trial", "target": "T8", "why": "isolate"}
    checked = _check(_proposal(), asks=[{"kind": "nope", "target": "x", "why": "y"}, good])
    assert [a.target for a in checked.asks] == ["T8"] and checked.problems[0].path == "asks[0]"
