"""bench_manifest.calibrations (03 §13.4; CCR #404, #412): the calibration files the recorded runs
read, from their config.lock.json, with `fitted` for the files the experiment wrote itself."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from veyltrace_bench.experiment import Experiment
from veyltrace_bench.manifest_calibrations import recorded
from veyltrace_core import textio
from veyltrace_core.canonical import canonical_json
from veyltrace_core.pipeline import run_dir_for

EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples"
DATASET = "re2-ob"
OWN = "veyllab.brief.oracle.foldA"  # the calibration example's family, fitted by rq3-coverage-veyllab
OTHER = "rcaeval-re2.off.oracle.foldB"


def _experiment(*, fit: bool) -> Experiment:
    return Experiment.model_validate(
        {
            "experiment_id": "rq3-coverage-veyllab",
            "description": "x",
            "dataset": {"parts": [DATASET]},
            "methods": [{"id": "veyltrace:off", "kind": "veyltrace"}],
            "metrics": ["coverage"],
            "calibration": {"fit": fit},
        }
    )


def _file(family: str, experiment_id: str, sha256: str) -> dict[str, Any]:
    content = json.loads(textio.read_text(EXAMPLES / "calibration.example.json"))
    return {
        "family_id": family,
        "sha256": sha256,
        "content": content | {"family": family, "experiment_id": experiment_id},
    }


def _run(
    root: Path, case: str, run_id: str | None, calibration: dict[str, Any] | None = None
) -> dict[str, object]:
    """A manifest runs[] entry; with a calibration (or None for an uncalibrated run) its lock is written."""
    if run_id is not None and calibration != {}:
        lock = json.loads(textio.read_text(EXAMPLES / "config_lock.example.json")) | {
            "calibration": calibration
        }
        textio.write_bytes(
            run_dir_for(root, DATASET, case, run_id) / "config.lock.json", canonical_json(lock) + b"\n"
        )
    return {
        "case_id": case,
        "dataset": DATASET,
        "method": "veyltrace:off",
        "run_id": run_id,
        "inputs_sha256": None,
    }


def test_the_files_the_runs_read_sorted_with_the_experiments_own_fitted(tmp_path: Path) -> None:
    own, other = _file(OWN, "rq3-coverage-veyllab", "a" * 64), _file(OTHER, "rcaeval-calibration", "b" * 64)
    runs = [
        _run(tmp_path, "c1", "r1", own),
        _run(tmp_path, "c2", "r2", other),
        _run(tmp_path, "c3", "r3", None),  # uncalibrated: its lock names no file
        _run(tmp_path, "c4", "r4", own),  # the same file read again: listed once
        _run(tmp_path, "c5", None),  # killed at the timeout: no run directory
        _run(tmp_path, "c6", "r6", {}),  # no lock (a baseline's partial run elsewhere, or stopped early)
    ]
    got = recorded(_experiment(fit=True), runs, tmp_path)
    assert got == [
        {"family_id": OTHER, "sha256": "b" * 64, "fitted": False},  # read, fitted by another experiment
        {"family_id": OWN, "sha256": "a" * 64, "fitted": True},
    ]
    assert [c["fitted"] for c in recorded(_experiment(fit=False), runs, tmp_path)] == [False, False]
    assert recorded(_experiment(fit=True), runs[2:3], tmp_path) == []
