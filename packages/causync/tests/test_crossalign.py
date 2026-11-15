"""Logs and metrics to the reference clock (04 §3.3): log–span join and co-movement."""

from __future__ import annotations

import numpy as np
import pyarrow as pa

from veyltrace_causync.crossalign import comovement_offset, log_span_offset
from veyltrace_causync.settings import causync_config
from veyltrace_core.config import resolve_config
from veyltrace_core.testing import golden

ALIGN = causync_config(resolve_config({}, ai_mode="off").engine("causync")).align
MS, S = 10**6, 10**9
STEPS = {"logs": 10 * S, "metrics": 10 * S, "traces": 10 * S}


def spans(n: int) -> pa.Table:
    """n spans s0…: span i covers [100 i, 100 i + 40] ms of trace t."""
    return pa.table(
        {
            "trace_id": pa.array(["t"] * n),
            "span_id": pa.array([f"s{i}" for i in range(n)]),
            "start_ns": pa.array([100 * i * MS for i in range(n)], pa.int64()),
            "end_ns": pa.array([(100 * i + 40) * MS for i in range(n)], pa.int64()),
        }
    )


def logs(times_ms: list[int], span_ids: list[str | None]) -> pa.Table:
    return pa.table(
        {
            "t_ns": pa.array([t * MS for t in times_ms], pa.int64()),
            "service": pa.array(["a"] * len(times_ms)),
            "trace_id": pa.array([None if s is None else "t" for s in span_ids], pa.string()),
            "span_id": pa.array(span_ids, pa.string()),
        }
    )


def test_lines_inside_their_span_need_no_offset() -> None:
    lines = logs([100 * i + 20 for i in range(20)], [f"s{i}" for i in range(20)])
    inside = log_span_offset(lines, spans(20), ALIGN)
    assert inside is not None
    assert (inside.offset_ns, inside.method, inside.confidence) == (0, "log_span_join", 1.0)
    one_out = logs([100 * i + 20 for i in range(19)] + [5000], [f"s{i}" for i in range(20)])
    found = log_span_offset(one_out, spans(20), ALIGN)
    assert found is not None
    assert (found.offset_ns, found.confidence) == (0, 0.95)  # exactly log_inside_share


def test_late_log_clock_is_projected_back_into_the_spans() -> None:
    # the log clock runs 70 ms ahead: a line written 20 ms into its span reads 90 ms
    lines = logs([100 * i + 90 for i in range(20)], [f"s{i}" for i in range(20)])
    found = log_span_offset(lines, spans(20), ALIGN)
    assert found is not None
    assert (found.source, found.service, found.method) == ("logs", None, "log_span_join")
    assert found.offset_ns == -50 * MS  # the nearest in-span shift: to the span end, not the true −70
    assert found.confidence == 1.0
    early = logs([100 * i - 30 for i in range(20)], [f"s{i}" for i in range(20)])
    behind = log_span_offset(early, spans(20), ALIGN)
    assert behind is not None
    assert behind.offset_ns == 30 * MS


def test_lines_without_a_matching_span_do_not_join() -> None:
    assert log_span_offset(logs([10, 20], [None, None]), spans(3), ALIGN) is None
    assert log_span_offset(logs([10, 20], ["x", "y"]), spans(3), ALIGN) is None
    assert log_span_offset(logs([], []), spans(3), ALIGN) is None
    mixed = logs([20, 999_999], ["s0", None])  # the line without ids is ignored, not counted outside
    assert (log_span_offset(mixed, spans(3), ALIGN) or 0) == log_span_offset(
        logs([20], ["s0"]), spans(3), ALIGN
    )


def test_spans_are_moved_to_the_reference_clock_before_the_join() -> None:
    # service a's trace clock runs 70 ms ahead and its trace offset is −70 ms; its logs share the
    # skewed clock, so they must come out with the same correction (#271)
    trace = spans(20).append_column("service", pa.array(["a"] * 20))
    lines = logs([100 * i + 20 for i in range(20)], [f"s{i}" for i in range(20)])
    raw = log_span_offset(lines, trace, ALIGN)
    assert raw is not None
    assert raw.offset_ns == 0  # against raw spans the lines look fine
    moved = log_span_offset(lines, trace, ALIGN, {"a": -70 * MS})
    assert moved is not None
    assert moved.offset_ns == -50 * MS  # the nearest in-span shift; a lower bound on the 70 ms
    assert log_span_offset(lines, trace, ALIGN, {"other": -70 * MS}) == raw


def traffic(
    lag_steps: int, services: tuple[str, ...] = ("a", "b", "c"), noise: float = 0.0, n: int = 80
) -> pa.Table:
    """Traces `rps` and `log_rate` per service on a 10 s grid; logs show the same traffic
    `lag_steps` buckets later, plus optional independent noise."""
    rows: list[tuple[str, str, str, str, int, float]] = []
    for k, service in enumerate(services):
        rng = np.random.default_rng(k)
        base = rng.normal(50.0, 10.0, n + 40)
        extra = np.random.default_rng(100 + k).normal(0.0, noise, n) if noise else np.zeros(n)
        for i in range(n):
            rows.append(("traces", service, service, "rps", 10 * i, float(base[i + 20])))
            rows.append(
                ("logs", service, service, "log_rate", 10 * i, float(base[i + 20 - lag_steps] + extra[i]))
            )
    cols = list(zip(*rows, strict=True))
    return pa.table(
        {
            "source": pa.array(cols[0]), "service": pa.array(cols[1]), "component": pa.array(cols[2]),
            "signal": pa.array(cols[3]), "t_ns": pa.array([t * S for t in cols[4]], pa.int64()),
            "value": pa.array(cols[5], pa.float64()),
        }
    )  # fmt: skip


def test_comovement_recovers_a_planted_lag_of_two_steps() -> None:
    found = comovement_offset(traffic(2), "logs", "traces", STEPS, ALIGN)
    assert (found.source, found.service, found.offset_ns, found.method) == (
        "logs",
        None,
        -20 * S,
        "comovement",
    )
    assert found.confidence > 0.99
    ahead = comovement_offset(traffic(-3), "logs", "traces", STEPS, ALIGN)
    assert ahead.offset_ns == 30 * S
    aligned = comovement_offset(traffic(0), "logs", "traces", STEPS, ALIGN)
    assert (aligned.offset_ns, aligned.method) == (0, "comovement")
    one_step = comovement_offset(traffic(1), "logs", "traces", STEPS, ALIGN)
    assert (one_step.offset_ns, one_step.method) == (0, "comovement")  # inside the resolution


def test_comovement_rejects_what_it_cannot_support() -> None:
    none = (0, "none", 0.0)

    def result(table: pa.Table, steps: dict[str, int] = STEPS) -> tuple[int, str, float]:
        o = comovement_offset(table, "logs", "traces", steps, ALIGN)
        return (o.offset_ns, o.method, o.confidence)

    assert result(traffic(2, noise=200.0)) == none  # low correlation
    assert result(traffic(2, services=("a",))) == none  # one service cannot agree with another
    assert result(traffic(13)) == none  # beyond max_lag (120 s): no accepted lag
    assert result(traffic(2, n=15)) == none  # fewer than min_points overlapping points
    assert result(traffic(2), steps={"traces": 10 * S}) == none  # the source has no step
    flat = traffic(2).set_column(5, "value", pa.array([1.0] * traffic(2).num_rows, pa.float64()))
    assert result(flat) == none  # constant traffic has no co-movement


def test_a_best_lag_at_the_edge_rejects_the_service() -> None:
    # the true lag is exactly max_lag (12 steps of 10 s): the winner is at the edge of the search,
    # so the services are rejected rather than given their next-best lag (#271)
    found = comovement_offset(traffic(12), "logs", "traces", STEPS, ALIGN)
    assert (found.offset_ns, found.method) == (0, "none")
    inside = comovement_offset(traffic(11), "logs", "traces", STEPS, ALIGN)
    assert (inside.offset_ns, inside.method) == (-110 * S, "comovement")


def test_coarser_step_sets_the_resolution() -> None:
    found = comovement_offset(traffic(4), "logs", "traces", {"logs": 20 * S, "traces": 10 * S}, ALIGN)
    assert found.offset_ns == -40 * S  # two 20 s steps


def test_uneven_grids_do_not_fake_a_lag() -> None:
    # constant traffic: 10 s trace buckets on a 15 s metric grid fall 1, 2, 1, 2 … per step
    rows = [("traces", "a", 10 * i, 3.0) for i in range(120)] + [
        ("traces", "b", 10 * i, 5.0) for i in range(120)
    ]
    rows += [
        ("metrics", s, 15 * i, v + 0.07 * (-1) ** i) for s, v in (("a", 3.0), ("b", 5.0)) for i in range(80)
    ]
    table = pa.table(
        {
            "source": pa.array([r[0] for r in rows]), "service": pa.array([r[1] for r in rows]),
            "component": pa.array([r[1] for r in rows]), "signal": pa.array(["rps"] * len(rows)),
            "t_ns": pa.array([r[2] * S for r in rows], pa.int64()),
            "value": pa.array([r[3] for r in rows], pa.float64()),
        }
    )  # fmt: skip
    steps = {"metrics": 15 * S, "traces": 10 * S}
    found = comovement_offset(table, "metrics", "traces", steps, ALIGN)
    assert (found.offset_ns, found.method) == (0, "none")


def test_synth_plants_no_skew() -> None:
    series = golden("signal_cube.series", "synth-04")
    assert isinstance(series, pa.Table)
    steps = {"logs": 10 * S, "metrics": 15 * S, "traces": 10 * S}
    for source in ("metrics", "logs"):
        assert comovement_offset(series, source, "traces", steps, ALIGN).offset_ns == 0


def test_synth_logs_join_their_spans() -> None:
    lines, trace = golden("telemetry.logs", "synth-04"), golden("telemetry.spans", "synth-04")
    assert isinstance(lines, pa.Table)
    assert isinstance(trace, pa.Table)
    found = log_span_offset(lines, trace, ALIGN)
    assert found is not None
    assert (found.offset_ns, found.method) == (0, "log_span_join")
