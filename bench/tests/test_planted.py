"""Planted decoy proposals (04 §5.2 H2b; #399): healthy decoys, valid derived runs, no model call."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import cast

import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_bench import experiment, planted, runner
from veyltrace_bench.experiment import ProposalDraw
from veyltrace_bench.metrics import RANK_SEPARATOR
from veyltrace_contracts import models
from veyltrace_core import cli, io, textio
from veyltrace_core.config import CONFIG_DIR_ENV

REPO = Path(__file__).resolve().parents[2]
ARM = "ai: {mode: record, relentra_mode: brief, model: qwen3.5-9b-q4_k_m, seeds: [1]}"
PLANTED = f"""\
experiment_id: synth-planted
description: "planted decoys on synth (never reported)"
dataset: {{parts: [synth], cases: all, exclude: null, normal_windows: none}}
protocol: {{alert: oracle, shift_s: 0, sources_drop: [], inject_proposals: {{n: 1, seed: 4}}}}
methods:
  - {{id: "veyltrace:brief", kind: veyltrace, {ARM}}}
  - {{id: "agent-only:brief", kind: agent_only, {ARM}}}
metrics: [ac_at_k, decoy_top1_change]
"""
SERVICES = ("cart", "cart-db", "checkout", "frontend", "payment")


@given(st.sampled_from([None, "cart", "frontend"]), st.integers(1, 6), st.integers(0, 99))
def test_decoys_are_healthy_seeded_and_capped(root: str | None, n: int, seed: int) -> None:
    draw = ProposalDraw(n=n, seed=seed)
    got = planted.decoys(SERVICES, root, "59e0d31bcc42", draw)
    assert got == planted.decoys(SERVICES, root, "59e0d31bcc42", draw) and len(set(got)) == len(got)
    healthy = [s for s in SERVICES if root is None or s.replace("-db", "") != root]
    assert set(got) <= set(healthy) and len(got) == min(n, len(healthy))  # cart-db is cart (coarse)


def test_planted_proposals_pass_the_contract_writer() -> None:
    example = json.loads(textio.read_text(REPO / "contracts" / "examples" / "proposals.example.json"))
    recorded = models.Proposals.model_validate(example)
    got = planted.planted(recorded, SERVICES, "checkout", ProposalDraw(n=2, seed=4), ["frontend", "cart"])
    io.prepare("proposals", got)  # schema, model and x-sort order (03 §9.1)
    assert (got["mode"], got["model"], len(got["proposals"])) == (
        "external",
        None,
        len(recorded.proposals) + 2,
    )
    mine = [p for p in got["proposals"] if p["rationale"] == planted.RATIONALE]
    assert all(p["hypothesis"]["service"] != "checkout" for p in mine)
    assert [c["predicate"] for c in mine[0]["claims"]] == ["onset_before", "zscore_above"]
    for (
        p
    ) in mine:  # the onset claim names the slate's top-1 (the next one for the top-1 itself), never the root
        want = "cart" if p["hypothesis"]["service"] == "frontend" else "frontend"
        assert p["claims"][0]["args"] == {"other_service": want}
    assert got["status"] == recorded.status and got["budget_used"]["tokens_in"] == 0  # no model call


def test_planted_runs_need_no_model_call_and_agent_only_sees_the_decoy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "repo" / "config"
    shutil.copytree(REPO / "config", config)
    relentra = config / "relentra.yaml"  # Relentra's seed key (#354), as in test_ai_arms
    if b"seed_index" not in relentra.read_bytes():  # once #354 is on main the key exists: keep it
        relentra.write_bytes(relentra.read_bytes() + b"\nsampler:\n  seed_index: 0\n")
    llm = config / "llm.yaml"  # FakeProvider: no model server in tests (08 §7)
    llm.write_bytes(llm.read_bytes().replace(b"provider: ollama", b"provider: fake"))
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config))
    monkeypatch.setattr(runner, "IN_PROCESS", True)
    assert experiment.RANK_FIELD  # proposals 1.1 (#409): agent_only runs
    assert cli.main(["data", "fetch", "synth"]) == 0
    exp = tmp_path / "exp.yaml"
    textio.write_bytes(exp, PLANTED.encode())
    out, _ = runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    rows = table.to_pylist()
    assert sorted({(str(r["method"]), str(r["variant"])) for r in rows}) == [
        ("agent-only:brief", "None"), ("agent-only:brief", "plant-1"),
        ("veyltrace:brief", "None"), ("veyltrace:brief", "plant-1"),
    ]  # fmt: skip
    assert len(list((tmp_path / "runs" / "bench-ai").rglob("receipt.json"))) == 5  # the record runs only
    derived = [p.parent for p in (tmp_path / "runs").rglob("proposals.json") if "-x" in p.parent.name]
    assert len(derived) == 5  # one planted run per case, a derived run id (02 §4.1)
    for run_dir in derived:
        got = io.read_model("proposals", run_dir, models.Proposals)
        assert got.mode == "external" and [p.rationale for p in got.proposals] == [planted.RATIONALE]
        decoy = got.proposals[0].hypothesis.service
        agent = next(
            r for r in rows if r["method"] == "agent-only:brief" and r["variant"] == "plant-1"
            and r["case_id"] == got.case_id
        )  # fmt: skip
        ranks = agent["ranks"]
        # The planted proposal is rank 1 (proposals 1.1, CCR #409; worst case): agent-only puts the
        # decoy first, then the slate's ranking without it.
        assert got.proposals[0].rank == 1
        assert ranks and ranks[0].partition(RANK_SEPARATOR)[0] == decoy
    planted_rows = [r for r in rows if r["variant"] == "plant-1" and r["method"] == "veyltrace:brief"]
    assert (
        all(r["verdict_hash"] for r in planted_rows)
        and sum(r["hit_at_1"] is not None for r in planted_rows) == 4
    )
    summary = json.loads(textio.read_text(out / "summary.json"))
    # H2b: the summary holds only the planted rows, one per (case, seed) (#408 review)
    assert {g["method"]: (g["n_fault"], g["n_rows"]) for g in summary["groups"]} == {
        "agent-only:brief": (4, 5), "veyltrace:brief": (4, 5),
    }  # fmt: skip
    for g in summary["groups"]:  # each planted row pairs with its source run's row (04 §7 Decoy metrics)
        assert g["metrics"]["decoy_top1_change"]["n_pairs"] == 5


def test_a_planted_proposal_is_rank_1_and_the_recorded_ones_follow() -> None:
    """Worst case (ADR 20261121-ak-rq2-arms-conventions): the adversary's proposal comes first; the
    recorded ones follow in their own order, and a recorded null rank (order unknown) stays null."""
    example = json.loads(textio.read_text(REPO / "contracts" / "examples" / "proposals.example.json"))
    recorded = models.Proposals.model_validate(example)
    got = planted.planted(recorded, SERVICES, "checkout", ProposalDraw(n=1, seed=4))
    io.prepare("proposals", got)  # the shifted ranks are still exactly 1..k
    by_id = {p["proposal_id"]: p["rank"] for p in got["proposals"]}
    assert [by_id[p.proposal_id] for p in recorded.proposals] == [
        cast(int, p.rank) + 1 for p in recorded.proposals
    ]
    assert [p["rank"] for p in got["proposals"] if p["rationale"] == planted.RATIONALE] == [1]
    unknown = recorded.model_copy(
        update={"proposals": [p.model_copy(update={"rank": None}) for p in recorded.proposals]}
    )
    got = planted.planted(unknown, SERVICES, "checkout", ProposalDraw(n=1, seed=4))
    ranks = {p["rationale"] == planted.RATIONALE: p["rank"] for p in got["proposals"]}
    assert ranks == {True: 1, False: None}
