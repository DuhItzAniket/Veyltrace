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
