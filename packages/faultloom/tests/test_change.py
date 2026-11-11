"""Unit tests of the change, peer and log atoms on hand-built views (06 §3.4, §3.9, §11 Q6)."""

from __future__ import annotations

import dataclasses
import math
import statistics
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_contracts import models
from veyltrace_core.errors import ConfigError
from veyltrace_faultloom.change import change_atoms, log_atoms, median, peer_atoms

PEER_ANOM = '{"source":"anomalies","window":"incident"}'
PEER_CHG = '{"source":"changes","window":"onset"}'
FINITE = st.floats(-1e6, 1e6, allow_nan=False)


def _by(atoms: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(a["candidate"], a["args_json"]): a for a in atoms}


def test_median_takes_the_mean_of_the_middle_pair_for_even_counts() -> None:
    assert median([3.0, 1.0, 2.0]) == 2.0
    assert median([4.0, 1.0, 3.0, 2.0]) == 2.5
    assert median([7.0]) == 7.0
    with pytest.raises(ValueError, match="no values"):
        median([])  # never a made-up 0.0 baseline


@given(xs=st.lists(FINITE, min_size=1, max_size=9), data=st.data())
def test_median_is_order_free_and_matches_statistics(xs: list[float], data: st.DataObject) -> None:
    assert median(data.draw(st.permutations(xs))) == median(xs) == statistics.median(xs)
    assert min(xs) <= median(xs) <= max(xs)


# --- change_proximity and peer_contrast{changes} ----------------------------------------------
def test_changes_map_to_their_service_or_its_components(hm: Any) -> None:
    v = hm.view(
        components={"a": frozenset({"a-1"}), "b": frozenset({"b"})},
        changes=(
            hm.change("C01", "a", proximity=0.9, peer=1.5),
            hm.change("C02", "a-1", scope="component", proximity=0.4, peer=4.0),
            hm.change("C03", "a", proximity=0.0, peer=6.0),  # too late: no proximity atom, still a peer gap
            hm.change("C04", "cluster-x", scope="cluster", proximity=1.0),  # cluster scope (06 §11 Q6)
            hm.change("C05", "ghost", proximity=1.0),  # maps to nothing
        ),
    )
    atoms = _by(change_atoms(v))
    prox = {k[1]: a["value"] for k, a in atoms.items() if a["kind"] == "change_proximity"}
    assert prox == {
        '{"change_id":"C01","event_kind":"deploy","window":"onset"}': 0.9,
        '{"change_id":"C02","event_kind":"deploy","window":"onset"}': 0.4,
    }
    assert {a["candidate"] for a in atoms.values()} == {"a"}
    peer = atoms["a", PEER_CHG]
    assert (peer["value"], peer["refs"], peer["unit"]) == (6.0, ["C03"], "z")


def test_a_shared_component_change_gives_one_atom_per_service(hm: Any) -> None:
    v = hm.view(
        components={"a": frozenset({"shared"}), "b": frozenset({"shared"})},
        changes=(hm.change("C01", "shared", "component"),),
    )
    assert sorted(str(a["candidate"]) for a in change_atoms(v)) == ["a", "b"]  # 06 §3.9


def test_no_peer_atom_without_a_peer_contrast_and_no_atom_without_events(hm: Any) -> None:
    v = hm.view(components={"a": frozenset({"a"})}, changes=(hm.change("C01", "a", peer=2.0),))
    assert [a["kind"] for a in change_atoms(v)] == ["change_proximity", "peer_contrast"]
    v = dataclasses.replace(v, changes=(hm.change("C01", "a"),))
    assert [a["kind"] for a in change_atoms(v)] == ["change_proximity"]
    no_events = models.Sources(metrics=True, logs=True, traces=True, events=False)
    assert change_atoms(dataclasses.replace(v, sources=no_events)) == []


# --- peer_contrast{anomalies} -------------------------------------------------------------------
def _z(hm: Any, series_id: str, score: float, klass: str = "internal") -> Any:
    return hm.anomaly(series_id, klass, score=score)


def test_peer_gap_is_top_component_minus_median_of_the_others(hm: Any) -> None:
    rows = (
        _z(hm, "a|a-1|cpu|metrics", 9.0),
        _z(hm, "a|a-2|cpu|metrics", 1.0),
        _z(hm, "a|a-2|mem|metrics", 2.0),  # a-2's max is 2.0
        _z(hm, "a|a-3|cpu|metrics", 4.0),
        _z(hm, "a|a-4|lat|traces", 50.0, "external"),  # external rows are not peers
    )
    (atom,) = peer_atoms(hm.view(anomalies=rows), 2)
    assert (atom["value"], atom["component"], atom["unit"], atom["args_json"]) == (6.0, "a-1", "z", PEER_ANOM)
    assert atom["refs"] == ["a|a-1|cpu|metrics", "a|a-2|mem|metrics", "a|a-3|cpu|metrics"]


def test_peer_gap_needs_min_components_and_breaks_ties_a_to_z(hm: Any) -> None:
    rows = (
        _z(hm, "a|a-2|cpu|metrics", 3.0),
        _z(hm, "a|a-1|cpu|metrics", 3.0),
        _z(hm, "b|b|cpu|metrics", 9.0),
    )
    (atom,) = peer_atoms(hm.view(anomalies=rows), 2)
    assert (atom["candidate"], atom["value"], atom["component"]) == ("a", 0.0, "a-1")
    assert peer_atoms(hm.view(anomalies=rows), 3) == []
    with pytest.raises(ConfigError, match="min_components"):
        peer_atoms(hm.view(anomalies=rows), 1)  # a service would be its own peer


_COMPS = st.dictionaries(
    st.sampled_from(["a-1", "a-2", "a-3", "a-4"]), st.lists(FINITE, min_size=1, max_size=3), min_size=2
)


@given(comps=_COMPS, data=st.data())
def test_peer_gap_is_top_minus_the_median_of_the_others_in_any_row_order(
    hm: Any, comps: dict[str, list[float]], data: st.DataObject
) -> None:
    rows = [_z(hm, f"a|{k}|m{j}|metrics", z) for k, zs in comps.items() for j, z in enumerate(zs)]
    best = {k: max(zs) for k, zs in comps.items()}
    lead = min(k for k, v in best.items() if v == max(best.values()))
    want = best[lead] - statistics.median(v for k, v in best.items() if k != lead)
    (atom,) = peer_atoms(hm.view(anomalies=tuple(data.draw(st.permutations(rows)))), 2)
    assert (atom["value"], atom["component"]) == (want, lead) and cast(float, atom["value"]) >= 0


# --- log atoms ----------------------------------------------------------------------------------
def _logs(hm: Any, **fields: Any) -> Any:
    templates = (
        hm.template("a", "T00000001", 0, 5, error=True),  # new error template
        hm.template("a", "T00000002", 0, 3),  # new, not an error
        hm.template("a", "T00000003", 0, 2, error=True),  # new but below min_count 3
        hm.template("a", "T00000004", 60, 120, error=True),  # old error template
    )
    return hm.view(templates=templates, **fields)


def test_new_template_counts_with_and_without_the_error_filter(hm: Any) -> None:
    atoms = _by(log_atoms(_logs(hm), 3))
    every = atoms["a", '{"error_level_only":false,"min_count":3,"window":"incident"}']
    errors = atoms["a", '{"error_level_only":true,"min_count":3,"window":"incident"}']
    assert (every["value"], every["refs"], every["unit"]) == (2.0, ["T00000001", "T00000002"], "count")
    assert (errors["value"], errors["refs"]) == (1.0, ["T00000001"])
    assert {a["candidate"] for a in atoms.values()} == {"a"}  # b and c have no templates: no atom


def test_error_rate_is_incident_minus_baseline_lines_per_second(hm: Any) -> None:
    (rate,) = [a for a in log_atoms(_logs(hm), 3) if a["kind"] == "log_error_rate"]
    # errors: incident 5 + 2 + 120 = 127 lines, baseline 60 lines, both windows 600 s.
    assert rate["value"] == pytest.approx(127 / 600 - 60 / 600)
    assert (rate["unit"], rate["refs"]) == ("lines/s", ["T00000001", "T00000003", "T00000004"])


def test_no_log_atoms_without_logs_or_with_an_empty_window(hm: Any) -> None:
    no_logs = models.Sources(metrics=True, logs=False, traces=True, events=True)
    assert log_atoms(_logs(hm, sources=no_logs), 3) == []
    empty = dataclasses.replace(_logs(hm), w_base=(0, 0))
    assert [a["kind"] for a in log_atoms(empty, 3)] == ["log_new_template", "log_new_template"]


_TEMPLATES = st.lists(st.tuples(st.integers(0, 10**6), st.integers(0, 10**6), st.booleans()), max_size=6)


@given(spec=_TEMPLATES, data=st.data())
def test_error_rate_is_the_exact_rate_difference_in_any_row_order(
    hm: Any, spec: list[tuple[int, int, bool]], data: st.DataObject
) -> None:
    rows = [hm.template("a", f"T{i:08d}", b, n, error=e) for i, (b, n, e) in enumerate(spec)]
    atoms = log_atoms(hm.view(templates=tuple(data.draw(st.permutations(rows)))), 3)
    assert atoms == log_atoms(hm.view(templates=tuple(rows)), 3)
    rates = [a for a in atoms if a["kind"] == "log_error_rate"]
    err = [t for t in rows if t.error_level]
    want = math.fsum(t.count_incident for t in err) / 600 - math.fsum(t.count_baseline for t in err) / 600
    assert [a["value"] for a in rates] == ([want] if rows else [])  # both windows are 600 s
    assert all(math.isfinite(cast(float, a["value"])) for a in atoms)
