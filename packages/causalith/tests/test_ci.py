"""Unit tests of the CI test's building blocks (05-causalith §3.7 steps 1–5, §7)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from veyltrace_causalith import ci
from veyltrace_causalith.ci import CI_API_VERSION, CIConfig
from veyltrace_core.config import load_section_file
from veyltrace_core.errors import ConfigError

CFG = CIConfig.from_sections(load_section_file("causalith"), load_section_file("anomara"))
NS = 1_000_000_000


def _s(sid: str, t: list[int], x: list[float]) -> Any:
    service, _, signal, source = sid.split("|")
    return ci.CISeries(sid, service, signal, "latency", source, "ms", np.asarray(t, dtype=np.int64),
                      np.asarray(x, dtype=np.float64))  # fmt: skip


def test_config_defaults_and_the_anomara_floor_terms() -> None:
    assert (CFG.max_parents, CFG.ridge, CFG.min_baseline_points, CFG.threshold) == (5, 0.001, 20, 3.0)
    assert (CFG.persist_steps, CFG.mad_factor, CFG.eta) == (3, 1.4826, 0.02)
    assert CFG.epsilon_for("latency", "ms") == 1.0 and CFG.epsilon_for("mem", "MB") == 1e-6
    with pytest.raises(ConfigError):
        CIConfig.from_sections({"ci": {}}, load_section_file("anomara"))
    assert CI_API_VERSION == "1"


def test_robust_scale_matches_the_03_anomara_micro_example() -> None:
    med, scale = ci.robust_scale(np.asarray([100.0, 102.0, 98.0, 101.0, 99.0, 100.0, 103.0, 97.0]), 1.0, CFG)
    assert (med, scale) == (100.0, 1.4826 * 1.5)


def test_target_priority() -> None:
    names = [
        "a|a|error|metrics",
        "a|a|error_rate|traces",
        "a|a|latency_p50|metrics",
        "a|a|latency_p90|metrics",
    ]
    series = {n: _s(n, [0], [1.0]) for n in names}
    target_of = ci.target_of
    found = target_of("a", series)
    assert found is not None and found.series_id == "a|a|latency_p90|metrics"  # highest metric quantile
    series["a|a|latency_p99|traces"] = _s("a|a|latency_p99|traces", [0], [1.0])
    found = target_of("a", series)
    assert found is not None and found.series_id == "a|a|latency_p99|traces"
    assert target_of("b", series) is None


def test_grid_keeps_buckets_where_every_column_is_observed() -> None:
    a = _s("a|a|latency_p99|traces", [k * 10 * NS for k in range(5)], [1.0, 2.0, 3.0, 4.0, 5.0])
    b = _s("b|b|latency_p99|traces", [0, 10 * NS, 20 * NS, 40 * NS], [6.0, 7.0, 8.0, 9.0])
    starts, matrix, step = ci.grid_matrix([a, b], (0, 50 * NS), CFG.bucket_ns)
    assert starts.tolist() == [0, 10 * NS, 20 * NS, 40 * NS]  # b has no point at 30 s
    assert matrix.tolist() == [[1.0, 6.0], [2.0, 7.0], [3.0, 8.0], [5.0, 9.0]] and step == 10 * NS
    slow = _s("c|c|latency|metrics", [k * 15 * NS for k in range(4)], [1.0, 2.0, 3.0, 4.0])
    assert ci.effective_step(slow, CFG.bucket_ns) == 15 * NS  # the grid takes the largest effective step


def test_traces_and_logs_series_step_is_the_bucket_even_with_repeated_values() -> None:
    # 03-anomara §3.1: the run-of-equal-values rule is for metrics only.
    values = [0.0] * 4 + [1.0] * 4 + [0.0] * 4
    t = [k * 10 * NS for k in range(12)]
    assert ci.effective_step(_s("a|a|error_rate|traces", t, values), CFG.bucket_ns) == 10 * NS
    assert ci.effective_step(_s("a|a|error|logs", t, values), CFG.bucket_ns) == 10 * NS
    assert ci.effective_step(_s("a|a|error|metrics", t, values), CFG.bucket_ns) == 40 * NS
    assert ci.effective_step(_s("a|a|error|metrics", [0], [1.0]), CFG.bucket_ns) == CFG.bucket_ns


@pytest.mark.parametrize(
    ("z", "expected"),
    [
        ([0.0, 5.0, 6.0, 7.0, 0.0], 5.0),
        ([5.0, -5.0, 5.0, -5.0], 0.0),
        ([0.0, 9.0, 0.0, 0.0], 0.0),
        ([-4.0] * 3, 4.0),
    ],
    ids=["run", "sign-flips", "spike", "down"],
)
def test_persistent_max(z: list[float], expected: float) -> None:
    starts = np.arange(len(z), dtype=np.int64) * 10 * NS
    assert ci.persistent_max(np.asarray(z), starts, 10 * NS, 3) == expected


def test_persistent_max_needs_contiguous_buckets() -> None:
    # Three kept rows 10 buckets apart are three isolated spikes, not a run (03-anomara §3.2 step 4).
    z = np.asarray([9.0, 9.0, 9.0])
    apart = np.asarray([100, 110, 120], dtype=np.int64) * 10 * NS
    together = np.asarray([100, 101, 102], dtype=np.int64) * 10 * NS
    assert ci.persistent_max(z, apart, 10 * NS, 3) == 0.0
    assert ci.persistent_max(z, together, 10 * NS, 3) == 9.0


def test_ridge_recovers_a_linear_fit_and_reports_singular_systems() -> None:
    z = np.asarray([[math.sin(k)] for k in range(50)])
    x = 2.0 * z[:, 0] + 1.0
    fit = ci.ridge_fit(z, x, 0.0)
    assert fit is not None and fit[0][0] == pytest.approx(2.0)
    assert ci.ridge_fit(np.zeros((10, 2)), np.ones(10), 0.0) is None
