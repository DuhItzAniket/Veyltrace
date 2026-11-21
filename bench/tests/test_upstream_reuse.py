"""Upstream reuse for slate-scored methods (R-16 B5, #413): identical slates, safe fallbacks.

A causatrix:<ranker> method restarts at Causatrix on veyltrace:off's run of the same case. Its slate
must be byte-identical to a full re-run (synth-01..05, every ranker below), and anything that could
make the reused steps differ falls back to a full run.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pyarrow as pa
import pytest

from veyltrace_bench import runner, upstream
from veyltrace_bench.experiment import load_experiment
from veyltrace_core import cli, io, textio
from veyltrace_core.config import CONFIG_DIR_ENV, resolve_config
from veyltrace_core.pipeline import run_case

REPO = Path(__file__).resolve().parents[2]
RANKERS = ("baro_rs", "graph_walk", "prism_m")
METHODS = "".join(
    f'  - {{id: "causatrix:{r}", kind: causatrix, overrides: {{causatrix.rankers.enabled: [{r}]}}}}\n'
    for r in RANKERS
)
REUSE = f"""\
experiment_id: synth-reuse
description: "upstream reuse on synth (never reported)"
dataset: {{parts: [synth], cases: all, exclude: null, normal_windows: none}}
protocol: {{alert: oracle, shift_s: 0, sources_drop: []}}
methods:
  - {{id: "veyltrace:off", kind: veyltrace, ai: {{mode: "off"}}, overrides: {{}}}}
{METHODS}metrics: [ac_at_k]
"""


@pytest.fixture
def synth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "repo" / "config"
    shutil.copytree(REPO / "config", config)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config))
    monkeypatch.setattr(runner, "IN_PROCESS", True)
    assert cli.main(["data", "fetch", "synth"]) == 0
    exp = tmp_path / "reuse.yaml"
    textio.write_bytes(exp, REUSE.encode())
    return exp


def _run(
    tmp_path: Path, exp: Path, name: str
) -> tuple[list[dict[str, object]], dict[tuple[str, str], bytes]]:
    """(rows, {(method, case): slate.json bytes}) of one run of the experiment."""
    out, _ = runner.run_experiment(exp, out_root=tmp_path / name, runs_root=tmp_path / f"runs-{name}")
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    runs = json.loads(textio.read_text(out / "manifest.json"))["runs"]
    slates: dict[tuple[str, str], bytes] = {}
    for r in runs:
        found = sorted((tmp_path / f"runs-{name}").rglob(f"{r['run_id']}*/slate.json"))
        assert found, r
        slates[(r["method"], r["case_id"])] = found[0].read_bytes()
    return table.to_pylist(), slates


def test_reused_slates_are_byte_identical_to_full_runs(
    tmp_path: Path, synth: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows, slates = _run(tmp_path, synth, "reuse")
    partial = sorted(p.name for p in (tmp_path / "runs-reuse").rglob("*~causatrix"))
    assert len(partial) == 5 * len(RANKERS)  # every causatrix:<ranker> case ran Causatrix alone
    monkeypatch.setattr(upstream, "applies", lambda _m: False)  # the same experiment, every run full
    full_rows, full_slates = _run(tmp_path, synth, "full")
    assert not list((tmp_path / "runs-full").rglob("*~causatrix"))
    assert slates == full_slates  # byte for byte, per (method, case), synth-01..05
    scored = ("case_id", "method", "ranks", "hit_at_1", "hit_at_3", "hit_at_5", "retrieval_hit")
    assert [{k: r[k] for k in scored} for r in rows] == [{k: r[k] for k in scored} for r in full_rows]


def test_a_source_that_differs_upstream_is_not_reused(tmp_path: Path, synth: Path) -> None:
    exp = load_experiment(synth)
    method = exp.methods[1]
    assert upstream.applies(method) and upstream.source_of(exp, method) == exp.methods[0]
    s = run_case("synth", "synth-02", "off", runs_root=tmp_path / "runs")
    over = runner.overrides_for(exp, method)
    lock = resolve_config(over, dataset="synth", ai_mode="off").lock_bytes()
    assert upstream.mismatch(s.run_dir, lock) is None  # off's run serves causatrix:baro_rs
    other = resolve_config(
        over | {"faultloom.cards.max_tokens": 1499}, dataset="synth", ai_mode="off"
    ).lock_bytes()
    assert upstream.mismatch(s.run_dir, other) == "config sections ['faultloom'] differ"
    anomalies = s.run_dir / "anomalies.parquet"
    anomalies.write_bytes(anomalies.read_bytes() + b"\0")  # a reused output edited after the run
    assert upstream.mismatch(s.run_dir, lock) == "anomalies.parquet no longer holds anomara's output"
    assert not upstream.applies(exp.methods[0])  # veyltrace:off itself
    assert upstream.source_of(exp.model_copy(update={"methods": exp.methods[1:]}), method) is None


def test_a_mismatch_falls_back_to_a_full_run(
    tmp_path: Path, synth: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(upstream, "mismatch", lambda *_a: "forced for the test")
    _run(tmp_path, synth, "fallback")
    assert not list((tmp_path / "runs-fallback").rglob("*~causatrix"))  # every method ran in full
