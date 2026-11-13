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
    assert anomara_config(SECTION).grid.bucket_ns == 10 * NS_PER_S


def test_grid_bucket_matches_signalyth_when_it_declares_one() -> None:
    signalyth: Any = load_section_file("signalyth")
    buckets = signalyth.get("buckets")
    if buckets is None:
        pytest.skip("config/signalyth.yaml has no buckets.* keys yet (O-02)")
    expected = anomara_config(SECTION).grid.bucket_ns
    assert expected == buckets["traces_s"] * NS_PER_S == buckets["logs_s"] * NS_PER_S


@pytest.mark.parametrize(
    ("path", "value"),
    [(("grid", "bucket_s"), 0), (("grid", "bucket_s"), 1.5), (("grid", "bucket_s"), True), (("grid",), None)],
)
def test_malformed_values_are_config_errors(path: tuple[str, ...], value: object) -> None:
    section = copy.deepcopy(SECTION)
    node = section
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(ConfigError):
        anomara_config(section)
