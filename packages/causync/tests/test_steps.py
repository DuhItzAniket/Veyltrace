"""Config view (04 §4) and source steps with the tolerance (04 §3.1)."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pytest

from veyltrace_causync.settings import causync_config
from veyltrace_causync.steps import series_groups, source_steps, tolerance
from veyltrace_core.config import resolve_config
from veyltrace_core.errors import ConfigError
from veyltrace_core.testing import golden

CONFIG = resolve_config({}, ai_mode="off").engine("causync")
S = 10**9


def series(rows: list[tuple[str, str, str, str, int, float]]) -> pa.Table:
    """A `signal_cube.series` slice from (source, service, component, signal, second, value) rows."""
    cols = list(zip(*rows, strict=True)) if rows else [[]] * 6
    return pa.table(
        {
            "source": pa.array(cols[0], pa.string()),
            "service": pa.array(cols[1], pa.string()),
            "component": pa.array(cols[2], pa.string()),
            "signal": pa.array(cols[3], pa.string()),
            "t_ns": pa.array([t * S for t in cols[4]], pa.int64()),
            "value": pa.array(cols[5], pa.float64()),
        }
    )


def test_defaults_match_the_spec_table() -> None:
    cfg = causync_config(CONFIG)
    a = cfg.align
    assert (a.min_pairs, a.trace_min_offset_ns, a.min_violation_share) == (30, 5_000_000, 0.05)
    assert (a.log_inside_share, a.max_lag_ns, a.min_corr, a.min_points) == (0.95, 120 * S, 0.5, 20)
    assert cfg.change_kinds == {"deploy", "config", "flag", "scale", "restart", "commit"}
    assert (cfg.tau_ns, cfg.min_replicas) == (300 * S, 2)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("align", "min_pairs", 0),
        ("align", "min_corr", 1.5),
        ("align", "max_lag_s", True),
        ("changes", "tau_s", 0),
        ("changes", "kinds", "deploy"),
        ("peer", "min_replicas", 1.5),
    ],
)
def test_bad_values_are_config_errors(section: str, key: str, value: Any) -> None:
    broken = {**CONFIG, section: {**CONFIG[section], key: value}}
    with pytest.raises(ConfigError, match=f"causync.{section}.{key}"):
        causync_config(broken)


def test_metric_step_is_the_run_length_of_held_values() -> None:
    # scraped every 15 s, held on a 1 s grid (RCAEval): the step is 15 s, not 1 s
    held = [("metrics", "a", "a", "cpu", t, float(t // 15)) for t in range(90)]
    native = [("metrics", "b", "b", "cpu", t, float(t)) for t in range(0, 90, 15)]
    assert source_steps(series(held)) == {"metrics": 15 * S}
    assert source_steps(series(native)) == {"metrics": 15 * S}
    constant = [("metrics", "c", "c", "mem", t, 1.0) for t in range(0, 50, 5)]
    assert source_steps(series(constant)) == {"metrics": 5 * S}  # no value change: the spacing


def test_bucketed_sources_take_the_spacing_of_their_count_series() -> None:
    rows = [("logs", "a", "a", "log_rate", t, 1.0) for t in range(0, 60, 10)]
    rows += [("traces", "a", "a", "rps", t, 1.0) for t in range(0, 60, 20)]
    rows += [("traces", "a", "a", "latency_p99", t, 1.0) for t in (0, 50)]  # quantiles have gaps
    steps = source_steps(series(rows))
    assert steps == {"logs": 10 * S, "traces": 20 * S}
    assert tolerance(steps) == 20 * S


def test_no_stepped_source_gives_zero_tolerance() -> None:
    assert source_steps(series([])) == {}
    assert tolerance({}) == 0
    single = series([("metrics", "a", "a", "cpu", 0, 1.0)])
    assert source_steps(single) == {}


def test_groups_do_not_depend_on_row_order() -> None:
    rows = [("metrics", "a", "a", "cpu", t, float(t)) for t in range(5)]
    rows += [("logs", "a", "a", "log_rate", t, 0.0) for t in range(0, 30, 10)]
    forward = [(k, t.tolist(), x.tolist()) for k, t, x in series_groups(series(rows))]
    backward = [(k, t.tolist(), x.tolist()) for k, t, x in series_groups(series(rows[::-1]))]
    assert forward == backward
    assert [k[0] for k, _, _ in forward] == ["logs", "metrics"]


def test_synth_tolerance_is_the_bucket() -> None:
    table = golden("signal_cube.series", "synth-04")
    assert isinstance(table, pa.Table)
    steps = source_steps(table)
    assert steps["logs"] == steps["traces"] == 10 * S
    assert tolerance(steps) == steps["metrics"] == 15 * S  # scrapes held on a finer grid
