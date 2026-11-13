"""Unit and property tests of `onset_precedence` and `propagation` on hand-built views (06 §3.4, §3.9)."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from veyltrace_faultloom.graph import callers, onset_atoms, propagation_atoms

SELF = '{"scope":"self","window":"onset"}'
DEPS = '{"scope":"dependents","window":"onset"}'
IVE = '{"scope":"internal_vs_external","window":"onset"}'
ENTRY = '{"scope":"entry","window":"incident"}'
ANOM = '{"scope":"anomalous","window":"incident"}'
PATH = '{"scope":"path","window":"incident"}'


def _by(atoms: list[dict[str, Any]]) -> dict[tuple[str, str], Any]:
    return {(a["candidate"], a["args_json"]): a for a in atoms}


def _values(atoms: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    return {key: a["value"] for key, a in _by(atoms).items()}


def _ext(hm: Any, service: str, score: float) -> Any:
    return hm.anomaly(f"{service}|{service}|latency|traces", "external", score=score)


# --- onset_precedence -------------------------------------------------------------------------
def test_self_onset_is_ms_after_t_onset_and_absent_without_onset(hm: Any) -> None:
    v = hm.view(onsets=(hm.onset("a", internal=-30), hm.onset("b")))
    assert _values(onset_atoms(v)) == {("a", SELF): -30_000.0}  # b: no onset, c: no entry (06 §6)


def test_onset_is_the_earlier_of_internal_and_external(hm: Any) -> None:
    v = hm.view(onsets=(hm.onset("a", ext=10, internal=-5), hm.onset("b", ext=4)))
    got = _values(onset_atoms(v))
    assert got[("a", SELF)] == -5_000.0 and got[("b", SELF)] == 4_000.0
    assert got[("a", IVE)] == 15_000.0  # external - internal; positive = internal first
    assert ("b", IVE) not in got  # needs both onsets


def test_dependents_counts_anomalous_callers_preceded_within_tolerance(hm: Any) -> None:
    # a -> b -> c: c's dependents are a and b (transitive callers); tol = 15 s.
    v = hm.view(
        onsets=(hm.onset("a", ext=0), hm.onset("b", ext=20), hm.onset("c", internal=14)),
        edges=(hm.edge("a", "b"), hm.edge("b", "c")),
        anomalies=(_ext(hm, "a", 5.0), _ext(hm, "b", 3.0)),
    )
    atoms = _by(onset_atoms(v))
    assert atoms["c", DEPS]["value"] == 1.0  # 14 <= 20 + 15 and 14 <= 0 + 15 (a tie within tol)
    assert atoms["c", DEPS]["refs"] == ["onsets#a", "onsets#b", "onsets#c"]
    assert atoms["b", DEPS]["value"] == 0.0  # 20 > 0 + 15
    assert ("a", DEPS) not in atoms  # no callers


def test_dependents_need_an_onset_and_an_external_anomaly(hm: Any) -> None:
    v = hm.view(
        onsets=(hm.onset("a", ext=0), hm.onset("b"), hm.onset("c", internal=30)),
        edges=(hm.edge("a", "c"), hm.edge("b", "c")),
        anomalies=(
            _ext(hm, "a", 2.9),
            _ext(hm, "b", 9.0),
            hm.anomaly("a|a|cpu|metrics", "internal", score=9.0),
        ),
    )
    assert ("c", DEPS) not in _values(onset_atoms(v))  # a below k_anom (internal z ignored), b no onset
    hot = dataclasses.replace(v, k_anom=2.5)
    assert _values(onset_atoms(hot))[("c", DEPS)] == 0.0  # a counts now; c (30 s) is later


def test_cycles_are_harmless_and_a_service_is_not_its_own_dependent(hm: Any) -> None:
    v = hm.view(
        onsets=(hm.onset("a", ext=0), hm.onset("b", ext=0)),
        edges=(hm.edge("a", "b"), hm.edge("b", "a")),
        anomalies=(_ext(hm, "a", 4.0), _ext(hm, "b", 4.0)),
    )
    assert callers(v.edges) == {"a": frozenset({"b"}), "b": frozenset({"a"})}
    got = _values(onset_atoms(v))
    assert got[("a", DEPS)] == 1.0 and got[("b", DEPS)] == 1.0


# --- propagation ------------------------------------------------------------------------------
def _chain(hm: Any, **fields: Any) -> Any:
    # a (entry) -> b -> c; a and c externally anomalous, b internally.
    rows = (_ext(hm, "a", 6.0), hm.anomaly("b|b|cpu|metrics", "internal", score=4.0), _ext(hm, "c", 3.5))
    base = {"edges": (hm.edge("a", "b"), hm.edge("b", "c")), "entry_services": ("a",), "anomalies": rows}
    return hm.view(**{**base, **fields})


def test_propagation_entry_and_anomalous_on_the_reversed_graph(hm: Any) -> None:
    got = _values(propagation_atoms(_chain(hm)))
    # c reaches b and a (its callers); a reaches only itself.
    assert got[("c", ENTRY)] == 1.0 and got[("c", ANOM)] == 1.0
    assert got[("b", ENTRY)] == 1.0 and got[("b", ANOM)] == 0.5  # reaches a, not c
    assert got[("a", ENTRY)] == 1.0 and got[("a", ANOM)] == 0.0  # an entry reaches itself
    refs = {c: a["refs"] for (c, args), a in _by(propagation_atoms(_chain(hm))).items() if args == ENTRY}
    assert refs == {"c": ["graph.edges#a-b", "graph.edges#b-c"], "b": ["graph.edges#a-b"], "a": []}  # walked


def test_is_entry_nodes_and_silence_count(hm: Any) -> None:
    nodes = (hm.node("b", is_entry=True),)
    v = _chain(hm, entry_services=(), nodes=nodes, onsets=(hm.onset("c", silent=True),))
    got = _values(propagation_atoms(v))
    assert ("a", ENTRY) not in got  # b is the only entry and not externally anomalous: no atom
    v2 = _chain(hm, entry_services=(), nodes=(hm.node("c", is_entry=True),), anomalies=())
    got2 = _values(propagation_atoms(dataclasses.replace(v2, onsets=(hm.onset("b", silent=True),))))
    assert got2[("c", ANOM)] == 1.0  # b is anomalous only through silence
    assert ("c", ENTRY) not in got2  # c has no external z: no anomalous entry


def test_no_edges_no_reachability_atoms_but_paths_stay(hm: Any) -> None:
    v = _chain(hm, edges=(), paths=(hm.path("c", 1, 0.5), hm.path("c", 2, 1.0)))
    got = _values(propagation_atoms(v))
    assert got == {("c", PATH): 0.5}  # rank 1 only (06 §3.4); no graph edges (06 §6)


# --- properties -------------------------------------------------------------------------------
_secs = st.one_of(st.none(), st.integers(min_value=-300, max_value=300))


@given(data=st.data())
def test_graph_atoms_do_not_depend_on_row_order(hm: Any, data: st.DataObject) -> None:
    names = ("a", "b", "c")
    onsets = tuple(hm.onset(n, ext=data.draw(_secs), internal=data.draw(_secs)) for n in names)
    pairs = data.draw(
        st.lists(st.tuples(st.sampled_from(names), st.sampled_from(names)), max_size=6, unique=True)
    )
    edges = tuple(hm.edge(s, d) for s, d in pairs)
    rows = tuple(_ext(hm, n, data.draw(st.floats(0, 9))) for n in names)
    base = hm.view(onsets=onsets, edges=edges, anomalies=rows, entry_services=("a",))
    shuffled = dataclasses.replace(
        base, onsets=tuple(data.draw(st.permutations(onsets))), edges=tuple(data.draw(st.permutations(edges)))
    )
    for build in (onset_atoms, propagation_atoms):
        assert build(base) == build(shuffled)
        for atom in build(base):
            value, args = atom["value"], str(atom["args_json"])
            if atom["unit"] is None:
                assert isinstance(value, float) and 0.0 <= value <= 1.0
            assert json.loads(args)["window"] in ("onset", "incident")
