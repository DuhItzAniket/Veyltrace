"""Signalyth's engine step (02 §7): goldens, synth behaviour checks, window independence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pytest

from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.errors import ArtifactMissing
from veyltrace_core.testing import SYNTH_CASES, VARIANTS, assert_golden, golden, make_context
from veyltrace_core.testing.rundir import fixture_run_dir
from veyltrace_signalyth.api import run

CASES = (*SYNTH_CASES, *sorted(VARIANTS))
OUTPUTS = ("signal_cube.series", "signal_cube.edges", "signal_cube.templates", "signal_cube.critical_path")


def _run(case: str, tmp_path: Path) -> Path:
    try:
        run_dir = fixture_run_dir(case, tmp_path, through="alert")
    except ArtifactMissing as exc:  # synth-01@detected before Anomara's detector: no alert fixture
        pytest.skip(f"upstream fixtures for {case} are not committed yet: {exc}")
    variant = VARIANTS.get(case)
    ctx = make_context(
        "signalyth",
        run_dir,
        ai_mode=variant.ai_mode if variant else "off",
        overrides=variant.overrides if variant else {},
    )
    assert run(ctx).status == "ok"
    return run_dir


@pytest.mark.parametrize("case", CASES)
def test_matches_golden(tmp_path: Path, case: str) -> None:
    run_dir = _run(case, tmp_path)
    for contract in OUTPUTS:
        assert_golden(io.path_of(contract, run_dir), contract, case)


def _alert(case: str) -> models.Alert:
    alert = golden("alert", case)
    assert isinstance(alert, models.Alert)
    return alert


def _rise(case: str, signal: str, source: str, factor: float) -> list[str]:
    """Services whose `signal` mean in the incident window exceeds `factor` × the baseline mean."""
    series, w = golden("signal_cube.series", case), _alert(case).windows
    assert isinstance(series, pa.Table)
    rows = [r for r in series.to_pylist() if r["signal"] == signal and r["source"] == source]
    risen = []
    for svc in sorted({r["service"] for r in rows}):
        base = [
            r["value"] for r in rows if r["service"] == svc and w.baseline[0] <= r["t_ns"] < w.baseline[1]
        ]
        inc = [r["value"] for r in rows if r["service"] == svc and w.incident[0] <= r["t_ns"] < w.incident[1]]
        if base and inc and np.mean(inc) > factor * max(np.mean(base), 1e-9):
            risen.append(svc)
    return risen


def test_synth_behaviour_without_answer_keys() -> None:
    """02 §7: what each synth fault must show in the signal cube (no answer key read)."""
    assert len(_rise("synth-01", "cpu", "metrics", 1.5)) == 1  # one CPU hog
    edges = golden("signal_cube.edges", "synth-02")
    assert isinstance(edges, pa.Table)
    by: dict[tuple[str, str], dict[str, Any]] = {}
    for r in edges.to_pylist():
        by.setdefault((r["caller"], r["callee"]), {})[r["window"]] = r
    slower = [
        k
        for k, v in by.items()
        if len(v) == 2
        and any(
            (v["incident"][c] or 0) > 1.5 * (v["baseline"][c] or 0) for c in ("p99_gap_ms", "p99_callee_ms")
        )
    ]
    assert slower, "synth-02: no edge got slower"
    assert _rise("synth-02", "cpu", "metrics", 1.5) == []  # a network fault moves no CPU
    assert _rise("synth-03", "error_rate", "traces", 2.0)
    assert _rise("synth-04", "latency_p99", "traces", 1.5) or _rise(
        "synth-04", "self_time_p99", "traces", 1.5
    )


def test_series_do_not_depend_on_the_windows(tmp_path: Path) -> None:
    first = _run("synth-01", tmp_path / "a")
    moved = _run("synth-01", tmp_path / "b")
    alert = _alert("synth-01").model_dump()
    alert["windows"] = {
        "baseline": [alert["windows"]["baseline"][0], alert["t_alert_ns"] - 60 * 10**9],
        "incident": [alert["t_alert_ns"] - 60 * 10**9, alert["windows"]["incident"][1]],
    }
    io.write("alert", alert, moved)
    ctx = make_context("signalyth", moved)
    run(ctx)
    series = io.path_of("signal_cube.series", first).read_bytes()
    assert io.path_of("signal_cube.series", moved).read_bytes() == series
    assert (
        io.path_of("signal_cube.edges", moved).read_bytes()
        != io.path_of("signal_cube.edges", first).read_bytes()
    )
