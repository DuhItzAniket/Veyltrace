"""Tests of the child-process runner (#68): a run in a child is the in-process run plus its cost
columns; a run past `resources.timeout_s` is killed and scored a miss; a child that fails, or exits
without a result, stops the experiment as an in-process error would."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pyarrow as pa
import pytest

from veyltrace_bench import child, runner
from veyltrace_core import cli, io, textio
from veyltrace_core.errors import VeyltraceError
from veyltrace_core.ids import case_id

SMOKE = Path(__file__).resolve().parents[1] / "experiments" / "synth-smoke.yaml"
COST = ("wall_ms", "peak_rss_mb")


def _rows(out: Path) -> dict[str, dict[str, object]]:
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    return {str(r["case_id"]): r for r in table.to_pylist()}


def _one_case(tmp_path: Path, *, timeout_s: int = 600) -> Path:
    """synth-smoke on synth-01 alone, with `timeout_s`."""
    cases, exp = tmp_path / "cases.yaml", tmp_path / "exp.yaml"
    cases.write_text(f"[{case_id('synth-01')}]\n", encoding="utf-8")
    text = textio.read_text(SMOKE).replace("cases: all", f"cases: {json.dumps(cases.as_posix())}")
    exp.write_text(text.replace("timeout_s: 600", f"timeout_s: {timeout_s}"), encoding="utf-8")
    return exp


def test_a_child_run_is_the_in_process_run_plus_its_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    outs: dict[bool, Path] = {}
    for in_process in (False, True):
        monkeypatch.setattr(runner, "IN_PROCESS", in_process)
        root = tmp_path / str(in_process)
        outs[in_process] = runner.run_experiment(SMOKE, out_root=root / "results", runs_root=root / "runs")[0]
    isolated, inline = (_rows(outs[k]) for k in (False, True))
    assert all(isinstance(r["peak_rss_mb"], float) for r in isolated.values())
    assert all(r["peak_rss_mb"] is None for r in inline.values())  # not measurable in process
    blank = dict.fromkeys(COST)
    assert {c: r | blank for c, r in isolated.items()} == {c: r | blank for c, r in inline.items()}
    for name in ("summary.json", "manifest.json"):  # run ids included: same config, same runs
        assert textio.read_bytes(outs[False] / name) == textio.read_bytes(outs[True] / name)


def test_a_run_past_timeout_s_is_killed_and_scored_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    hang = [sys.executable, "-c", "import time; time.sleep(120)"]
    monkeypatch.setattr(runner, "child_command", lambda request, result: hang)
    exp = _one_case(tmp_path, timeout_s=1)
    out, summary = runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    (row,) = _rows(out).values()
    assert row["run_outcome"] == "timeout" and row["hit_at_1"] is False and row["ranks"] == []
    assert isinstance(row["wall_ms"], float) and 1000.0 <= row["wall_ms"] < 60_000.0  # killed, not waited
    assert row["peak_rss_mb"] is None and row["verdict_hash"] is None
    (run,) = json.loads(textio.read_text(out / "manifest.json"))["runs"]
    assert run["run_id"] is None and run["inputs_sha256"] is None  # no run directory to name
    groups = summary["groups"]
    assert isinstance(groups, list) and groups[0]["n_fault"] == 1


def test_a_child_without_a_result_stops_the_experiment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    monkeypatch.setattr(runner, "child_command", lambda request, result: [sys.executable, "-c", "pass"])
    with pytest.raises(VeyltraceError, match="without a result"):
        runner.run_experiment(_one_case(tmp_path), out_root=tmp_path / "results", runs_root=tmp_path / "runs")


def test_the_child_reports_an_error_instead_of_a_summary(tmp_path: Path) -> None:
    request, result = tmp_path / "request.json", tmp_path / "result.json"
    bad = {"dataset": "synth", "case_id": case_id("synth-01"), "ai_mode": "off",
           "overrides": {"core.no_such_key": 1}, "runs_root": str(tmp_path / "runs")}  # fmt: skip
    request.write_text(json.dumps(bad), encoding="utf-8")
    assert child.main([str(request), str(result)]) == 1
    error = json.loads(textio.read_text(result))["error"]
    assert error["type"] == "ConfigError" and "no_such_key" in error["detail"]


def test_peak_rss_is_this_process_in_mib() -> None:
    peak = child.peak_rss_mb()
    assert 1.0 < peak < 1024.0 * 1024.0  # an interpreter with pyarrow loaded, well under a TiB
    assert child.peak_rss_mb() >= peak  # a peak never decreases
