"""Tests of the Causatrix configuration (07 §4): every key is read, typed and validated."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from veyltrace_causatrix import api
from veyltrace_causatrix.config import FAMILIES, config_from
from veyltrace_core.config import load_section_file
from veyltrace_core.errors import ConfigError
from veyltrace_core.testing import fixture_run_dir, make_context

RANKERS = ("baro_rs", "change_prox", "cp_sbfl", "graph_walk", "nsigma", "prism_m")


def _thaw(value: object) -> Any:
    """A mutable deep copy of a frozen config tree."""
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in cast(Mapping[str, object], value).items()}
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [_thaw(v) for v in cast(Sequence[object], value)]
    return value


def _sections() -> tuple[dict[str, Any], dict[str, Any]]:
    return _thaw(load_section_file("causatrix")), _thaw(load_section_file("core"))


def test_repo_config_matches_the_spec_defaults(tmp_path: Path) -> None:
    ctx = make_context("causatrix", fixture_run_dir("synth-01", tmp_path, through="faultloom"))
    c = config_from(ctx.config, ctx.config.core)
    assert (c.k, c.rankers, c.method, c.rrf_k, c.fusion_k) == (5, RANKERS, "rrf", 60, 60)
    assert dict(c.weights) == dict.fromkeys(RANKERS, 1.0)
    assert (c.gate, c.abstain_on_constant, c.prism_combine, c.silence_z) == (True, True, "add", 10.0)
    assert (c.damping, c.iterations, c.self_loop) == (0.85, 200, True)
    assert (c.change_min_proximity, c.edge_gap_min_ms, c.tail_ratio) == (0.36787944, 5.0, 0.5)
    assert (c.k_anom, c.include_external) == (3.0, False)
    # 07 §3.6: the indicator vocabulary, with self_time -> latency and other -> unknown.
    assert dict(c.indicator_map) == {
        "cpu": "cpu",
        "disk": "diskio",
        "errors": "error",
        "latency": "latency",
        "logs": "logs",
        "mem": "mem",
        "net": "socket",
        "other": "unknown",
        "self_time": "latency",
        "traffic": "workload",
    }
    assert c.indicator("disk") == "diskio"
    assert c.weight("prism_m") == 1.0


def test_fusion_k_is_null_for_methods_without_one() -> None:
    cfg, core = _sections()
    cfg["fusion"]["method"] = "borda"
    assert config_from(cfg, core).fusion_k is None


def test_rankers_are_sorted_and_weights_follow_enabled_only() -> None:
    cfg, core = _sections()
    cfg["rankers"]["enabled"] = ["prism_m", "baro_rs"]
    c = config_from(cfg, core)
    assert c.rankers == ("baro_rs", "prism_m")
    assert dict(c.weights) == {"baro_rs": 1.0, "prism_m": 1.0}


@pytest.mark.parametrize(
    ("dotted", "value", "match"),
    [
        ("slate.k", 0, r"causatrix\.slate\.k"),
        ("slate.k", True, r"causatrix\.slate\.k"),
        ("rankers.enabled", ["prism_m", "prism_m"], "twice"),
        ("rankers.enabled", "prism_m", "list"),
        ("rankers.enabled", ["Prism-M"], "snake-case"),
        ("rankers.enabled", ["prism_m", "extra"], "no weight"),
        ("fusion.method", "votes", r"causatrix\.fusion\.method"),
        ("rrf.k", 1.5, r"causatrix\.rrf\.k"),
        ("rrf.weights.prism_m", -1.0, r"causatrix\.rrf\.weights\.prism_m"),
        ("rrf.weights.prism_m", float("nan"), r"causatrix\.rrf\.weights\.prism_m"),
        ("rrf.gate", "yes", r"causatrix\.rrf\.gate"),
        ("abstain_on_constant", 1, r"causatrix\.abstain_on_constant"),
        ("prism_m.combine", "mul", r"causatrix\.prism_m\.combine"),
        ("prism_m.silence_z", -1.0, r"causatrix\.prism_m\.silence_z"),
        ("graph_walk.damping", 1.5, r"causatrix\.graph_walk\.damping"),
        ("graph_walk.iterations", 0, r"causatrix\.graph_walk\.iterations"),
        ("graph_walk.self_loop", None, r"causatrix\.graph_walk\.self_loop"),
        ("mode.change_min_proximity", 2.0, r"causatrix\.mode\.change_min_proximity"),
        ("mode.edge_gap_min_ms", "5", r"causatrix\.mode\.edge_gap_min_ms"),
        ("mode.tail_ratio", -0.1, r"causatrix\.mode\.tail_ratio"),
        ("indicator_map.cpu", "processor", r"causatrix\.indicator_map\.cpu"),
    ],
)
def test_bad_values_name_their_key(dotted: str, value: object, match: str) -> None:
    cfg, core = _sections()
    *parents, leaf = dotted.split(".")
    node = cfg
    for part in parents:
        node = node[part]
    node[leaf] = value
    with pytest.raises(ConfigError, match=match):
        config_from(cfg, core)


def test_every_rrf_weight_is_validated_even_for_a_ranker_left_out() -> None:
    # 07 §9 leave-one-ranker-out: the dropped ranker's weight is still checked (#109 review).
    for bad in (-1, "abc", None):
        cfg, core = _sections()
        cfg["rankers"]["enabled"] = [r for r in RANKERS if r != "nsigma"]
        cfg["rrf"]["weights"]["nsigma"] = bad
        with pytest.raises(ConfigError, match=r"causatrix\.rrf\.weights\.nsigma"):
            config_from(cfg, core)
    cfg, core = _sections()
    cfg["rrf"]["weights"]["Bad-Name"] = 1.0
    with pytest.raises(ConfigError, match="snake-case"):
        config_from(cfg, core)


def test_rrf_weights_must_be_a_mapping_even_with_no_ranker_enabled() -> None:
    cfg, core = _sections()
    cfg["rankers"]["enabled"], cfg["rrf"]["weights"] = [], 5
    with pytest.raises(ConfigError, match=r"causatrix\.rrf\.weights must be a mapping"):
        config_from(cfg, core)


def test_indicator_map_must_cover_every_family() -> None:
    cfg, core = _sections()
    del cfg["indicator_map"]["traffic"]
    with pytest.raises(ConfigError, match="families"):
        config_from(cfg, core)
    cfg["indicator_map"] = dict.fromkeys([*FAMILIES, "extra"], "unknown")
    with pytest.raises(ConfigError, match="families"):
        config_from(cfg, core)


@pytest.mark.parametrize(
    ("section", "dotted", "match"),
    [
        ("causatrix", "rrf.weights", r"causatrix\.rrf\.weights"),
        ("causatrix", "graph_walk.damping", r"causatrix\.graph_walk\.damping"),
        ("core", "thresholds.anomaly_z", r"core\.thresholds\.anomaly_z"),
    ],
)
def test_missing_key_is_a_config_error(section: str, dotted: str, match: str) -> None:
    cfg, core = _sections()
    *parents, leaf = dotted.split(".")
    node = cfg if section == "causatrix" else core
    for part in parents:
        node = node[part]
    del node[leaf]
    with pytest.raises(ConfigError, match=match):
        config_from(cfg, core)


def test_core_values_are_validated() -> None:
    cfg, core = _sections()
    core["universe"]["include_external"] = "no"
    with pytest.raises(ConfigError, match=r"core\.universe\.include_external"):
        config_from(cfg, core)


def test_engine_run_rejects_a_bad_key_even_if_the_stub_does_not_use_it(tmp_path: Path) -> None:
    run_dir = fixture_run_dir("synth-01", tmp_path, through="faultloom")
    ctx = make_context("causatrix", run_dir, overrides={"causatrix.graph_walk.damping": 2.0})
    with pytest.raises(ConfigError, match=r"causatrix\.graph_walk\.damping"):
        api.run(ctx)
