"""Tests of the five evidence-channel rankers, competition ranks and gating (07 §3.1–§3.3, §3.7)."""

from __future__ import annotations

import math
from dataclasses import replace
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_causatrix.config import config_from
from veyltrace_causatrix.ranking import CONSTANT, NO_CHANNEL, Ranker, competition_ranks, load_ranker, vote
from veyltrace_causatrix.views import EvidenceView, ServiceEvidence, graph_view
from veyltrace_contracts.models import Sources
from veyltrace_core.config import load_section_file
from veyltrace_core.errors import ConfigError

CFG = config_from(load_section_file("causatrix"), load_section_file("core"))
GRAPH = graph_view([], [], [], include_external=False)
ALL = Sources(metrics=True, logs=True, traces=True, events=True)
NO_EVENTS = Sources(metrics=True, logs=True, traces=True, events=False)
SE = ServiceEvidence
#: The 07 §3.7 micro-example (robust z I and E, nsigma NS, spectrum SP).
EXAMPLE = {
    "checkout": SE(internal=9.0, external=11.0, nsigma=10.5, spectrum=0.683),
    "currency": SE(internal=2.0, external=4.5, nsigma=5.0, spectrum=0.210),
    "frontend": SE(internal=1.2, external=14.0, nsigma=16.0, spectrum=0.258),
    "payment": SE(internal=0.8, external=1.0, nsigma=1.1, spectrum=0.165),
}


def _view(facts: dict[str, ServiceEvidence], *, channels: bool = True) -> EvidenceView:
    return EvidenceView(tuple(sorted(facts)), (), facts, channels, channels, channels, channels)


def _ranks(name: str, facts: dict[str, ServiceEvidence], sources: Sources = ALL) -> dict[str, int]:
    result = vote(load_ranker(name), _view(facts), GRAPH, sources, CFG)
    assert result.active, result.abstained
    return dict(result.ranks)


def test_competition_ranks_share_ties_after_rounding_to_1e12() -> None:
    assert competition_ranks({"a": 3.0, "b": 3.0, "c": 1.0, "d": 3.0 + 1e-13}) == {
        "a": 1,
        "b": 1,
        "c": 4,
        "d": 1,
    }
    assert competition_ranks({"x": 2.0, "y": 1.0, "z": 2.0 + 1e-11}) == {"x": 2, "y": 3, "z": 1}
    assert competition_ranks({}) == {}


def test_worked_example_scores_and_ranks() -> None:
    prism = vote(load_ranker("prism_m"), _view(EXAMPLE), GRAPH, NO_EVENTS, CFG)
    expected = {"checkout": 16.955, "currency": 4.485, "frontend": 12.415, "payment": 0.770}
    assert {s: round(x, 3) for s, x in prism.scores.items()} == expected
    order = {"checkout": 1, "frontend": 2, "currency": 3, "payment": 4}
    assert dict(prism.ranks) == order
    # baro_rs and nsigma put the entry service first: the max-deviation failure of 07 §3.7.
    assert _ranks("baro_rs", EXAMPLE) == {"frontend": 1, "checkout": 2, "currency": 3, "payment": 4}
    assert _ranks("nsigma", EXAMPLE) == {"frontend": 1, "checkout": 2, "currency": 3, "payment": 4}
    assert _ranks("cp_sbfl", EXAMPLE) == order
    assert vote(load_ranker("change_prox"), _view(EXAMPLE), GRAPH, NO_EVENTS, CFG).abstained == NO_CHANNEL


def test_prism_m_counts_silence_and_has_a_conjunctive_form() -> None:
    facts = {"a": SE(internal=2.0, silent=1.0), "b": SE(internal=3.0, external=4.0)}
    scores = vote(load_ranker("prism_m"), _view(facts), GRAPH, ALL, CFG).scores
    assert scores["a"] == pytest.approx(10.0 - math.log(11.0))  # I' = silence_z · Sil = 10
    conj = vote(load_ranker("prism_m"), _view(facts), GRAPH, ALL, replace(CFG, prism_combine="conj"))
    assert dict(conj.scores) == {"a": 0.0, "b": 3.0}


def test_change_prox_needs_an_anomalous_or_silent_service() -> None:
    facts = {
        "anomalous": SE(external=3.0, change=0.7),
        "quiet": SE(internal=2.9, change=0.9),
        "silent": SE(silent=1.0, change=0.4),
        "none": SE(internal=8.0),
    }
    scores = vote(load_ranker("change_prox"), _view(facts), GRAPH, ALL, CFG).scores
    assert dict(scores) == {"anomalous": 0.7, "none": 0.0, "quiet": 0.0, "silent": 0.4}


@pytest.mark.parametrize(
    ("name", "sources", "channels"),
    [
        ("prism_m", ALL, False),
        ("baro_rs", ALL, False),
        ("nsigma", ALL, False),
        ("cp_sbfl", ALL, False),
        ("cp_sbfl", Sources(metrics=True, logs=True, traces=False, events=True), True),
        ("change_prox", ALL, False),
        ("change_prox", NO_EVENTS, True),
    ],
)
def test_gating_abstains_without_the_channel(name: str, sources: Sources, channels: bool) -> None:
    facts = {s: replace(f, change=0.5) for s, f in EXAMPLE.items()}
    view = _view(facts, channels=channels)
    assert vote(load_ranker(name), view, GRAPH, sources, CFG).abstained == NO_CHANNEL
    # Ungated RRF (rrf.gate: false, an ablation) lets it vote on whatever scores it finds.
    assert vote(load_ranker(name), view, GRAPH, sources, replace(CFG, gate=False)).active


def test_constant_scores_abstain_unless_disabled() -> None:
    flat = {"a": SE(internal=5.0), "b": SE(internal=5.0 + 1e-13)}
    assert vote(load_ranker("baro_rs"), _view(flat), GRAPH, ALL, CFG).abstained == CONSTANT
    loose = vote(load_ranker("baro_rs"), _view(flat), GRAPH, ALL, replace(CFG, abstain_on_constant=False))
    assert dict(loose.ranks) == {"a": 1, "b": 1}
    assert vote(load_ranker("nsigma"), _view({}), GRAPH, ALL, CFG).abstained == CONSTANT  # empty U


def test_a_scorer_must_cover_u_with_finite_values() -> None:
    nan = Ranker("bad", lambda ev, g, s, c: True, lambda ev, g, c: dict.fromkeys(ev.universe, math.nan))
    short = Ranker("bad", lambda ev, g, s, c: True, lambda ev, g, c: {"checkout": 1.0})
    for ranker in (nan, short):
        with pytest.raises(ValueError, match="finite score"):
            vote(ranker, _view(EXAMPLE), GRAPH, ALL, CFG)


def test_entry_points_are_exactly_the_ranker_modules() -> None:
    declared = {ep.name: ep for ep in entry_points(group="veyltrace.rankers")}
    rankers_dir = Path(__file__).resolve().parents[1] / "src" / "veyltrace_causatrix" / "rankers"
    modules = {p.stem for p in rankers_dir.glob("*.py") if p.stem != "__init__"}
    assert set(declared) == modules
    for name, ep in sorted(declared.items()):
        assert ep.load() is load_ranker(name)
        assert ep.value == f"veyltrace_causatrix.rankers.{name}:RANKER"


@pytest.mark.parametrize("name", ["no_such_ranker", "Bad-Name"])
def test_unknown_or_malformed_ranker_names_are_config_errors(name: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_ranker(name)


_z = st.floats(min_value=0.0, max_value=40.0, allow_nan=False)
_facts = st.dictionaries(
    st.sampled_from(["a", "b", "c", "d", "e"]),
    st.builds(lambda i, e, sil: SE(internal=i, external=e, silent=sil), _z, _z, st.sampled_from([0.0, 1.0])),
    min_size=2,
)


@given(facts=_facts, bump=st.floats(min_value=0.0, max_value=20.0), data=st.data())
def test_raising_internal_never_lowers_prism_or_baro_rank(
    facts: dict[str, ServiceEvidence], bump: float, data: st.DataObject
) -> None:
    s = data.draw(st.sampled_from(sorted(facts)))
    raised = {**facts, s: replace(facts[s], internal=facts[s].internal + bump)}
    cfg = replace(CFG, abstain_on_constant=False)
    for name in ("prism_m", "baro_rs"):
        before = vote(load_ranker(name), _view(facts), GRAPH, ALL, cfg).ranks[s]
        after = vote(load_ranker(name), _view(raised), GRAPH, ALL, cfg).ranks[s]
        assert after <= before
