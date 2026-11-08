"""config/faultloom.yaml declares every key of 06 §4 with the spec's default and shape."""

from __future__ import annotations

from typing import Any

import pytest

from veyltrace_core.config import load_config

#: 06 §4 table (key -> default), plus the 06 §9 `atoms.disabled` ablation and the 06 §6
#: missing-alignment tolerance.
SPEC_DEFAULTS: dict[str, Any] = {
    "atoms.detectors": ("robust_z", "nsigma", "silence"),
    "atoms.disabled": (),
    "window.score_ms": 300000,
    "self_time.quantile": "p50",
    "self_time.min_total_increase_ms": 5.0,
    "spectrum.formula": "ochiai",
    "spectrum.weighting": "critical_path",
    "templates.min_count": 3,
    "peer.min_components": 2,
    "edge_gap.min_calls": 10,
    "cards.max_tokens": 1500,
    "cards.bytes_per_token": 4,
    "cards.k_default": 6,
    "intervention.max_candidates": 5,
    "alignment.missing_tolerance_ns": 15_000_000_000,
}

#: 06 §3.5 parameter ranges (inclusive), kept in the config lock.
PREDICATE_RANGES: dict[str, tuple[float, float]] = {
    "change_before_onset.max_ms": (0.0, 86400000.0),
    "error_rate_above.x": (0.0, 1.0),
    "on_critical_path.min_share": (0.0, 1.0),
    "peer_gap_above.x": (0.0, 100.0),
    "self_time_share_above.x": (0.0, 1.0),
    "template_new_in_incident.min_count": (1, 1000000),
    "zscore_above.k": (1.0, 100.0),
}


@pytest.mark.parametrize(("key", "default"), sorted(SPEC_DEFAULTS.items()))
def test_spec_key_has_its_default(key: str, default: Any) -> None:
    value = load_config("faultloom").get_path(key, None)
    if isinstance(default, tuple):
        assert tuple(value) == default
    else:
        assert value == default and type(value) is type(default)


@pytest.mark.parametrize(("key", "bounds"), sorted(PREDICATE_RANGES.items()))
def test_predicate_ranges_are_kept(key: str, bounds: tuple[float, float]) -> None:
    rng = load_config("faultloom").get_path(f"predicates.{key}", None)
    assert (rng["min"], rng["max"]) == bounds
    assert type(rng["min"]) is type(bounds[0])


def test_ablation_overrides_name_declared_keys() -> None:
    cfg = load_config(
        "faultloom", {"faultloom.spectrum.weighting": "none", "faultloom.atoms.disabled": ["spectrum"]}
    )
    assert cfg.get_path("spectrum.weighting", None) == "none"
    assert tuple(cfg.get_path("atoms.disabled", None)) == ("spectrum",)
