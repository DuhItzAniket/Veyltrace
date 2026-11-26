"""scripts/observe/perf_check.py (O-11): the per-dataset summary and the one-case child."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from veyltrace_core import cli

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "observe" / "perf_check.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("veyltrace_perf_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("veyltrace_perf_check", module)
    spec.loader.exec_module(module)
    return module


def _row(case: str, total: float, peak: float, outcome: str = "ok") -> dict[str, object]:
    steps = {"signalyth": total * 0.6, "anomara": total * 0.4}
    return {"case": case, "outcome": outcome, "total_s": total, "steps_s": steps, "peak_mb": peak}


def test_summary_uses_nearest_rank_p95_and_both_budgets() -> None:
    perf = _load()
    assert perf.quantile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0 and perf.quantile([5.0], 0.95) == 5.0
    assert perf.quantile(list(range(1, 101)), 0.95) == 95
    rows = [_row(f"c{i}", float(i), 100.0 * i) for i in range(1, 21)]  # p95 = 19 s, peak 2000 MiB
    lines, ok = perf.summarise(rows, 30.0, 3072.0)
    assert ok and "p95   19.0 s" in lines[1] and "signalyth" in lines[3]
    assert not perf.summarise(rows, 18.0, 3072.0)[1]  # over the time budget
    assert not perf.summarise(rows, 30.0, 1999.0)[1]  # over the memory budget
    lines, ok = perf.summarise([*rows, _row("bad", 1.0, 1.0, "failed")], 30.0, 3072.0)
    assert not ok and "1 not ok: bad" in lines[0]  # a failed case is never within budget
    assert perf.summarise([], 30.0, 3072.0) == (["  no case finished ok; failed: none run"], False)


def test_one_case_child_reports_steps_and_peak(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    perf = _load()
    assert cli.main(["data", "fetch", "synth"]) == 0
    capsys.readouterr()
    assert perf.main(["--one", "synth", "synth-01", str(tmp_path / "runs")]) == 0
    row = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert row["outcome"] == "ok" and row["peak_mb"] > 0 and row["total_s"] > 0
    assert {"infralume", "signalyth", "anomara", "causync", "causalith"} <= set(row["steps_s"])


def test_csv_rows_are_sorted_and_keep_failed_cases() -> None:
    perf = _load()
    rows = [
        {**_row("b", 2.0, 200.04), "system": "re2-tt", "pass": 2},
        {**_row("a", 1.23456, 100.0), "system": "re2-tt", "pass": 2},
        {**_row("a", 3.0, 150.0), "system": "re2-tt", "pass": 1},
        {"case": "z", "outcome": "exit 3", "system": "re2-ob", "pass": 1},
    ]
    header, table = perf.csv_rows(rows)
    assert header == [
        "case",
        "system",
        "pass",
        "outcome",
        "wall_ms",
        "peak_rss_mb",
        "anomara_ms",
        "signalyth_ms",
    ]
    assert [r[:3] for r in table] == [
        ["z", "re2-ob", 1],
        ["a", "re2-tt", 1],
        ["a", "re2-tt", 2],
        ["b", "re2-tt", 2],
    ]
    assert table[0][3:] == ["exit 3", "", "", "", ""]  # a case that did not finish has empty cells
    assert table[2][3:] == ["ok", 1234.6, 100.0, 493.8, 740.7]
    assert perf.csv_rows([]) == (["case", "system", "pass", "outcome", "wall_ms", "peak_rss_mb"], [])


def test_two_passes_write_one_row_per_case_and_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    perf = _load()
    assert cli.main(["data", "fetch", "synth"]) == 0
    out = tmp_path / "perf.csv"
    code = perf.main(
        ["synth", "--cases", "1", "--passes", "2", "--out", str(out), "--runs-root", str(tmp_path / "r")]
    )
    printed = capsys.readouterr().out
    assert code == 0 and "pass 1 of 2" in printed and "pass 2 of 2" in printed
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("case,system,pass,outcome,wall_ms,peak_rss_mb,") and len(lines) == 3
    assert [ln.split(",")[1:4] for ln in lines[1:]] == [["synth", "1", "ok"], ["synth", "2", "ok"]]
    assert (tmp_path / "r" / "pass-1").is_dir() and (tmp_path / "r" / "pass-2").is_dir()
