"""scripts/rq5_ai_cost.py (#545): the RQ5 AI-path cost read from kept runs' proposals.json."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from types import ModuleType

from veyltrace_bench.summary import nearest_rank

ROOT = Path(__file__).resolve().parents[1]
RQ2 = "re2-oracle-rq2-v1"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rq5_ai_cost", ROOT / "scripts" / "rq5_ai_cost.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _world(tmp: Path) -> tuple[Path, Path]:
    """A recording replay CSV with three Tier 1 runs (two systems), one Tier 2 row and one run of
    another experiment, and the matching kept runs."""
    results, runs_root = tmp / "results", tmp / "runs"
    rows = [
        ("1", "aaaaaaaaaaaaaaa1", "c00000000001", "re2-ob", "ob", "1", RQ2, 120000.04, 5000, 900, 1),
        ("1", "aaaaaaaaaaaaaaa2", "c00000000001", "re2-ob", "ob", "2", RQ2, 250000.0, 6000, 1800, 2),
        ("1", "aaaaaaaaaaaaaaa3", "c00000000002", "re2-tt", "tt", "1", RQ2, 90000.0, 4000, 700, 1),
        ("2", "aaaaaaaaaaaaaaa1", "c00000000001", "re2-ob", "ob", "1", RQ2, 1.0, 1, 1, 1),
        ("1", "aaaaaaaaaaaaaaa4", "c00000000003", "re2-ss", "ss", "1", "other-experiment", 1.0, 1, 1, 1),
    ]
    path = results / "replay" / "recording" / "replay.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["tier", "run_id", "case_id", "dataset", "system", "seed", "experiments"])
        for tier, rid, case, ds, sysname, seed, exp, *_ in rows:
            w.writerow([tier, rid, case, ds, sysname, seed, f"['{exp}']"])
    for tier, rid, case, ds, _, _, _, wall, tin, tout, turns in rows:
        if tier != "1":
            continue
        d = runs_root / "bench-ai" / ds / case / rid
        d.mkdir(parents=True)
        used = {"wall_ms": wall, "tokens_in": tin, "tokens_out": tout, "turns": turns}
        (d / "proposals.json").write_text(
            json.dumps({"status": "complete", "budget_used": used}), encoding="utf-8"
        )
    return results, runs_root


def test_one_row_per_recorded_run_and_nearest_rank_percentiles(tmp_path: Path) -> None:
    rq5 = _script()
    results, runs_root = _world(tmp_path)
    assert rq5.main(["--runs-root", str(runs_root), "--results", str(results)]) == 0
    out = results / "rq5-ai-cost"
    with (out / "re2-oracle-rq2-v1.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["run_id"] for r in rows] == ["aaaaaaaaaaaaaaa1", "aaaaaaaaaaaaaaa2", "aaaaaaaaaaaaaaa3"]
    # the Tier 2 row and the other experiment's run are left out
    assert rows[0]["model_wall_ms"] == "120000.0" and rows[1]["turns"] == "2"
    ob = json.loads((out / "summary.json").read_text(encoding="utf-8"))["systems"]["ob"]
    assert ob["n"] == 2 and ob["status"] == {"complete": 2}
    assert ob["model_wall_ms_p95"] == nearest_rank([120000.0, 250000.0], 95) == 250000.0
    assert ob["model_wall_ms_p50"] == nearest_rank([120000.0, 250000.0], 50) == 120000.0


def test_the_script_agrees_with_bench_on_the_percentile_rule() -> None:
    rq5 = _script()
    for values in ([3.0], [5.0, 1.0, 4.0, 2.0], [float(v) for v in range(1, 102)]):
        for p in (50, 95):
            assert rq5.nearest_rank(values, p) == nearest_rank(values, p)


def test_no_recorded_runs_is_refused(tmp_path: Path) -> None:
    rq5 = _script()
    results = tmp_path / "results"
    path = results / "replay" / "recording" / "replay.csv"
    path.parent.mkdir(parents=True)
    path.write_text("tier,run_id,case_id,dataset,system,seed,experiments\n", encoding="utf-8")
    assert rq5.main(["--runs-root", str(tmp_path), "--results", str(results)]) == 2
