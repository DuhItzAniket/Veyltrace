"""RCAEval pre-injection normal windows (04 §5.4 item 6; #393): rows, folds, fit, drops."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pyarrow as pa
import pytest

from veyltrace_bench import answer_keys, calibration, normal_windows, runner, splits
from veyltrace_bench.experiment import Experiment
from veyltrace_contracts.models import AnswerKeyRow
from veyltrace_core import cli, io, textio, yaml12
from veyltrace_core.calibration import load_calibration
from veyltrace_core.config import CONFIG_DIR_ENV
from veyltrace_core.errors import ConfigError
from veyltrace_core.ids import case_id

REPO = Path(__file__).resolve().parents[2]
WINDOWS = """\
experiment_id: synth-windows
description: "normal windows on synth (never reported)"
dataset: {parts: [synth], cases: all, exclude: null, normal_windows: rcaeval_pre_injection}
split: {family: synth, scheme: crossfit2, seed: 20261108}
protocol: {alert: oracle, shift_s: 0, sources_drop: []}
methods:
  - {id: "veyltrace:off", kind: veyltrace, ai: {mode: "off"}, overrides: {}}
calibration: {fit: true, alpha: 0.10, no_fault_beta: 0.10}
metrics: [ac_at_k]
resources: {workers: 1, timeout_s: 600}
"""


def _alert(run_dir: Path, baseline_s: int) -> Path:
    start = 1_767_225_600_000_000_000
    end = start + baseline_s * normal_windows.NS_PER_S
    alert = {"schema_version": io.contract_info("alert").version, "protocol": "oracle", "t_alert_ns": end + 1}
    alert |= {
        "shift_ns": 0,
        "detector": None,
        "windows": {"baseline": [start, end], "incident": [end, end + 1]},
    }
    io.write("alert", alert | {"clamped": True}, run_dir)
    return run_dir


def test_a_window_needs_60_s_of_baseline(tmp_path: Path) -> None:
    assert normal_windows.too_short(_alert(tmp_path / "a", 59))
    assert not normal_windows.too_short(_alert(tmp_path / "b", 60))
    assert not normal_windows.too_short(tmp_path / "rejected") and not normal_windows.too_short(None)
    # A window core rejects for having no data is dropped too, not counted as a false alarm (#393 review).
    assert normal_windows.dropped(tmp_path / "rejected", normal_windows.EMPTY_WINDOW)
    assert normal_windows.dropped(tmp_path / "a", None) and not normal_windows.dropped(
        None, "unsupported_format"
    )


def _exp(text: str) -> Experiment:
    return Experiment.model_validate(yaml12.load_yaml_bytes(text.encode(), source="t"))


def test_windows_come_from_fault_cases_of_rcaeval_parts_under_the_unshifted_oracle() -> None:
    exp = _exp(WINDOWS.replace("[synth]", "[re2-ob, synth]"))
    fields = dict.fromkeys(AnswerKeyRow.model_fields) | {"system": "ob", "root_service": "cart"}
    rows = [
        AnswerKeyRow.model_validate(fields | {"case_id": f"{i:012x}", "dataset": d, "is_no_fault": nf})
        for i, (d, nf) in enumerate([("re2-ob", False), ("re2-ob", True), ("synth", False)])
    ]
    assert [r.case_id for r in normal_windows.windows_of(exp, rows)] == [rows[0].case_id]
    normal_windows.check(exp)
    re2 = WINDOWS.replace("[synth]", "[re2-ob]")
    for bad in (re2.replace("shift_s: 0", "shift_s: -60"), re2.replace("alert: oracle", "alert: detected")):
        with pytest.raises(ConfigError, match="oracle and shift_s 0"):
            normal_windows.check(_exp(bad))
    with pytest.raises(ConfigError, match="RCAEval part"):
        normal_windows.check(_exp(WINDOWS))


@pytest.fixture
def synth_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Synth as if it were an RCAEval part (690 s of baseline at shift -510), on a copy of config/."""
    shutil.copytree(REPO / "config", tmp_path / "repo" / "config")
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path / "repo" / "config"))
    monkeypatch.setattr(normal_windows, "RCAEVAL_BENCHMARKS", ("synth",))
    monkeypatch.setattr(runner, "IN_PROCESS", True)
    assert cli.main(["data", "fetch", "synth"]) == 0
    exp = tmp_path / "windows.yaml"
    textio.write_bytes(exp, WINDOWS.encode())
    return exp


def _run(tmp_path: Path, exp: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    out, _ = runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    return table.to_pylist(), json.loads(textio.read_text(out / "manifest.json"))["runs"]


def test_windows_are_no_truth_rows_of_their_cases_fold_and_enter_its_fit(
    tmp_path: Path, synth_windows: Path
) -> None:
    rows, runs = _run(tmp_path, synth_windows)
    cases = {str(r["case_id"]): r for r in rows if r["variant"] is None}
    keys = {c: k for c, k in answer_keys.load_answer_keys("synth").items() if c in cases}
    plan = splits.crossfit2(keys, 20261108)
    windows = [r for r in rows if r["variant"] == "shift-510"]
    assert sorted(str(r["case_id"]) for r in windows) == sorted(
        c for c, k in keys.items() if not k.is_no_fault
    )
    for w in windows:
        assert (w["shift_s"], w["hit_at_1"], w["in_set"], w["fold"]) == (
            -510,
            None,
            None,
            plan.test_fold[str(w["case_id"])],
        )
    assert len(runs) == 2 * len(rows)  # every row: a calibration run and its held-out restart
    for fold in splits.FOLDS:
        nf = load_calibration(
            tmp_path / "repo" / "config" / "calibration" / f"synth.off.oracle.{fold}.json"
        ).content.no_fault
        assert nf.m == len(plan.fits[fold])  # its windows + synth-05 if it is there (each has robust_z atoms)
        assert "rcaeval_pre_injection" in nf.sources
    pooled = next(r for r in calibration.held_out_rates(rows) if r["fold"] == "pooled")
    assert (pooled["n_fault"], pooled["n_normal"]) == (4, 5)  # R-12's false-alarm denominator


def test_a_window_with_a_short_baseline_is_dropped_but_its_run_is_recorded(
    tmp_path: Path, synth_windows: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(normal_windows, "MIN_BASELINE_S", 10**6)  # every synth window is too short
    rows, runs = _run(tmp_path, synth_windows)
    assert all(r["variant"] is None for r in rows) and len(rows) == 5
    assert len(runs) == 5 + 4 + 5  # calibration runs (cases + windows), then the cases' restarts
    nf = [
        load_calibration(p).content.no_fault
        for p in (tmp_path / "repo" / "config" / "calibration").glob("*.json")
    ]
    assert sorted(n.m for n in nf) == [0, 1] and all("rcaeval_pre_injection" not in n.sources for n in nf)


def test_a_transfer_fit_has_its_source_parts_windows(
    tmp_path: Path, synth_windows: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """04 §5.4 item 7: the transfer file is fitted "with their normal windows", although the
    experiment's own (test) parts ask for none (#393 review)."""
    keys = answer_keys.load_answer_keys("synth")
    test_cases = [case_id("synth-01"), case_id("synth-02")]
    sources = {c: k for c, k in keys.items() if c in {case_id(f"synth-0{i}") for i in (3, 4, 5)}}
    monkeypatch.setattr(splits, "TRANSFER_SOURCES", {"synth.transfer-x": ("synth",)})
    monkeypatch.setattr(runner, "transfer_keys", lambda *_: sources)
    repo = tmp_path / "repo"
    textio.write_bytes(repo / "two.yaml", "".join(f'- "{c}"\n' for c in test_cases).encode())
    text = WINDOWS.replace("cases: all", "cases: two.yaml").replace(
        "normal_windows: rcaeval_pre_injection", "normal_windows: none"
    )
    text = text.replace("scheme: crossfit2", "scheme: transfer, calibrate_from: synth.transfer-x")
    textio.write_bytes(synth_windows, text.encode())
    rows, _ = _run(tmp_path, synth_windows)
    content = load_calibration(repo / "config" / "calibration" / "synth.off.oracle.transfer-x.json").content
    assert content.no_fault.m == 3 and content.no_fault.sources == [
        "rcaeval_pre_injection",
        "synth-05",
    ]  # 2 + synth-05
    assert content.n == 2  # synth-03 and synth-04, never a test case
    assert sorted(str(r["case_id"]) for r in rows) == sorted(test_cases) and {r["fold"] for r in rows} == {
        "transfer-x"
    }
    bad = text.replace("shift_s: 0", "shift_s: 30")
    textio.write_bytes(synth_windows, bad.encode())
    with pytest.raises(ConfigError, match="source windows need"):
        _run(tmp_path, synth_windows)
