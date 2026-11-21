"""The 04 §9 keys and metric ids added by the lead's prereg-v1 decisions (#314)."""

from __future__ import annotations

from pathlib import Path

import pytest

from veyltrace_bench.experiment import (
    METRIC_TASKS,
    Experiment,
    ProposalDraw,
    load_experiment,
    unsupported,
)
from veyltrace_bench.summary import METRIC_KEYS, summarize
from veyltrace_core.errors import ConfigError

BASE = (
    'experiment_id: t-1\ndescription: "x"\ndataset: {parts: [synth]}\n'
    'methods: [{id: "veyltrace:off", kind: veyltrace}]\n'
)


def _load(tmp_path: Path, text: str) -> Experiment:
    path = tmp_path / "exp.yaml"
    path.write_text(text, encoding="utf-8", newline="\n")
    return load_experiment(path)


def test_transfer_split_names_the_family_it_calibrates_from(tmp_path: Path) -> None:
    exp = _load(tmp_path, BASE + "metrics: [mrr]\nsplit: {scheme: transfer, calibrate_from: rcaeval-re2}\n")
    assert (exp.split.scheme, exp.split.calibrate_from) == ("transfer", "rcaeval-re2")
    assert not any("split" in todo for todo in unsupported(exp))  # runs since #391 (splits.check_split)
    for split in ("{scheme: transfer}", "{scheme: crossfit2, calibrate_from: rcaeval-re2}"):
        with pytest.raises(ConfigError, match="calibrate_from"):
            _load(tmp_path, BASE + f"metrics: [mrr]\nsplit: {split}\n")


def test_proposal_perturbations_are_seeded_draws(tmp_path: Path) -> None:
    exp = _load(tmp_path, BASE + "metrics: [mrr]\nprotocol: {inject_proposals: {n: 1, seed: 4}}\n")
    assert exp.protocol.inject_proposals == ProposalDraw(n=1, seed=4)
    assert "protocol AI perturbations" in unsupported(exp)
    for bad in ("{n: 1}", "{n: 0, seed: 4}", "{n: 1, seed: 4, kind: x}"):
        with pytest.raises(ConfigError, match="inject_proposals"):
            _load(tmp_path, BASE + f"metrics: [mrr]\nprotocol: {{inject_proposals: {bad}}}\n")


def test_new_metric_ids_are_tasks_and_cost_is_computed(tmp_path: Path) -> None:
    ids = ["selective_accuracy", "decoy_top1_change", "permutation_invariance"]
    exp = _load(tmp_path, BASE + f"metrics: [mrr, cost, {', '.join(ids)}]\n")
    todo = " | ".join(unsupported(exp))
    assert all(f"metrics {m} ({METRIC_TASKS[m]})" in todo for m in ids)
    assert "cost" not in todo and "cost" in METRIC_KEYS and "cost" not in METRIC_TASKS  # #316
    assert "decoy_ranked_first" in METRIC_KEYS and "decoy_ranked_first" not in METRIC_TASKS  # #357
    assert set(summarize([], ["mrr", "cost"])) >= {"mrr", "n_cost", "wall_ms_p95"}
