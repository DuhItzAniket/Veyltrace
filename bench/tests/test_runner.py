"""Tests of the bench runner as a library: synth end to end, outcomes, case lists, guards.

The R-00 stub engines rank nothing (slate rankers_active == []), so every synth fault case must be
scored as unranked (empty ranks, misses) and synth-05, the no-fault normal window, with null hits
(04 §7 "Unranked runs", added by #14; packages/causatrix/README.md). Outputs go to tmp_path, never
into bench/results. The CLI over this runner (#14) is tested in test_cli.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pytest

from veyltrace_bench import runner
from veyltrace_core import cli, io, textio
from veyltrace_core.config import find_config_dir
from veyltrace_core.errors import ConfigError, UsageError
from veyltrace_core.hashing import sha256_text_lf
from veyltrace_core.ids import case_id
from veyltrace_core.pipeline import Outcome, RunSummary

SMOKE = Path(__file__).resolve().parents[1] / "experiments" / "synth-smoke.yaml"
NORMAL_WINDOW = case_id("synth-05")
HITS = ("hit_at_1", "hit_at_3", "hit_at_5", "retrieval_hit", "pool_hit", "in_set")
STUB = {"run_outcome": "ok", "method": "veyltrace:off", "ranks": [], "set_size": None}


def _rows(out: Path, *, unmeasured: bool = False) -> dict[str, dict[str, object]]:
    """per_case.csv rows by case id, read back through the bench_result contract."""
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    rows: list[dict[str, object]] = table.to_pylist()
    blank = {"wall_ms": None, "peak_rss_mb": None} if unmeasured else {}
    return {str(r["case_id"]): r | blank for r in rows}


def test_synth_smoke_runs_end_to_end(tmp_path: Path) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0

    def run() -> Path:
        return runner.run_experiment(SMOKE, out_root=tmp_path / "results", runs_root=tmp_path / "runs")[0]

    out = run()
    assert out == tmp_path / "results" / "synth-smoke"
    rows = _rows(out)
    assert sorted(rows) == sorted(case_id(f"synth-0{i}") for i in range(1, 6))
    for row in rows.values():
        assert {c: row[c] for c in STUB} == STUB and isinstance(row["wall_ms"], float)
        assert isinstance(row["peak_rss_mb"], float) and row["peak_rss_mb"] > 0  # measured by the child
        assert row["verdict_hash"] and row["status"]
        assert [row[c] for c in HITS] == ([None] * 6 if row["case_id"] == NORMAL_WINDOW else [False] * 6)
    summary, manifest = (textio.read_text(out / name) for name in ("summary.json", "manifest.json"))
    for name in ("summary", "manifest"):  # both are contracts now (03 §13.3, §13.4), not free JSON
        io.read_path(f"bench_{name}", out / f"{name}.json", validate=True)
    assert '"outcomes":{"failed":0,"no_alert":0,"ok":5,"rejected":0,"timeout":0}' in summary
    for part in ('"n_unranked":4', '"n_fault":4', '"n_chance":4', '"ac_at_1":0.0', '"chance_at_1":0.16666'):
        assert part in summary
    assert '"mrr":{"mrr":0.0}' in summary and '"rerank_at_1":null' in summary  # only the YAML's metrics
    assert f'"experiment_sha256":"{sha256_text_lf(SMOKE)}"' in manifest and manifest.count('"run_id"') == 5
    assert manifest.count('"inputs_sha256":"') == 6 and '"cases_without_inputs":[]' in manifest
    assert run() == out  # again on the same runs root: bench empties its dir, all re-run
    assert [textio.read_text(out / n) for n in ("summary.json", "manifest.json")] == [summary, manifest]
    assert all(isinstance(r["wall_ms"], float) for r in _rows(out).values())  # measured, never reused
    blank = {"wall_ms": None, "peak_rss_mb": None}
    assert _rows(out, unmeasured=True) == {c: r | blank for c, r in rows.items()}


def test_run_outcomes_are_learned_and_scored_as_misses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    runs: list[Outcome] = ["failed", "no_alert", "rejected", "failed", "failed"]
    outcomes = dict(zip(sorted(case_id(f"synth-0{i}") for i in range(1, 6)), runs, strict=True))
    cached = False

    def fake_run_case(dataset: str, case: str, ai_mode: str, **_: object) -> RunSummary:
        outcome = outcomes[case]
        return RunSummary(dataset, case, "0" * 16, tmp_path, outcome, "x", None, (), (), {}, cached=cached)

    def run() -> tuple[Path, dict[str, object]]:
        return runner.run_experiment(SMOKE, out_root=tmp_path / "results", runs_root=tmp_path / "runs")

    monkeypatch.setattr(runner, "IN_PROCESS", True)  # the fake run_case lives in this process
    monkeypatch.setattr(runner, "run_case", fake_run_case)
    out, summary = run()
    rows = _rows(out)
    assert {c: r["run_outcome"] for c, r in rows.items()} == outcomes
    assert {c: r["hit_at_1"] for c, r in rows.items()} == dict.fromkeys(rows, False) | {NORMAL_WINDOW: None}
    assert all(r["status"] is None and r["ranks"] == [] and r["set_size"] is None for r in rows.values())
    groups = summary["groups"]
    assert isinstance(groups, list) and len(groups) == 1  # summary values are JSON, typed as object
    chance = groups[0]["metrics"]["chance"]
    assert (groups[0]["n_fault"], groups[0]["n_chance"], chance["chance_at_1"]) == (4, 0, None)  # no n_i
    cached = True  # a reused run has no wall time: it could hide a timeout (04 §9), so it is refused
    with pytest.raises(ConfigError, match="reuses run"):
        run()


def test_case_and_exclude_lists_pick_the_runs_and_are_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    ids = sorted(case_id(f"synth-0{i}") for i in range(1, 6))
    cases, dev, exp = (tmp_path / f"{name}.yaml" for name in ("cases", "dev", "exp"))
    cases.write_text(f"[{', '.join(ids[:3])}]\n", encoding="utf-8")
    dev.write_text(f"[{ids[1]}]\n", encoding="utf-8")
    text = textio.read_text(SMOKE).replace("cases: all", f"cases: {json.dumps(cases.as_posix())}")
    exp.write_text(text.replace("exclude: null", f"exclude: {json.dumps(dev.as_posix())}"), encoding="utf-8")

    def fake_run_case(dataset: str, case: str, ai_mode: str, **_: object) -> RunSummary:
        return RunSummary(dataset, case, "0" * 16, tmp_path, "failed", "x", None, (), (), {})

    monkeypatch.setattr(runner, "IN_PROCESS", True)  # the fake run_case lives in this process
    monkeypatch.setattr(runner, "run_case", fake_run_case)  # absolute lists: repo / path == path
    out, summary = runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    assert sorted(_rows(out)) == [ids[0], ids[2]] and summary["excluded"] == {"synth": [ids[1]]}
    (part,) = json.loads(textio.read_text(out / "manifest.json"))["datasets"]
    assert (part["dataset"], part["cases"], part["excluded"]) == ("synth", [ids[0], ids[2]], [ids[1]])


def test_unsupported_experiments_are_refused_before_the_first_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exp = tmp_path / "rcaeval.yaml"
    exp.write_text(textio.read_text(SMOKE).replace("kind: veyltrace", "kind: rcaeval"), encoding="utf-8")

    def no_run(*_: object, **__: object) -> RunSummary:
        raise AssertionError("an unsupported experiment must not run a case")

    monkeypatch.setattr(runner, "IN_PROCESS", True)  # the fake run_case lives in this process
    monkeypatch.setattr(runner, "run_case", no_run)
    with pytest.raises(ConfigError, match=r"baselines, R-05"):
        runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rcaeval.yaml"]  # no results or runs dir


def test_timeout_is_set_by_bench_and_is_a_miss() -> None:
    assert runner.run_outcome("ok", 600_001.0, 600) == "timeout"
    assert runner.run_outcome("ok", 600_000.0, 600) == "ok"
    assert runner.run_outcome("no_alert", 1.0, 600) == "no_alert"


def test_table_mode_and_synth_without_out_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = find_config_dir().parent.joinpath(*runner.RESULTS_DIR, "synth-smoke")
    monkeypatch.setattr(runner, "code_state", lambda _: {"dirty": False, "bench_dirty": True})
    with pytest.raises(UsageError, match="dirty"):
        runner.run_experiment(SMOKE, out_root=tmp_path, table=True)
    monkeypatch.setattr(runner, "code_state", lambda _: {"dirty": False, "bench_dirty": False})
    with pytest.raises(UsageError, match="synth"):
        runner.run_experiment(SMOKE, out_root=tmp_path, table=True)
    for out_root in (None, results.parent):  # smoke output never lands in bench/results, even asked
        with pytest.raises(UsageError, match="synth"):
            runner.run_experiment(SMOKE, out_root=out_root)
    assert not any(tmp_path.iterdir()) and not results.exists()  # refused before any run or write
