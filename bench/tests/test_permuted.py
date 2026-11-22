"""Proposal permutations in memory (04 §5.2 H2c; #399): Causentra's verdict ignores proposal order."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from veyltrace_bench import calibration, permuted, runner
from veyltrace_causentra.api import verdict_for
from veyltrace_contracts import models
from veyltrace_core import cli, io, textio
from veyltrace_core.config import CONFIG_DIR_ENV
from veyltrace_core.pipeline import run_case

REPO = Path(__file__).resolve().parents[2]
ARM = "ai: {mode: record, relentra_mode: brief, model: qwen3.5-9b-q4_k_m, seeds: [1]}"
PERMUTE = f"""\
experiment_id: synth-permute
description: "proposal permutations on synth (never reported)"
dataset: {{parts: [synth], cases: all, exclude: null, normal_windows: none}}
protocol: {{alert: oracle, shift_s: 0, sources_drop: [], permute_proposals: {{n: 2, seed: 3}}}}
methods:
  - {{id: "veyltrace:brief", kind: veyltrace, {ARM}}}
metrics: [ac_at_k, permutation_invariance]
"""


def test_a_permuted_verdict_is_the_verdict(tmp_path: Path) -> None:
    """Real proposals on a synth run's inputs: every seeded order gives one verdict_hash, and the
    orders do differ (so the check is not vacuous)."""
    assert cli.main(["data", "fetch", "synth"]) == 0
    s = run_case("synth", "synth-01", "off", runs_root=tmp_path / "runs")
    ctx, cfg, inp = calibration.causentra_inputs(s.run_dir)
    example = json.loads(textio.read_text(REPO / "contracts" / "examples" / "proposals.example.json"))
    proposals = models.Proposals.model_validate(example | {"case_id": ctx.case_id})
    base = replace(inp, proposals=proposals)
    want = verdict_for(ctx, cfg, base)[1]["verdict_hash"]
    orders = set()
    for i in range(8):
        shuffled = permuted.permuted(base, np.random.default_rng([3, i]))
        assert shuffled.proposals is not None
        orders.add(tuple(p.proposal_id for p in shuffled.proposals.proposals))
        assert verdict_for(ctx, cfg, shuffled)[1]["verdict_hash"] == want
    assert len(orders) > 1


def test_permutations_are_rows_without_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "repo" / "config"
    shutil.copytree(REPO / "config", config)
    relentra = config / "relentra.yaml"  # Relentra's seed key (#354), as in test_ai_arms
    if b"seed_index" not in relentra.read_bytes():  # once #354 is on main the key exists: keep it
        relentra.write_bytes(relentra.read_bytes() + b"\nsampler:\n  seed_index: 0\n")
    llm = config / "llm.yaml"  # FakeProvider: no model server in tests (08 §7)
    llm.write_bytes(llm.read_bytes().replace(b"provider: ollama", b"provider: fake"))
    pinned = b'gguf_sha256: "' + b"ab" * 32 + b'"'  # a test digest: AI arms run on a pinned GGUF (#315)
    llm.write_bytes(llm.read_bytes().replace(b"gguf_sha256: null", pinned))
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config))
    monkeypatch.setattr(runner, "IN_PROCESS", True)
    assert cli.main(["data", "fetch", "synth"]) == 0
    exp = tmp_path / "exp.yaml"
    textio.write_bytes(exp, PERMUTE.encode())
    out, _ = runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    rows = table.to_pylist()
    by_case: dict[str, dict[str, object]] = {}
    for r in rows:
        by_case.setdefault(str(r["case_id"]), {})[str(r["variant"])] = r["verdict_hash"]
    assert all(
        sorted(v) == ["None", "perm-1", "perm-2"] and len(set(v.values())) == 1 for v in by_case.values()
    )
    runs = json.loads(textio.read_text(out / "manifest.json"))["runs"]
    assert len(runs) == 5  # the five record runs; permutations make no run and no model call
    group = json.loads(textio.read_text(out / "summary.json"))["groups"][0]
    assert group["metrics"]["permutation_invariance"] == {"permutation_invariance": 1.0, "n_cases": 5}
