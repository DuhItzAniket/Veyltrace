"""Tests of the typed Anomara config view (03-anomara §4)."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import pytest

from veyltrace_anomara.settings import NS_PER_S, anomara_config
from veyltrace_core.config import load_section_file
from veyltrace_core.errors import ConfigError


def _thaw(value: Any) -> Any:
    """A mutable copy of a frozen config tree (mappingproxy and tuples)."""
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


SECTION: dict[str, Any] = _thaw(load_section_file("anomara"))


def test_defaults_match_the_spec_table() -> None:
    cfg = anomara_config(SECTION)
    rz = cfg.robust_z
    assert cfg.grid.bucket_ns == 10 * NS_PER_S
    assert (rz.mad_factor, rz.iqr_divisor, rz.eta, rz.persist_steps) == (1.4826, 1.349, 0.02, 3)
    assert (rz.threshold, rz.min_baseline_steps) == (3.0, 5)


@pytest.mark.parametrize(
    ("family", "unit", "eps"),
    [
        ("cpu", "cores", 0.001),
        ("cpu", "s/s", 0.1),
        ("mem", "bytes", 1048576.0),
        ("mem", "MB", 1e-6),  # unlisted unit and no family "*": the other."*" fallback
        ("latency", "ms", 1.0),
        ("errors", "ratio", 0.01),
        ("errors", None, 0.1),
        ("traffic", "1/s", 0.1),
        ("logs", "count", 1.0),
        ("disk", "bytes/s", 1.0),
        ("other", "x", 1e-6),
        ("unknown-family", "ms", 1e-6),
    ],
)
def test_epsilon_lookup(family: str, unit: str | None, eps: float) -> None:
    assert anomara_config(SECTION).robust_z.epsilon_for(family, unit) == eps


def test_grid_bucket_matches_signalyth_when_it_declares_one() -> None:
    signalyth: Any = load_section_file("signalyth")
    buckets = signalyth.get("buckets")
    if buckets is None:
        pytest.skip("config/signalyth.yaml has no buckets.* keys yet (O-02)")
    expected = anomara_config(SECTION).grid.bucket_ns
    assert expected == buckets["traces_s"] * NS_PER_S
    # `buckets.logs_s` (02-signalyth §4) arrives with the log series (O-03); check it once declared
    if "logs_s" in buckets:
        assert expected == buckets["logs_s"] * NS_PER_S


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("grid", "bucket_s"), 0),
        (("grid", "bucket_s"), 1.5),
        (("grid", "bucket_s"), True),
        (("grid",), None),
        (("robust_z", "threshold"), "3"),
        (("robust_z", "eta"), -0.1),
        (("robust_z", "persist_steps"), 1.5),
        (("robust_z", "epsilon", "cpu", "cores"), 0.0),
        (("robust_z", "epsilon", "other"), {"ms": 1.0}),
        (("onset", "bocpd_max_lead_s"), 0),
        (("t_onset", "clamp_s"), [60, 300]),
        (("t_onset", "clamp_s"), [-60]),
        (("nsigma", "threshold"), 0),
        (("silence", "zero_signals"), "rps"),
        (("silence", "min_baseline_coverage"), 1.5),
        (("bocpd", "lambda"), 1),
        (("bocpd", "threshold"), 0.0),
        (("bocpd", "prior", "mu0"), "x"),
    ],
)
def test_malformed_values_are_config_errors(path: tuple[str, ...], value: object) -> None:
    section = copy.deepcopy(SECTION)
    node = section
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(ConfigError):
        anomara_config(section)
