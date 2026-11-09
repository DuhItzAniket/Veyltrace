"""Unit tests of the trace edges and the edges.* config (05-causalith §3.4, §4, §7)."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import pyarrow as pa
import pytest

from veyltrace_causalith.graph import trace_edges
from veyltrace_causalith.settings import causalith_config
from veyltrace_core import io
from veyltrace_core.config import load_section_file
from veyltrace_core.errors import ConfigError

CFG = causalith_config(load_section_file("causalith"))
RULES = CFG.edges
QUANTILES = ("p50_caller_ms", "p99_caller_ms", "p50_callee_ms", "p99_callee_ms", "p50_gap_ms", "p99_gap_ms")


def _edge(
    caller: str, callee: str, window: str, calls: int, error_rate: float = 0.0, **q: float
) -> dict[str, Any]:
    return {
        "caller": caller,
        "callee": callee,
        "window": window,
        "calls": calls,
        "error_rate": error_rate,
        **dict.fromkeys(QUANTILES),
        **q,
    }


def _edges(rows: list[dict[str, Any]]) -> pa.Table:
    table = pa.Table.from_pylist(rows, schema=io.arrow_schema("signal_cube.edges"))
    return io.conform_table("signal_cube.edges", table)


def test_defaults_match_the_spec_table() -> None:
    assert (
        RULES.latency_ratio,
        RULES.latency_min_ms,
        RULES.error_delta,
        RULES.silence_min_baseline_calls,
    ) == (0.5, 5.0, 0.05, 10)


def test_weights_are_incident_call_shares_else_baseline_shares() -> None:
    edges = trace_edges(
        _edges(
            [
                _edge("a", "b", "incident", 30),
                _edge("a", "c", "incident", 10),
                _edge("a", "c", "baseline", 5),
                _edge("x", "y", "baseline", 4),
                _edge("x", "z", "baseline", 12),
            ]
        ),
        RULES,
    )
    assert edges["a", "b"].weight == 0.75 and edges["a", "c"].weight == 0.25
    assert edges["x", "y"].weight == 0.25 and edges["x", "z"].weight == 0.75
    assert (edges["a", "b"].calls_incident, edges["x", "y"].calls_incident) == (30, 0)
    assert all(e.provenance == {"traces"} for e in edges.values())


@pytest.mark.parametrize(
    ("baseline", "incident", "anomalous"),
    [
        ({"p99_callee_ms": 10.0}, {"p99_callee_ms": 16.0}, True),  # 1.6x and +6 ms
        ({"p99_callee_ms": 10.0}, {"p99_callee_ms": 14.0}, False),  # 1.4x
        ({"p99_callee_ms": 2.0}, {"p99_callee_ms": 6.0}, False),  # 3x but only +4 ms
        ({"p99_gap_ms": 4.0}, {"p99_gap_ms": 12.0}, True),  # the same test on the gap
        ({"p99_callee_ms": None}, {"p99_callee_ms": 50.0}, False),  # no baseline quantile
        ({"error_rate": 0.01}, {"error_rate": 0.07}, True),  # +6 points
        ({"error_rate": 0.01}, {"error_rate": 0.05}, False),
        ({"calls": 10}, None, True),  # went silent
        ({"calls": 9}, None, False),  # too few baseline calls to call it silent
        (None, {"error_rate": 0.05}, True),  # new edge with errors
        (None, {"error_rate": 0.0}, False),
    ],
)
def test_edge_anomaly_rules(
    baseline: dict[str, Any] | None, incident: dict[str, Any] | None, anomalous: bool
) -> None:
    rows: list[dict[str, Any]] = []
    if baseline is not None:
        calls = baseline.pop("calls", 20)
        rows.append(_edge("a", "b", "baseline", calls, **baseline))
    if incident is not None:
        rows.append(_edge("a", "b", "incident", 20, **incident))
    assert trace_edges(_edges(rows), RULES)["a", "b"].anomalous is anomalous


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    return value


@pytest.mark.parametrize(
    ("key", "value"),
    [("anom_latency_ratio", -0.1), ("anom_error_delta", "x"), ("silence_min_baseline_calls", 0)],
)
def test_malformed_edge_keys_are_config_errors(key: str, value: object) -> None:
    section = copy.deepcopy(_thaw(load_section_file("causalith")))
    section["edges"][key] = value
    with pytest.raises(ConfigError):
        causalith_config(section)


def test_static_topology_is_off_and_rejected_until_supported() -> None:
    """05 §4: `topology.static_path` defaults to null; a set path fails loudly instead of being ignored."""
    section = copy.deepcopy(_thaw(load_section_file("causalith")))
    assert section["topology"]["static_path"] is None
    section["topology"]["static_path"] = "topology/static.yaml"
    with pytest.raises(ConfigError, match="static_path"):
        causalith_config(section)
