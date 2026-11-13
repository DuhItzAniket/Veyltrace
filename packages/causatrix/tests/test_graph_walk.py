"""Tests of the `graph_walk` ranker: personalised PageRank against propagation (07 §3.4, §3.7)."""

from __future__ import annotations

import math
from dataclasses import replace
from importlib.metadata import entry_points
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_causatrix.config import config_from
from veyltrace_causatrix.rankers.graph_walk import score, transition_rows
from veyltrace_causatrix.ranking import CONSTANT, NO_CHANNEL, load_ranker, vote
from veyltrace_causatrix.views import EvidenceView, GraphView, ServiceEvidence, graph_view
from veyltrace_contracts.models import Sources
from veyltrace_core.config import load_section_file

CFG = config_from(load_section_file("causatrix"), load_section_file("core"))
ALL = Sources(metrics=True, logs=True, traces=True, events=True)
SE = ServiceEvidence
EXAMPLE = {  # 07 §3.7
    "checkout": SE(internal=9.0, external=11.0),
    "currency": SE(internal=2.0, external=4.5),
    "frontend": SE(internal=1.2, external=14.0),
    "payment": SE(internal=0.8, external=1.0),
}
CALLS = [
    ("frontend", "checkout"),
    ("frontend", "currency"),
    ("checkout", "payment"),
    ("checkout", "currency"),
]


def _view(facts: dict[str, ServiceEvidence]) -> EvidenceView:
    return EvidenceView(tuple(sorted(facts)), (), facts, True, True, True, True)


def _graph(members: list[str], calls: list[tuple[str, str]], weights: list[float] | None = None) -> GraphView:
    w = weights or [1.0] * len(calls)
    rows: list[dict[str, Any]] = [
        {"src": s, "dst": d, "weight": x, "provenance": ["traces"]}
        for (s, d), x in zip(calls, w, strict=True)
    ]
    return graph_view(members, [], rows, include_external=False)


def test_worked_example_rows_and_scores() -> None:
    graph = _graph(list(EXAMPLE), CALLS)
    rows = transition_rows(_view(EXAMPLE), graph, CFG)
    rounded = {
        u: ([(v, round(f, 3)) for v, f in r.moves], round(r.stay, 3), round(r.restart, 3))
        for u, r in rows.items()
    }
    assert rounded == {
        "checkout": ([("currency", 0.161), ("payment", 0.036)], 0.517, 0.287),
        "currency": ([], 0.143, 0.857),
        "frontend": ([("checkout", 0.393), ("currency", 0.161)], 0.038, 0.408),
        "payment": ([], 0.057, 0.943),
    }
    result = vote(load_ranker("graph_walk"), _view(EXAMPLE), graph, ALL, CFG)
    expected = {"checkout": 0.500381, "currency": 0.208490, "frontend": 0.256530, "payment": 0.034598}
    assert result.scores == pytest.approx(expected, abs=1e-6)  # 07 §3.7 values, 07 §7 tolerance
    assert dict(result.ranks) == {"checkout": 1, "frontend": 2, "currency": 3, "payment": 4}


def test_a_disconnected_node_keeps_a_self_loop_and_restart() -> None:
    # A node with no edge in or out: its row has no moves, never a negative part, and it is still
    # ranked through its own prior mass rather than dropped.
    facts = {**EXAMPLE, "ledger": SE(internal=6.0, external=0.0)}
    graph = _graph(list(facts), CALLS)
    rows = transition_rows(_view(facts), graph, CFG)
    assert rows["ledger"].moves == () and rows["ledger"].stay == pytest.approx(6.0 / 14.0)
    assert rows["ledger"].restart == pytest.approx(8.0 / 14.0)
    assert all(x >= 0 for r in rows.values() for x in (r.stay, r.restart, *(f for _, f in r.moves)))
    pi = score(_view(facts), graph, CFG)
    assert pi["ledger"] > 0 and math.fsum(pi.values()) == pytest.approx(1.0, abs=1e-9)


def test_abstains_without_edges_or_anomaly() -> None:
    ranker = load_ranker("graph_walk")
    no_edges = _graph(list(EXAMPLE), [])
    assert vote(ranker, _view(EXAMPLE), no_edges, ALL, CFG).abstained == NO_CHANNEL
    calm = {s: SE() for s in EXAMPLE}
    graph = _graph(list(EXAMPLE), CALLS)
    assert vote(ranker, _view(calm), graph, ALL, CFG).abstained == NO_CHANNEL
    # Ungated, a zero prior gives zero scores, which are constant: still no vote with zeros.
    assert vote(ranker, _view(calm), graph, ALL, replace(CFG, gate=False)).abstained == CONSTANT


def test_silence_enters_the_prior_through_silence_z() -> None:
    facts = {"api": SE(external=5.0), "db": SE(silent=1.0)}
    graph = _graph(list(facts), [("api", "db")])
    walked = vote(load_ranker("graph_walk"), _view(facts), graph, ALL, CFG)
    assert walked.ranks["db"] == 1  # the silent callee of an anomalous caller collects the mass
    only_silent = {"api": SE(), "db": SE(silent=1.0)}
    no_z = replace(CFG, silence_z=0.0)
    assert vote(load_ranker("graph_walk"), _view(only_silent), graph, ALL, no_z).abstained == NO_CHANNEL


def test_edge_weights_split_the_callee_share() -> None:
    facts = {"a": SE(internal=1.0), "b": SE(internal=5.0), "c": SE(internal=5.0)}
    graph = _graph(list(facts), [("a", "b"), ("a", "c")], [3.0, 1.0])
    row = transition_rows(_view(facts), graph, CFG)["a"]
    assert dict(row.moves) == pytest.approx({"b": 0.75, "c": 0.25})
    zero = _graph(list(facts), [("a", "b")], [0.0])
    assert transition_rows(_view(facts), zero, CFG)["a"].moves == ()


def test_every_enabled_default_ranker_is_installed() -> None:
    names = sorted(ep.name for ep in entry_points(group="veyltrace.rankers"))
    assert (
        names == list(CFG.rankers) == ["baro_rs", "change_prox", "cp_sbfl", "graph_walk", "nsigma", "prism_m"]
    )


_members = ["a", "b", "c", "d", "e"]
_facts = st.fixed_dictionaries(
    {
        s: st.builds(
            lambda i, e, sil: SE(internal=i, external=e, silent=sil),
            st.floats(min_value=0.0, max_value=30.0),
            st.floats(min_value=0.0, max_value=30.0),
            st.sampled_from([0.0, 1.0]),
        )
        for s in _members
    }
)
_calls = st.lists(st.tuples(st.sampled_from(_members), st.sampled_from(_members)), unique=True, max_size=12)


@given(facts=_facts, calls=_calls, self_loop=st.booleans())
def test_rows_sum_to_one_and_mass_is_conserved(
    facts: dict[str, ServiceEvidence], calls: list[tuple[str, str]], self_loop: bool
) -> None:
    cfg = replace(CFG, self_loop=self_loop)
    view, graph = _view(facts), _graph(_members, calls)
    if max(max(f.internal, f.external, f.silent) for f in facts.values()) <= 0:
        return
    for row in transition_rows(view, graph, cfg).values():
        parts = [f for _, f in row.moves]
        assert all(x >= 0 for x in [*parts, row.stay, row.restart])
        assert math.fsum([*parts, row.stay, row.restart]) == pytest.approx(1.0, abs=1e-12)
    assert math.fsum(score(view, graph, cfg).values()) == pytest.approx(1.0, abs=1e-9)
