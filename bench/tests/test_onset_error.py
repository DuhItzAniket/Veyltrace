"""Onset error (04 §7 "Onset error"; #215): |onsets.t_onset_ns − answer_key.t_inject_ns| / 1e6 in
per_case.csv `onset_error_ms`, for detected-protocol `ok` runs of cases with an injection time, and
its median, max and count in summary.json (metric `onset_error`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_bench import runner
from veyltrace_bench.metrics import NS_PER_MS, MethodOutput, Truth, score_case
from veyltrace_bench.summary import summarize
from veyltrace_contracts.models import CaseManifest, Onsets
from veyltrace_core import cli, io, plugins, textio
from veyltrace_core.adapters import AlertDetection, TelemetryTables
from veyltrace_core.ids import case_id
from veyltrace_core.pipeline import RunSummary
from veyltrace_core.plugins import Plugin
from veyltrace_core.synth import layout as lay

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "bench" / "experiments" / "synth-smoke.yaml"
T_INJECT = 1_767_225_900 * 10**9
TRUTH = Truth("cart", "cpu", "cpu", None, T_INJECT)
DELAY_NS = 30 * 10**9  # the test detector fires 30 s after the injection


def _error(truth: Truth, out: MethodOutput) -> float | None:
    return score_case(truth, out).onset_error_ms


def test_onset_error_is_the_absolute_gap_in_ms() -> None:
    for gap_ns in (0, 1, 2_500_000, -DELAY_NS):
        score = score_case(TRUTH, MethodOutput(ranks=("cart_cpu",), t_onset_ns=T_INJECT + gap_ns))
        assert score.onset_error_ms == abs(gap_ns) / 1e6
        assert score.columns()["onset_error_ms"] == score.onset_error_ms


@given(st.integers(0, 2**62), st.integers(0, 2**62))
def test_onset_error_is_symmetric_and_non_negative(a: int, b: int) -> None:
    one = _error(Truth("cart", t_inject_ns=a), MethodOutput(ranks=("cart",), t_onset_ns=b))
    other = _error(Truth("cart", t_inject_ns=b), MethodOutput(ranks=("cart",), t_onset_ns=a))
    assert one == other == abs(a - b) / NS_PER_MS
    assert one is not None and one >= 0.0


def test_no_onset_error_without_both_times_or_an_ok_run() -> None:
    ranked = ("cart",)
    assert _error(TRUTH, MethodOutput(ranks=ranked)) is None  # oracle: the runner passes no t_onset
    assert _error(Truth("cart"), MethodOutput(ranks=ranked, t_onset_ns=T_INJECT)) is None  # no inject time
    assert _error(Truth(None), MethodOutput(t_onset_ns=T_INJECT)) is None  # no fault, no injection
    for outcome in ("failed", "timeout", "no_alert"):
        assert _error(TRUTH, MethodOutput(outcome=outcome, t_onset_ns=T_INJECT)) is None
    # an unranked ok run still has an onset: onset error does not depend on the ranking
    assert _error(TRUTH, MethodOutput(t_onset_ns=T_INJECT + 5)) == 5 / NS_PER_MS


def _scored(gap_ns: int | None) -> Any:
    onset = None if gap_ns is None else T_INJECT + gap_ns
    return score_case(TRUTH, MethodOutput(ranks=("cart",), t_onset_ns=onset))


def test_summary_reports_median_max_and_count_in_any_order() -> None:
    scores = [_scored(g) for g in (3_000_000, None, 1_000_000, 10_000_000, 2_000_000)]
    got = summarize(scores, ["onset_error"])
    assert (got["onset_error_median_ms"], got["onset_error_max_ms"], got["n_onset"]) == (2.5, 10.0, 4)
    assert summarize(list(reversed(scores)), ["onset_error"]) == got
    empty = summarize([_scored(None)], ["onset_error"])
    assert (empty["onset_error_median_ms"], empty["onset_error_max_ms"], empty["n_onset"]) == (None, None, 0)
    assert "n_onset" not in summarize(scores, ["ac_at_k"])  # only a listed metric is written (04 §9)


def _experiment(tmp_path: Path, alert: str, names: list[str]) -> Path:
    cases = tmp_path / "cases.yaml"
    cases.write_text(json.dumps([case_id(n) for n in names]) + "\n", encoding="utf-8")
    text = textio.read_text(SMOKE).replace("cases: all", f"cases: {json.dumps(cases.as_posix())}")
    text = text.replace("alert: oracle", f"alert: {alert}").replace("metrics: [", "metrics: [onset_error, ")
    exp = tmp_path / f"{alert}.yaml"
    exp.write_text(text, encoding="utf-8")
    return exp


def _detector(telemetry: TelemetryTables, manifest: CaseManifest, config: Any) -> AlertDetection:
    return AlertDetection(lay.T_INJECT_NS + DELAY_NS, ("frontend",), "latency_p99", 1.0)


def _rows(out: Path) -> dict[str, dict[str, Any]]:
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    return {str(r["case_id"]): r for r in table.to_pylist()}


def test_detected_runs_fill_onset_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    found = (Plugin(plugins.ALERT_DETECTORS, plugins.ALERT_DETECTOR_NAME, "x:y", "d", lambda: _detector),)
    discover = plugins.discover
    monkeypatch.setattr(plugins, "discover", lambda g: found if g == plugins.ALERT_DETECTORS else discover(g))
    run_dirs: dict[str, Path] = {}
    run_case = runner.run_case

    def spy(dataset: str, cid: str, *args: Any, **kwargs: Any) -> RunSummary:
        summary = run_case(dataset, cid, *args, **kwargs)
        run_dirs[cid] = summary.run_dir
        return summary

    monkeypatch.setattr(runner, "run_case", spy)
    exp = _experiment(tmp_path, "detected", ["synth-01", "synth-05"])
    out, summary = runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    rows = _rows(out)
    injected, normal = rows[case_id("synth-01")], rows[case_id("synth-05")]
    assert injected["protocol"] == "detected" and injected["run_outcome"] == "ok"
    onsets = io.read_model("onsets", run_dirs[case_id("synth-01")], Onsets)
    assert onsets.t_onset_ns != lay.T_INJECT_NS  # the detector fired late, so the error is not 0
    assert injected["onset_error_ms"] == abs(onsets.t_onset_ns - lay.T_INJECT_NS) / 1e6
    assert normal["run_outcome"] == "ok" and normal["onset_error_ms"] is None  # no injection time
    groups = summary["groups"]
    assert isinstance(groups, list)
    values = [g for g in groups if g["n_onset"]]
    assert len(values) == 1 and values[0]["onset_error_max_ms"] == injected["onset_error_ms"]


def test_oracle_runs_leave_onset_error_empty(tmp_path: Path) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    exp = _experiment(tmp_path, "oracle", ["synth-01"])
    out, summary = runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    row = _rows(out)[case_id("synth-01")]
    assert row["run_outcome"] == "ok" and row["onset_error_ms"] is None
    groups = summary["groups"]
    assert isinstance(groups, list) and all(g["n_onset"] == 0 for g in groups)
