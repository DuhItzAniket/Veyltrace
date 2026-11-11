"""Tests of rank(): gated RRF and the 07 §3.1 step-5 order (07 §3.7 fusion table, §7 properties)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_causatrix.config import CausatrixConfig, config_from
from veyltrace_causatrix.rank import RankResult, rank
from veyltrace_causatrix.views import EvidenceView, GraphView, ServiceEvidence, graph_view
from veyltrace_contracts.models import Sources
from veyltrace_core.config import load_section_file
from veyltrace_core.errors import ConfigError

CFG = config_from(load_section_file("causatrix"), load_section_file("core"))
NO_EVENTS = Sources(metrics=True, logs=True, traces=True, events=False)
SE = ServiceEvidence
EXAMPLE = {  # 07 §3.7
    "checkout": SE(internal=9.0, external=11.0, nsigma=10.5, spectrum=0.683),
    "currency": SE(internal=2.0, external=4.5, nsigma=5.0, spectrum=0.210),
    "frontend": SE(internal=1.2, external=14.0, nsigma=16.0, spectrum=0.258),
    "payment": SE(internal=0.8, external=1.0, nsigma=1.1, spectrum=0.165),
}
CALLS = [
    ("frontend", "checkout"),
    ("frontend", "currency"),
    ("checkout", "payment"),
    ("checkout", "currency"),
]


def _view(facts: dict[str, ServiceEvidence], change: bool = False) -> EvidenceView:
    return EvidenceView(tuple(sorted(facts)), (), facts, True, True, True, change)


def _graph(members: list[str], calls: list[tuple[str, str]]) -> GraphView:
    rows: list[dict[str, Any]] = [
        {"src": s, "dst": d, "weight": 1.0, "provenance": ["traces"]} for s, d in calls
    ]
    return graph_view(members, [], rows, include_external=False)


def test_worked_example_fusion_table() -> None:
    result = rank(_view(EXAMPLE), _graph(list(EXAMPLE), CALLS), NO_EVENTS, CFG)
    assert result.active == ("baro_rs", "cp_sbfl", "graph_walk", "nsigma", "prism_m")
    expected = {
        "checkout": 3 / 61 + 2 / 62,
        "frontend": 2 / 61 + 3 / 62,
        "currency": 5 / 63,
        "payment": 5 / 64,
    }
    assert {s: round(f, 9) for s, f in result.fused.items()} == {s: round(f, 9) for s, f in expected.items()}
    assert round(result.fused["checkout"], 9) == 0.081438392
    assert result.order == ("checkout", "frontend", "currency", "payment")
    change = next(v for v in result.votes if v.ranker == "change_prox")
    assert (change.active, change.abstained) == (False, "no_channel")


@pytest.mark.parametrize(
    ("ranker", "order"),
    [
        ("prism_m", ("checkout", "frontend", "currency", "payment")),
        ("baro_rs", ("frontend", "checkout", "currency", "payment")),
        ("nsigma", ("frontend", "checkout", "currency", "payment")),
        ("cp_sbfl", ("checkout", "frontend", "currency", "payment")),
        ("graph_walk", ("checkout", "frontend", "currency", "payment")),
    ],
)
def test_each_ranker_alone_gives_its_own_order(ranker: str, order: tuple[str, ...]) -> None:
    # Bench's `causatrix:<ranker>` method sets causatrix.rankers.enabled=[<ranker>] (07 §9).
    alone = replace(CFG, rankers=(ranker,), weights=((ranker, 1.0),))
    result = rank(_view(EXAMPLE), _graph(list(EXAMPLE), CALLS), NO_EVENTS, alone)
    assert result.active == (ranker,)
    assert result.order == order


def test_no_vote_gives_zero_scores_and_the_tie_break_order() -> None:
    facts = {
        "a": SE(),
        "b": SE(internal=3.0, onset_ms=50.0),
        "c": SE(internal=8.0, onset_ms=10.0),
        "d": SE(internal=2.9, onset_ms=1.0),
    }
    view = EvidenceView(tuple(sorted(facts)), (), facts, False, False, False, False)
    result = rank(view, _graph(list(facts), []), NO_EVENTS, CFG)
    assert result.active == () and set(result.fused.values()) == {0.0}
    assert result.order == ("c", "b", "d", "a")  # internal-first, then earliest onset, then name


def test_equal_non_zero_fused_scores_fall_back_to_the_name() -> None:
    # a and b have the same evidence, so every voting ranker ties them: equal F > 0, both internal
    # anomalies, no onsets, so the step-5 key comes down to the name (07 §3.1 step 5).
    facts = {"b": SE(internal=5.0, external=6.0), "a": SE(internal=5.0, external=6.0), "c": SE(1.0, 1.0)}
    result = rank(_view(facts), _graph(list(facts), []), NO_EVENTS, CFG)
    assert result.active and result.fused["a"] == result.fused["b"] > result.fused["c"]
    assert result.order == ("a", "b", "c")
    assert hash(result) == hash(rank(_view(facts), _graph(list(facts), []), NO_EVENTS, CFG))


def test_other_fusion_methods_and_mismatched_views_are_refused() -> None:
    graph = _graph(list(EXAMPLE), CALLS)
    with pytest.raises(ConfigError, match="borda"):
        rank(_view(EXAMPLE), graph, NO_EVENTS, replace(CFG, method="borda"))
    with pytest.raises(ValueError, match="same universe"):
        rank(_view(EXAMPLE), _graph(["checkout"], []), NO_EVENTS, CFG)


_names = ["a", "b", "c", "d", "e"]
_facts = st.fixed_dictionaries(
    {
        s: st.builds(
            lambda i, e, ns, sil, ch: SE(internal=i, external=e, nsigma=ns, silent=sil, change=ch),
            *(st.floats(min_value=0.0, max_value=30.0) for _ in range(3)),
            st.sampled_from([0.0, 1.0]),
            st.floats(min_value=0.0, max_value=1.0),
        )
        for s in _names
    }
)
_calls = st.lists(st.tuples(st.sampled_from(_names), st.sampled_from(_names)), unique=True, max_size=8)


def _rank(
    f: dict[str, ServiceEvidence], calls: list[tuple[str, str]], src: Sources, cfg: CausatrixConfig
) -> RankResult:
    return rank(_view(f, change=True), _graph(sorted(f), calls), src, cfg)


@given(facts=_facts, calls=_calls)
def test_rrf_bound_and_abstaining_rankers(
    facts: dict[str, ServiceEvidence], calls: list[tuple[str, str]]
) -> None:
    full = _rank(facts, calls, NO_EVENTS, CFG)
    assert all(0.0 <= f <= len(full.active) / (CFG.rrf_k + 1) + 1e-15 for f in full.fused.values())
    # change_prox abstains without events: dropping it from rankers.enabled never changes F.
    names = tuple(r for r in CFG.rankers if r != "change_prox")
    fewer = replace(CFG, rankers=names, weights=tuple((r, 1.0) for r in names))
    assert _rank(facts, calls, NO_EVENTS, fewer).fused == full.fused


@given(facts=_facts, calls=_calls)
def test_renaming_services_relabels_the_result(
    facts: dict[str, ServiceEvidence], calls: list[tuple[str, str]]
) -> None:
    rename = {"a": "v", "b": "z", "c": "w", "d": "y", "e": "x"}
    events = Sources(metrics=True, logs=True, traces=True, events=True)
    before = _rank(facts, calls, events, CFG)
    after = _rank(
        {rename[s]: f for s, f in facts.items()}, [(rename[s], rename[d]) for s, d in calls], events, CFG
    )
    assert after.active == before.active
    assert {rename[s]: f for s, f in before.fused.items()} == pytest.approx(dict(after.fused), abs=1e-15)
