"""agent-only:brief (04 §4; #398): the brief run's proposals as the ranking, no run of its own."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pyarrow as pa
import pytest

from veyltrace_bench import agent_only, experiment, runner
from veyltrace_bench.experiment import load_experiment, unsupported
from veyltrace_bench.runner import slate_ranks
from veyltrace_contracts import models
from veyltrace_core import cli, io, testing, textio
from veyltrace_core.config import CONFIG_DIR_ENV
from veyltrace_core.errors import ConfigError

REPO = Path(__file__).resolve().parents[2]
ARM = "ai: {mode: record, relentra_mode: brief, model: qwen3.5-9b-q4_k_m, seeds: [1]}"
BOTH = f"""\
experiment_id: synth-agent-only
description: "agent-only on synth (never reported)"
dataset: {{parts: [synth], cases: all, exclude: null, normal_windows: none}}
protocol: {{alert: oracle, shift_s: 0, sources_drop: []}}
methods:
  - {{id: "veyltrace:brief", kind: veyltrace, {ARM}}}
  - {{id: "agent-only:brief", kind: agent_only, {ARM}}}
metrics: [ac_at_k, cost]
"""


def test_proposals_lead_in_rank_order_and_a_null_rank_is_unranked() -> None:
    """The model's order (proposals[].rank, CCR #409), not the file's A-Z order; unknown order is
    unranked. Until #409 lands the models have no rank, so a stand-in carries it here."""
    slate = testing.golden("slate", "synth-01")
    assert isinstance(slate, models.Slate)
    example = json.loads(textio.read_text(REPO / "contracts" / "examples" / "proposals.example.json"))
    proposals = models.Proposals.model_validate(example)
    ranking = slate_ranks(slate)
    assert agent_only.ranks(proposals, ranking, slate) is None  # 1.0 file: no rank, order unknown
    first, second = proposals.proposals[0], proposals.proposals[1]  # file order: A-Z by service
    stand_in = SimpleNamespace(
        case_id=proposals.case_id,
        proposals=[
            SimpleNamespace(hypothesis=first.hypothesis, rank=2),
            SimpleNamespace(hypothesis=second.hypothesis, rank=1),
        ],
    )
    got = agent_only.ranks(cast("models.Proposals", stand_in), ranking, slate)
    assert got is not None
    heads = [second.hypothesis.service, first.hypothesis.service]  # rank 1 first
    assert [r.split("_")[0] for r in got[:2]] == heads
    assert got[2:] == tuple(r for r in ranking if r.split("_")[0] not in heads)
    assert agent_only.ranks(None, ranking, slate) == ranking  # no proposals: the slate's ranking


BRIEF_LINE = f'  - {{id: "veyltrace:brief", kind: veyltrace, {ARM}}}\n'
AGENT_LINE = f'  - {{id: "agent-only:brief", kind: agent_only, {ARM}}}\n'


@pytest.mark.parametrize(
    "text",
    [
        BOTH.replace(AGENT_LINE, AGENT_LINE.replace("seeds: [1]", "seeds: [2]")),  # another ai block
        BOTH.replace(BRIEF_LINE + AGENT_LINE, AGENT_LINE + BRIEF_LINE),  # listed after it
    ],
)
def test_an_agent_only_method_needs_its_source_before_it(tmp_path: Path, text: str) -> None:
    path = tmp_path / "exp.yaml"
    textio.write_bytes(path, text.encode())
    exp = load_experiment(path)
    agent = next(m for m in exp.methods if m.kind == "agent_only")
    with pytest.raises(ConfigError, match="none precedes it"):
        agent_only.source_of(exp, agent)


def test_agent_only_is_refused_until_proposals_carry_a_rank(tmp_path: Path) -> None:
    """Without proposals[].rank every case would be a silent miss (#407 review, CCR #409)."""
    path = tmp_path / "exp.yaml"
    textio.write_bytes(path, BOTH.encode())
    todo = unsupported(load_experiment(path))
    if experiment.RANK_FIELD:
        assert not any("agent_only" in t for t in todo)
    else:
        assert "methods agent-only:brief: kind agent_only needs proposals 1.1 rank (#409)" in todo


def test_agent_only_rows_score_the_brief_runs_without_runs_of_their_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    config = tmp_path / "repo" / "config"
    shutil.copytree(REPO / "config", config)
    relentra = config / "relentra.yaml"  # Relentra's seed key (#354), as in test_ai_arms
    if b"seed_index" not in relentra.read_bytes():  # once #354 is on main the key exists: keep it
        relentra.write_bytes(relentra.read_bytes() + b"\nsampler:\n  seed_index: 0\n")
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config))
    monkeypatch.setattr(runner, "IN_PROCESS", True)
    monkeypatch.setattr(experiment, "RANK_FIELD", True)  # as once proposals 1.1 (#409) lands
    assert cli.main(["data", "fetch", "synth"]) == 0
    exp = tmp_path / "exp.yaml"
    textio.write_bytes(exp, BOTH.encode())
    caplog.set_level("INFO")
    out, _ = runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    rows = table.to_pylist()
    brief = {str(r["case_id"]): r for r in rows if r["method"] == "veyltrace:brief"}
    agent = {str(r["case_id"]): r for r in rows if r["method"] == "agent-only:brief"}
    assert sorted(agent) == sorted(brief) and len(agent) == 5
    for case, row in agent.items():
        assert (row["seed"], row["ai_mode"], row["status"], row["verdict_hash"]) == (1, "record", None, None)
        shared = (brief[case]["wall_ms"], brief[case]["tokens_in"])
        assert (row["wall_ms"], row["tokens_in"]) == shared  # the source's run and cost
    # The stub proposes nothing: agent-only ranks by the slate (04 §4), and the rows are counted.
    assert [r.getMessage() for r in caplog.records].count("bench.agent_only_slate_fallback") == 1
    kept = list((tmp_path / "runs" / "bench-ai").rglob("receipt.json"))

    assert len(kept) == 5  # one record run per case: agent_only made none
    runs = json.loads(textio.read_text(out / "manifest.json"))["runs"]
    assert {r["run_id"] for r in runs if r["method"] == "agent-only:brief"} == {
        r["run_id"] for r in runs if r["method"] == "veyltrace:brief"
    }
