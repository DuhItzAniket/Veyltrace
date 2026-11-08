"""Unit and property tests of the R-00 Causatrix stub (07 §2, §3.1 step 5, §4, §6).

The stub makes no algorithmic claim, so these tests pin what it may do: read the inputs, build U
(06 §2.1), list every service with the no-vote fused score 0.0, order candidates by the 07 §3.1
tie-break key and classify by the fallback rule only.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_causatrix import api
from veyltrace_causatrix.stub import (
    FALLBACK_FAULT_CLASS,
    FALLBACK_MODE,
    STUB_NOTE,
    ServiceFacts,
    Settings,
    build_slate,
    engine_atoms,
    order_universe,
    service_facts,
    settings_from,
    universe,
)
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.errors import ConfigError
from veyltrace_core.testing import fixture_run_dir, make_context

RANKERS = ("baro_rs", "change_prox", "cp_sbfl", "graph_walk", "nsigma", "prism_m")
K_ANOM = 3.0
CASE_ID = "59e0d31bcc42"


def _settings(k: int = 5, rankers: tuple[str, ...] = RANKERS, method: str = "rrf") -> Settings:
    return Settings(
        k=k,
        rankers=rankers,
        method=method,
        rrf_k=60,
        weights=tuple((r, 1.0) for r in rankers),
        fallback_indicator="unknown",
        k_anom=K_ANOM,
        include_external=False,
    )


def _cfg() -> dict[str, Any]:
    return {
        "slate": {"k": 5},
        "rankers": {"enabled": list(RANKERS)},
        "fusion": {"method": "rrf"},
        "rrf": {"k": 60, "weights": dict.fromkeys(RANKERS, 1.0)},
        "indicator_map": {"other": "unknown", "cpu": "cpu"},
    }


CORE: Mapping[str, Any] = {"thresholds": {"anomaly_z": 3.0}, "universe": {"include_external": False}}


def _row(
    candidate: str,
    kind: str,
    value: float,
    args: Mapping[str, Any],
    *,
    atom_id: str = "E0000000000",
    component: str | None = None,
    origin: str = "engine",
) -> dict[str, Any]:
    return {
        "atom_id": atom_id,
        "candidate": candidate,
        "component": component,
        "kind": kind,
        "args_json": json.dumps(args, sort_keys=True),
        "value": value,
        "origin": origin,
    }


def _robust(window: str = "incident") -> dict[str, str]:
    return {"detector": "robust_z", "family": "cpu", "source": "metrics", "window": window}


# --- configuration ------------------------------------------------------------------------------
def test_settings_from_repo_config_matches_spec_defaults(tmp_path: Path) -> None:
    run_dir = fixture_run_dir("synth-01", tmp_path, through="faultloom")
    ctx = make_context("causatrix", run_dir)
    s = settings_from(ctx.config, ctx.config.core)
    assert (s.k, s.rrf_k, s.method, s.fusion_k) == (5, 60, "rrf", 60)  # 07 §4 defaults
    assert s.rankers == RANKERS
    assert dict(s.weights) == dict.fromkeys(RANKERS, 1.0)
    assert s.fallback_indicator == "unknown"  # 07 §3.6: other -> unknown
    assert (s.k_anom, s.include_external) == (3.0, False)
    # Every 07 §4 key is declared, so ablation overrides can name it.
    for key in (
        "rrf.gate",
        "abstain_on_constant",
        "prism_m.combine",
        "prism_m.silence_z",
        "graph_walk.damping",
        "graph_walk.iterations",
        "graph_walk.self_loop",
        "mode.change_min_proximity",
        "mode.edge_gap_min_ms",
        "mode.tail_ratio",
    ):
        ctx.config.get_path(key)
    assert set(ctx.config["indicator_map"]) == {
        "cpu",
        "mem",
        "disk",
        "net",
        "latency",
        "self_time",
        "errors",
        "logs",
        "traffic",
        "other",
    }


def test_settings_fusion_k_is_null_for_methods_without_one() -> None:
    cfg = _cfg()
    cfg["fusion"]["method"] = "borda"
    assert settings_from(cfg, CORE).fusion_k is None


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("fusion", "method"), "votes", "fusion.method"),
        (("slate", "k"), 0, "slate.k"),
        (("slate", "k"), True, "slate.k"),
        (("rrf", "k"), 1.5, "rrf.k"),
        (("rankers", "enabled"), ["prism_m", "prism_m"], "twice"),
        (("rankers", "enabled"), "prism_m", "list"),
        (("rankers", "enabled"), ["prism_m", "extra"], "no weight"),
        (("indicator_map", "other"), None, "indicator_map.other"),
    ],
)
def test_settings_reject_bad_config(path: tuple[str, str], value: object, match: str) -> None:
    cfg = _cfg()
    cfg[path[0]][path[1]] = value
    with pytest.raises(ConfigError, match=match):
        settings_from(cfg, CORE)


def test_settings_missing_key_is_a_config_error() -> None:
    cfg = _cfg()
    del cfg["rrf"]["weights"]
    with pytest.raises(ConfigError, match=r"causatrix\.rrf\.weights"):
        settings_from(cfg, CORE)


def test_rankers_are_sorted_and_weights_follow_enabled_only() -> None:
    cfg = _cfg()
    cfg["rankers"]["enabled"] = ["prism_m", "baro_rs"]
    s = settings_from(cfg, CORE)
    assert s.rankers == ("baro_rs", "prism_m")
    assert dict(s.weights) == {"baro_rs": 1.0, "prism_m": 1.0}


# --- universe -----------------------------------------------------------------------------------
def test_universe_is_services_plus_non_external_nodes_sorted() -> None:
    nodes = [("redis", "cache"), ("card-gateway.example", "external"), ("frontend", "entry")]
    assert universe(["payment", "frontend"], nodes, include_external=False) == (
        "frontend",
        "payment",
        "redis",
    )
    assert universe(["payment"], nodes, include_external=True) == (
        "card-gateway.example",
        "frontend",
        "payment",
        "redis",
    )
    assert universe([], [], include_external=False) == ()


# --- evidence -----------------------------------------------------------------------------------
def test_engine_atoms_ignore_claim_checks_and_parse_args() -> None:
    rows = [
        _row("b", "internal_anomaly", 4.0, _robust(), atom_id="E0000000002"),
        _row("a", "claim_check", 1.0, {"k": 3.0}, origin="claim_check"),
        _row("a", "internal_anomaly", 5.0, _robust(), atom_id="E0000000001"),
    ]
    atoms = engine_atoms(rows)
    assert [a.candidate for a in atoms] == ["a", "b"]
    assert atoms[0].args["detector"] == "robust_z"


def test_service_facts_from_atoms() -> None:
    atoms = engine_atoms(
        [
            _row("a", "internal_anomaly", 9.0, _robust(), atom_id="E0000000002", component="a-0"),
            _row("a", "internal_anomaly", 9.0, _robust("onset"), atom_id="E0000000001", component="a-1"),
            _row("a", "internal_anomaly", 50.0, {**_robust(), "detector": "nsigma"}, atom_id="E0000000003"),
            _row("a", "onset_precedence", 120.0, {"scope": "self", "window": "onset"}, atom_id="E1"),
            _row("a", "onset_precedence", 5.0, {"scope": "dependents", "window": "onset"}, atom_id="E2"),
            _row("b", "external_anomaly", 4.0, _robust(), component="b-0"),
            _row("c", "external_anomaly", 4.0, _robust(), component=None),
            _row("zz", "internal_anomaly", 7.0, _robust()),  # not in U: ignored
        ]
    )
    facts = service_facts(atoms, ["a", "b", "c", "d"])
    assert sorted(facts) == ["a", "b", "c", "d"]
    # I(a) is the robust_z max (nsigma atoms do not count); topI tie goes to the smaller atom_id.
    assert facts["a"] == ServiceFacts(internal=9.0, onset_ms=120.0, component="a-1")
    # No internal atom: component from topE.
    assert facts["b"] == ServiceFacts(internal=0.0, onset_ms=math.inf, component="b-0")
    assert facts["c"].component is None
    assert facts["d"] == ServiceFacts()


# --- ordering and slate -------------------------------------------------------------------------
def test_order_universe_tie_break_internal_first_then_onset_then_name() -> None:
    facts = {
        "a": ServiceFacts(),
        "b": ServiceFacts(internal=3.0, onset_ms=50.0),
        "c": ServiceFacts(internal=8.0, onset_ms=10.0),
        "d": ServiceFacts(internal=2.9, onset_ms=1.0),
    }
    fused = dict.fromkeys(facts, 0.0)
    assert order_universe(facts, fused, facts, K_ANOM) == ("c", "b", "d", "a")


def test_order_universe_fused_score_dominates() -> None:
    facts = {"a": ServiceFacts(), "b": ServiceFacts(internal=9.0)}
    assert order_universe(facts, {"a": 0.5, "b": 0.1}, facts, K_ANOM) == ("a", "b")


def test_build_slate_is_stub_honest_and_schema_valid() -> None:
    members = ("cart", "catalog", "checkout", "frontend", "payment", "recommend")
    facts = {s: ServiceFacts() for s in members}
    slate = build_slate(CASE_ID, members, facts, _settings(k=5))
    io.prepare("slate", slate)  # schema and x-sort orders
    assert slate["rankers_active"] == []
    assert slate["fusion"] == {"method": "rrf", "k": 60, "weights": dict.fromkeys(RANKERS, 1.0)}
    assert [c["service"] for c in slate["candidates"]] == list(members[:5])
    assert [c["rank"] for c in slate["candidates"]] == [1, 2, 3, 4, 5]
    for c in slate["candidates"]:
        assert (c["mode"], c["fault_class"], c["indicator"]) == (
            FALLBACK_MODE,
            FALLBACK_FAULT_CLASS,
            "unknown",
        )
        assert c["fused_score"] == 0.0
        assert c["ranker_ranks"] == dict.fromkeys(RANKERS)
        assert c["ranker_scores"] == dict.fromkeys(RANKERS)
    assert slate["all_scores"] == [{"service": s, "fused_score": 0.0} for s in members]


def test_build_slate_fewer_services_than_k_and_empty_universe() -> None:
    slate = build_slate(CASE_ID, ("a", "b"), {}, _settings(k=5))
    assert [c["service"] for c in slate["candidates"]] == ["a", "b"]
    assert slate["k"] == 5  # 07 §3.8: k records the configured K
    empty = build_slate(CASE_ID, (), {}, _settings())
    io.prepare("slate", empty)
    assert (empty["candidates"], empty["all_scores"]) == ([], [])


# --- properties ---------------------------------------------------------------------------------
_names = st.from_regex(r"[a-z][a-z0-9-]{0,6}", fullmatch=True)
_values = st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)


@st.composite
def _cases(draw: st.DrawFn) -> tuple[list[str], list[dict[str, Any]]]:
    services = draw(st.lists(_names, min_size=0, max_size=8, unique=True))
    rows: list[dict[str, Any]] = []
    for i, service in enumerate(services):
        if draw(st.booleans()):
            kind = draw(st.sampled_from(["internal_anomaly", "external_anomaly"]))
            rows.append(_row(service, kind, draw(_values), _robust(), atom_id=f"E{i:010d}"))
        if draw(st.booleans()):
            args = {"scope": "self", "window": "onset"}
            rows.append(_row(service, "onset_precedence", draw(_values), args, atom_id=f"E{i + 100:010d}"))
    return services, rows


@given(case=_cases(), k=st.integers(min_value=1, max_value=10), data=st.data())
def test_slate_properties(case: tuple[list[str], list[dict[str, Any]]], k: int, data: st.DataObject) -> None:
    services, rows = case
    settings = _settings(k=k)

    def slate_of(svcs: list[str], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        members = universe(svcs, [], include_external=False)
        return build_slate(CASE_ID, members, service_facts(engine_atoms(evidence), members), settings)

    slate = slate_of(services, rows)
    io.prepare("slate", slate)
    # Every service in U gets a fused score, exactly once (07 AGENTS Never 4).
    assert sorted(e["service"] for e in slate["all_scores"]) == sorted(services)
    # Candidates are the first min(k, |U|) of U, ranked 1..n, no ranker votes.
    assert len(slate["candidates"]) == min(k, len(services))
    assert [c["rank"] for c in slate["candidates"]] == list(range(1, len(slate["candidates"]) + 1))
    assert all(set(c["ranker_ranks"]) == set(RANKERS) for c in slate["candidates"])
    # Internal-anomaly services (I >= k_anom) come before the others.
    facts = service_facts(engine_atoms(rows), services)
    flags = [facts[c["service"]].internal >= K_ANOM for c in slate["candidates"]]
    assert flags == sorted(flags, reverse=True)
    # Invariant to the order of input rows and of manifest services.
    perm_rows = data.draw(st.permutations(rows))
    perm_services = data.draw(st.permutations(services))
    assert slate_of(list(perm_services), list(perm_rows)) == slate


@given(case=_cases())
def test_ignoring_claim_check_rows(case: tuple[list[str], list[dict[str, Any]]]) -> None:
    services, rows = case
    claims = [
        _row(s, "claim_check", 99.0, _robust(), atom_id=f"E{i + 500:010d}", origin="claim_check")
        for i, s in enumerate(services)
    ]
    assert engine_atoms(rows + claims) == engine_atoms(rows)


# --- engine -------------------------------------------------------------------------------------
def test_run_writes_slate_over_universe(tmp_path: Path) -> None:
    run_dir = fixture_run_dir("synth-01", tmp_path, through="faultloom")
    ctx = make_context("causatrix", run_dir)
    result = api.run(ctx)
    assert result.status == "ok"
    assert result.notes == (STUB_NOTE,)
    assert [name for name, _ in result.outputs] == ["slate"]
    slate = io.read_model("slate", run_dir, models.Slate)
    manifest = io.read_model("case_manifest", run_dir, models.CaseManifest)
    assert slate.case_id == manifest.case_id
    assert [e.service for e in slate.all_scores] == sorted(manifest.services)
    assert result.metrics["universe"] == len(slate.all_scores)


@pytest.mark.parametrize("absent", ["evidence", "graph.nodes"])
def test_run_fails_without_required_input(tmp_path: Path, absent: str) -> None:
    run_dir = fixture_run_dir("synth-01", tmp_path, through="faultloom")
    io.path_of(absent, run_dir).unlink()
    result = api.run(make_context("causatrix", run_dir))
    assert result.status == "failed"
    assert not io.exists("slate", run_dir)


def test_run_without_graph_edges_still_writes(tmp_path: Path) -> None:
    run_dir = fixture_run_dir("synth-01", tmp_path, through="faultloom")
    io.path_of("graph.edges", run_dir).unlink()
    result = api.run(make_context("causatrix", run_dir))
    assert result.status == "ok"
    assert result.metrics["graph_edges_in_u"] == 0


def test_run_honours_slate_k_override(tmp_path: Path) -> None:
    run_dir = fixture_run_dir("synth-01", tmp_path, through="faultloom")
    ctx = make_context("causatrix", run_dir, overrides={"causatrix.slate.k": 2})
    assert api.run(ctx).status == "ok"
    slate = io.read_model("slate", run_dir, models.Slate)
    assert slate.k == 2
    assert len(slate.candidates) == 2
