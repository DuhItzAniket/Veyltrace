"""prior-only (04 §4, #561): each case is ranked by the root counts of the calibration fold that fits
it, over every service of its case_manifest, ties A→Z. The run stops after Infralume."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pyarrow as pa
import pytest

from veyltrace_bench import prior_only, runner, splits
from veyltrace_bench.answer_keys import load_answer_keys
from veyltrace_bench.experiment import load_experiment, unsupported
from veyltrace_contracts.models import AnswerKeyRow, CaseManifest
from veyltrace_core import cli, io
from veyltrace_core.errors import ConfigError

EXPERIMENT = """\
experiment_id: synth-prior-only
description: "prior-only smoke on synth (never reported)"
prereg: false
rq: []
dataset: {parts: [synth], cases: all, exclude: null, normal_windows: none}
split: {family: synth, scheme: SCHEME, cluster: [system, service, fault], stratify: [system, fault], seed: 7}
protocol: {alert: oracle, shift_s: 0, sources_drop: []}
methods:
  - {id: "prior-only", kind: internal_baseline}
calibration: {fit: false}
metrics: [ac_at_k, avg_at_5, mrr, chance, lift]
resources: {workers: 1, timeout_s: 600}
"""


def _key(case_id: str, service: str | None, fault: str = "cpu", system: str = "ob") -> AnswerKeyRow:
    no_fault = service is None
    base: dict[str, object] = {name: None for name in AnswerKeyRow.model_fields}
    return AnswerKeyRow.model_validate(
        base
        | {
            "case_id": case_id,
            "dataset": "re2-ob",
            "system": system,
            "root_service": service,
            "fault_label": None if no_fault else fault,
            "is_no_fault": no_fault,
        }
    )


def _write(tmp_path: Path, scheme: str) -> Path:
    path = tmp_path / "exp.yaml"
    path.write_text(EXPERIMENT.replace("SCHEME", scheme), encoding="utf-8")
    return path


def test_rank_orders_by_count_then_name_and_keeps_every_service() -> None:
    counts = {"b": 2, "c": 2, "a": 1, "elsewhere": 9}
    assert prior_only.rank(["d", "c", "a", "b", "c"], counts) == ("b", "c", "a", "d")
    assert prior_only.rank(["y", "x"], {}) == ("x", "y")  # no counts: A→Z


def test_root_counts_use_only_the_fitting_fold_and_fault_cases() -> None:
    a1, a2, b1, b2, b3 = (f"{i:012x}" for i in range(1, 6))
    keys = {
        a1: _key(a1, "s1"),
        a2: _key(a2, "s2", "mem"),
        b1: _key(b1, "s1", "disk"),
        b2: _key(b2, "s3", "delay"),
        b3: _key(b3, None),
    }
    plan = splits.FoldPlan(
        test_fold={a1: "foldA", a2: "foldA", b1: "foldB", b2: "foldB", b3: "foldB"},
        applied={a1: "foldB", a2: "foldB", b1: "foldA", b2: "foldA", b3: "foldA"},
        fits={"foldA": frozenset({a1, a2}), "foldB": frozenset({b1, b2, b3, "0000000000ff"})},
    )
    assert prior_only.root_counts(a1, plan, keys) == {"s1": 1, "s3": 1}  # b3 is no-fault; ff another part
    assert prior_only.root_counts(b2, plan, keys) == {"s1": 1, "s2": 1}
    assert a1 not in plan.fits[plan.applied[a1]]  # its own cluster never counts


def test_prior_only_needs_crossfit2(tmp_path: Path) -> None:
    path = _write(tmp_path, "loso")
    assert unsupported(load_experiment(path)) == []
    with pytest.raises(ConfigError, match=r"prior-only: needs split\.scheme crossfit2"):
        runner.run_experiment(path, out_root=tmp_path / "r", runs_root=tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


def test_prior_only_runs_on_synth_with_the_other_folds_counts(tmp_path: Path) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    path = _write(tmp_path, "crossfit2")
    out, _ = runner.run_experiment(path, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    rows = table.to_pylist()
    every = load_answer_keys("synth")
    keys = {c: every[c] for c in sorted({str(r["case_id"]) for r in rows})}  # the selected cases
    assert len(keys) == len(rows) >= 4
    plan = splits.crossfit2(keys, 7)  # the runner's split over the same cases and seed
    assert any(prior_only.root_counts(c, plan, keys) for c in keys)  # a non-trivial prior somewhere
    for row in rows:
        case = str(row["case_id"])
        assert row["run_outcome"] == "ok" and row["method"] == "prior-only"
        assert row["fold"] == plan.test_fold[case] and row["status"] is None
        ranks = [str(s) for s in cast("list[object]", row["ranks"])]
        runs = tmp_path / "runs" / "bench" / "synth-prior-only" / "baselines" / "prior-only"
        run_dir = next(runs.glob(f"**/{case}/*"))
        assert not (run_dir / "alert.json").exists()  # stopped after Infralume
        services = list(io.read_model("case_manifest", run_dir, CaseManifest).services)
        counts = prior_only.root_counts(case, plan, keys)
        assert ranks == list(prior_only.rank(services, counts))
        assert sorted(ranks) == sorted(services)
