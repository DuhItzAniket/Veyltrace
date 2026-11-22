"""AI arms in the runner (04 §8 "LLM arms"; #397): one run per seed, kept record runs, replay.

Relentra brief mode (#354-#356) runs against FakeProvider (the config copy sets llm.provider fake,
08 §7): every model call is a recorded `unscripted` error, so runs record and replay real
cassettes without a model server. relentra.sampler.seed_index (#354) carries each seed. The copy
pins a test GGUF digest, because an AI arm counts only on the pinned GGUF (#315).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from veyltrace_bench import ai_arms, answer_keys, runner, splits
from veyltrace_bench.experiment import Experiment, load_experiment
from veyltrace_contracts import models
from veyltrace_core import cli, io, textio
from veyltrace_core.calibration import load_calibration
from veyltrace_core.config import CONFIG_DIR_ENV
from veyltrace_core.errors import ConfigError

REPO = Path(__file__).resolve().parents[2]
GGUF = "ab" * 32  # the test copy's pinned model.gguf_sha256
UNPINNED = b"gguf_sha256: null"
BRIEF = """\
experiment_id: synth-brief
description: "AI arm on synth (never reported)"
dataset: {parts: [synth], cases: all, exclude: null, normal_windows: none}
split: {family: null, scheme: none}
protocol: {alert: oracle, shift_s: 0, sources_drop: []}
methods:
  - id: "veyltrace:brief"
    kind: veyltrace
    ai: {mode: record, relentra_mode: brief, model: qwen3.5-9b-q4_k_m, seeds: [1, 2]}
calibration: {fit: false}
metrics: [ac_at_k, cost]
resources: {workers: 1, timeout_s: 600}
"""


@pytest.fixture
def ai_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of config/ with Relentra's seed key (#354), as the runner's repo root."""
    config = tmp_path / "repo" / "config"
    shutil.copytree(REPO / "config", config)
    relentra = config / "relentra.yaml"
    if b"seed_index" not in relentra.read_bytes():  # once #354 is on main the key exists: keep it
        relentra.write_bytes(relentra.read_bytes() + b"\nsampler:\n  seed_index: 0\n")
    llm = config / "llm.yaml"  # FakeProvider: no model server in tests (08 §7)
    llm.write_bytes(llm.read_bytes().replace(b"provider: ollama", b"provider: fake"))
    _set_digest(config, GGUF)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config))
    assert cli.main(["data", "fetch", "synth"]) == 0
    return config


def _set_digest(config: Path, digest: str | None) -> None:
    """Pin config/llm.yaml model.gguf_sha256 of the copy to `digest` (None: unpinned)."""
    llm = config / "llm.yaml"
    lines = textio.read_text(llm).splitlines(keepends=True)
    value = f'"{digest}"' if digest is not None else "null"
    pinned = [f"  gguf_sha256: {value}\n" if ln.strip().startswith("gguf_sha256:") else ln for ln in lines]
    textio.write_bytes(llm, "".join(pinned).encode())


def _yaml(tmp_path: Path, text: str, name: str = "brief") -> Path:
    path = tmp_path / f"{name}.yaml"
    textio.write_bytes(path, text.encode())
    return path


def _rows(out: Path) -> list[dict[str, object]]:
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    return table.to_pylist()


def _kept(tmp_path: Path) -> list[Path]:
    return sorted(p.parent for p in (tmp_path / "runs" / "bench-ai").rglob("receipt.json"))


def test_each_seed_is_a_kept_record_run_and_a_second_run_replays_it(tmp_path: Path, ai_config: Path) -> None:
    exp = _yaml(tmp_path, BRIEF)
    out, _ = runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    rows = _rows(out)
    assert len(rows) == 10 and {(r["seed"], r["ai_mode"]) for r in rows} == {(1, "record"), (2, "record")}
    assert all(r["tokens_in"] == 0 and r["tokens_out"] == 0 for r in rows)  # the stub's budget_used
    kept = _kept(tmp_path)
    assert len(kept) == 10  # one record run per (case, seed), outside bench's emptied dir
    seeds = set()
    for run_dir in kept:
        lock: dict[str, Any] = json.loads(textio.read_text(run_dir / "config.lock.json"))
        relentra = lock["sections"]["relentra"]
        seeds.add((run_dir.parent.name, relentra["sampler"]["seed_index"], relentra["mode"]))
        ai = io.read_model("run_manifest", run_dir, models.RunManifest).ai
        assert ai.mode == "record" and (ai.model, ai.gguf_sha256) == ("qwen3.5:9b", GGUF)  # RQ6 Tier 2
    assert len(seeds) == 10 and {s for _, s, _ in seeds} == {1, 2} and {m for *_, m in seeds} == {"brief"}

    again, _ = runner.run_experiment(exp, out_root=tmp_path / "results2", runs_root=tmp_path / "runs")
    replayed = _rows(again)
    assert {r["ai_mode"] for r in replayed} == {"replay"} and _kept(tmp_path) == kept  # no new record run
    assert all(r["wall_ms"] is None and r["tokens_in"] is None for r in replayed)  # a replay has no cost
    by_key = {(r["case_id"], r["seed"]): r["verdict_hash"] for r in rows}
    assert {(r["case_id"], r["seed"]): r["verdict_hash"] for r in replayed} == by_key
    manifest = json.loads(textio.read_text(again / "manifest.json"))
    assert manifest["seeds"] == [1, 2]


def test_ai_arms_need_relentras_seed_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "repo" / "config"
    shutil.copytree(REPO / "config", config)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config))
    assert cli.main(["data", "fetch", "synth"]) == 0
    if "seed_index" in textio.read_text(config / "relentra.yaml"):
        pytest.skip("Relentra's seed key is on main (#354): nothing to refuse")
    with pytest.raises(ConfigError, match="seed_index"):
        runner.run_experiment(
            _yaml(tmp_path, BRIEF), out_root=tmp_path / "results", runs_root=tmp_path / "runs"
        )
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize(
    ("ai", "match"),
    [
        ("{mode: record, relentra_mode: brief, seeds: []}", "needs relentra_mode and seeds"),
        ("{mode: record, seeds: [1]}", "needs relentra_mode and seeds"),
        ('{mode: "off", seeds: [1]}', "no relentra_mode or seeds"),
        ("{mode: replay, relentra_mode: brief, seeds: [1]}", "bench replays"),
        ("{mode: record, relentra_mode: brief, seeds: [1, 1]}", "distinct"),
    ],
)
def test_an_ai_block_is_complete(tmp_path: Path, ai: str, match: str) -> None:
    text = BRIEF.replace("{mode: record, relentra_mode: brief, model: qwen3.5-9b-q4_k_m, seeds: [1, 2]}", ai)
    with pytest.raises(ConfigError, match=match):
        load_experiment(_yaml(tmp_path, text))
    override = BRIEF.replace(
        "    kind: veyltrace\n", "    kind: veyltrace\n    overrides: {relentra.mode: investigate}\n"
    )
    with pytest.raises(ConfigError, match="bench sets them from `ai`"):
        load_experiment(_yaml(tmp_path, override, "override"))


def test_a_fitted_ai_arm_writes_its_own_arms_files(
    tmp_path: Path, ai_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The calibration ai_arm is the Relentra mode (03 §12.1); seeds pool into one file per fold."""
    monkeypatch.setattr(runner, "IN_PROCESS", True)
    text = BRIEF.replace("split: {family: null, scheme: none}", "split: {family: synth, scheme: crossfit2}")
    text = text.replace("calibration: {fit: false}", "calibration: {fit: true}").replace("[1, 2]", "[3, 4]")
    out, _ = runner.run_experiment(
        _yaml(tmp_path, text), out_root=tmp_path / "results", runs_root=tmp_path / "runs"
    )
    names = sorted(p.name for p in (ai_config / "calibration").glob("*.json"))
    assert names == ["synth.brief.oracle.foldA.json", "synth.brief.oracle.foldB.json"]
    rows = _rows(out)
    assert {(r["seed"], r["ai_mode"]) for r in rows} == {(3, "record"), (4, "record")} and all(
        r["fold"] for r in rows
    )
    keys = {
        c: k for c, k in answer_keys.load_answer_keys("synth").items() if c in {r["case_id"] for r in rows}
    }
    plan = splits.crossfit2(keys, 20261108)
    for fold in splits.FOLDS:  # fitted on the first seed only: n = fault cases, not cases x seeds
        content = load_calibration(ai_config / "calibration" / f"synth.brief.oracle.{fold}.json").content
        assert content.n == sum(not keys[c].is_no_fault for c in plan.fits[fold])


def test_an_unpinned_gguf_refuses_before_the_first_case(tmp_path: Path, ai_config: Path) -> None:
    _set_digest(ai_config, None)  # config/llm.yaml as it ships until L-01 pins the digest
    with pytest.raises(ConfigError, match="gguf_sha256 is null"):
        runner.run_experiment(
            _yaml(tmp_path, BRIEF), out_root=tmp_path / "results", runs_root=tmp_path / "runs"
        )
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize(
    ("method", "match"),
    [
        ("    overrides: {llm.model.name: 'qwen3.5:4b'}", "'qwen3.5:4b' is not qwen3.5-9b-q4_k_m"),
        (f"    overrides: {{llm.model.gguf_sha256: '{'cd' * 32}'}}", f"is not the pinned {GGUF}"),
        ("", "'qwen3.5-4b-q4_k_m' is not a pinned 04 model id"),
    ],
)
def test_a_method_on_another_model_refuses_before_the_first_case(
    tmp_path: Path, ai_config: Path, method: str, match: str
) -> None:
    kind = "    kind: veyltrace"
    text = BRIEF.replace(kind, f"{kind}\n{method}" if method else kind)
    if not method:
        text = text.replace("model: qwen3.5-9b-q4_k_m", "model: qwen3.5-4b-q4_k_m")
    with pytest.raises(ConfigError, match=match):
        runner.run_experiment(
            _yaml(tmp_path, text), out_root=tmp_path / "results", runs_root=tmp_path / "runs"
        )
    assert not (tmp_path / "runs").exists()


def test_a_run_on_another_gguf_is_rejected_never_scored(
    tmp_path: Path, ai_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """config/llm.yaml changes after the check (an edit mid-experiment): every run resolves another
    digest than the pin, so each row is rejected: no ranks or verdict, a miss (03 §13.2; 04 §7)."""
    monkeypatch.setattr(runner, "IN_PROCESS", True)
    check = ai_arms.check

    def edit_after_check(exp: Experiment) -> dict[str, ai_arms.Pin]:
        pins = check(exp)
        _set_digest(ai_config, "cd" * 32)
        return pins

    monkeypatch.setattr(ai_arms, "check", edit_after_check)
    out, summary = runner.run_experiment(
        _yaml(tmp_path, BRIEF), out_root=tmp_path / "results", runs_root=tmp_path / "runs"
    )
    rows = _rows(out)
    assert len(rows) == 10 and {r["run_outcome"] for r in rows} == {"rejected"}
    assert all(not r["ranks"] and r["status"] is None and r["verdict_hash"] is None for r in rows)
    assert all(r[c] in (None, False, 0) for r in rows for c in ("hit_at_1", "hit_at_5", "in_set"))  # misses
    groups = summary["groups"]
    assert isinstance(groups, list) and all(g["outcomes"]["rejected"] == g["n_rows"] for g in groups)
    assert len(_kept(tmp_path)) == 10  # the runs happened; they are listed in the manifest, not scored
    assert len(json.loads(textio.read_text(out / "manifest.json"))["runs"]) == 10
