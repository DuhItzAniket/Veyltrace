"""Unit and property tests of FaultLoom's input view (06 §2.1 shared values, 06 §6 absences)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.errors import ContractValidationError
from veyltrace_core.testing import make_context
from veyltrace_core.testing.fixtures import repo_root
from veyltrace_faultloom.inputs import (
    BOTH_PASS_TABLES,
    GraphNode,
    load_inputs,
    score_window,
    universe,
)

SYNTH_SERVICES = ("cart", "catalog", "checkout", "frontend", "payment", "recommend")
NODE_KINDS = ("service", "db", "cache", "queue", "external", "entry")
# 06 §6: tol_ns when alignment.json is absent (the config default, 15 s).
MISSING_TOL_NS = 15_000_000_000


def _example(name: str) -> Any:
    path = repo_root() / "contracts" / "examples" / f"{name}.example.json"
    return json.loads(path.read_text(encoding="utf-8"))


# --- universe U -------------------------------------------------------------------------------
def test_universe_adds_non_external_graph_nodes_sorted() -> None:
    nodes = [
        GraphNode("redis", "cache", False),
        GraphNode("card-gateway.example", "external", False),
        GraphNode("frontend", "entry", True),
    ]
    assert universe(["frontend", "cart"], nodes, include_external=False) == ("cart", "frontend", "redis")


def test_universe_includes_external_only_when_configured() -> None:
    nodes = [GraphNode("card-gateway.example", "external", False)]
    assert universe(["cart"], nodes, include_external=True) == ("card-gateway.example", "cart")
    assert universe(["cart"], nodes, include_external=False) == ("cart",)


_names = st.sampled_from(("a", "b", "cart", "cart-0", "frontend", "Zed", "é-svc", "payment"))
_nodes = st.lists(
    st.builds(GraphNode, node=_names, kind=st.sampled_from(NODE_KINDS), is_entry=st.booleans()), max_size=8
)


@given(services=st.lists(_names, max_size=8), nodes=_nodes, include_external=st.booleans(), data=st.data())
def test_universe_is_the_06_set_rule_and_order_free(
    services: list[str], nodes: list[GraphNode], include_external: bool, data: st.DataObject
) -> None:
    got = universe(services, nodes, include_external=include_external)
    expected = set(services) | {n.node for n in nodes if include_external or n.kind != "external"}
    assert got == tuple(sorted(expected))
    assert list(got) == sorted(set(got))  # sorted A→Z and unique
    shuffled_services = data.draw(st.permutations(services))
    shuffled_nodes = data.draw(st.permutations(nodes))
    assert universe(shuffled_services, shuffled_nodes, include_external=include_external) == got


# --- W_score ----------------------------------------------------------------------------------
def test_score_window_inside_incident() -> None:
    assert score_window(100, (0, 1_000), 300) == (100, 400)
    assert score_window(900, (0, 1_000), 300) == (900, 1_000)  # min(t_onset + score, end of W_inc)


def test_score_window_clamps_an_onset_outside_the_incident_window() -> None:
    # 06 §3.9: t_onset outside W_inc -> W_score clamped to W_inc, atoms still emitted.
    assert score_window(-50, (0, 1_000), 300) == (0, 250)
    assert score_window(5_000, (0, 1_000), 300) == (1_000, 1_000)


_ns = st.integers(min_value=-(10**12), max_value=10**12)


@given(t_onset=_ns, start=_ns, length=st.integers(min_value=0, max_value=10**12), score=_ns.map(abs))
def test_score_window_stays_inside_the_incident_window(
    t_onset: int, start: int, length: int, score: int
) -> None:
    w_inc = (start, start + length)
    lo, hi = score_window(t_onset, w_inc, score)
    assert w_inc[0] <= lo <= hi <= w_inc[1]
    if w_inc[0] <= t_onset <= w_inc[1]:
        assert lo == t_onset
        assert hi == min(t_onset + score, w_inc[1])


# --- load_inputs on fixture run dirs ------------------------------------------------------------
def test_load_inputs_reads_every_input_of_synth_01(main_dir: Path) -> None:
    ctx = make_context("faultloom", main_dir)
    view = load_inputs(ctx)
    alert = io.read_model("alert", main_dir, models.Alert)
    onsets = io.read_model("onsets", main_dir, models.Onsets)
    alignment = io.read_model("alignment", main_dir, models.Alignment)
    assert view.case_id == ctx.case_id
    assert view.universe == SYNTH_SERVICES  # graph.nodes holds no extra non-external node yet
    assert set(view.rows) == set(BOTH_PASS_TABLES)
    assert view.absent == () and view.notes == ()
    assert view.tol_ns == alignment.tolerance_ns
    assert view.w_base == alert.windows.baseline
    assert view.w_inc == alert.windows.incident
    assert view.w_score == score_window(onsets.t_onset_ns, view.w_inc, 300_000 * 1_000_000)


def test_load_inputs_reads_window_score_ms_from_config(main_dir: Path) -> None:
    short = load_inputs(make_context("faultloom", main_dir, overrides={"faultloom.window.score_ms": 60_000}))
    default = load_inputs(make_context("faultloom", main_dir))
    assert short.w_score[0] == default.w_score[0]
    assert short.w_score[1] == min(short.w_score[0] + 60_000 * 1_000_000, short.w_inc[1])


def test_missing_alignment_falls_back_to_the_configured_tolerance(main_dir: Path) -> None:
    io.path_of("alignment", main_dir).unlink()
    view = load_inputs(make_context("faultloom", main_dir))
    assert view.tol_ns == MISSING_TOL_NS
    assert "alignment" in view.absent
    assert any("alignment absent" in note for note in view.notes)
    over = load_inputs(
        make_context("faultloom", main_dir, overrides={"faultloom.alignment.missing_tolerance_ns": 30})
    )
    assert over.tol_ns == 30


@pytest.mark.parametrize("name", ["changes", "graph.edges", "signal_cube.series", "signal_cube.templates"])
def test_absent_optional_tables_are_listed_not_fatal(main_dir: Path, name: str) -> None:
    io.path_of(name, main_dir).unlink()
    view = load_inputs(make_context("faultloom", main_dir))
    assert name in view.absent and name not in view.rows


def test_graph_nodes_extend_the_universe_except_external(main_dir: Path) -> None:
    rows = [
        *_example("graph.nodes"),
        {"node": "card-gateway.example", "kind": "external", "is_entry": False, "provenance": ["traces"]},
    ]
    io.write("graph.nodes", rows, main_dir)
    view = load_inputs(make_context("faultloom", main_dir))
    assert view.universe == (*SYNTH_SERVICES[:2], "checkout", "frontend", "payment", "recommend", "redis")
    assert "card-gateway.example" in view.node_names
    with_ext = load_inputs(
        make_context("faultloom", main_dir, overrides={"core.universe.include_external": True})
    )
    assert "card-gateway.example" in with_ext.universe


def test_case_manifest_of_another_case_is_an_error(main_dir: Path) -> None:
    ctx = make_context("faultloom", main_dir, case_id="0" * 12)
    with pytest.raises(ContractValidationError, match="case_manifest"):
        load_inputs(ctx)
