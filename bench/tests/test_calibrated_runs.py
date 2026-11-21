"""The runner under a calibration split (04 §5.4; #391, #376): fit, held-out restarts, reuse.

Each test works on a copy of config/ (VEYLTRACE_CONFIG_DIR), so calibration files are written
under tmp_path and never into the repository's config/calibration/.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from veyltrace_bench import answer_keys, calibration, runner, splits
from veyltrace_contracts import models
from veyltrace_core import cli, io, textio
from veyltrace_core.calibration import load_calibration, write_calibration
from veyltrace_core.config import CONFIG_DIR_ENV
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_file

REPO = Path(__file__).resolve().parents[2]
FILE: dict[str, Any] = {
    "family": "synth", "ai_arm": "off", "alert_protocol": "oracle", "alpha": 0.1, "beta": 0.1,
    "default_tau": 1.386294361, "seed": 1, "config_sha256s": ["a" * 64], "code_commit": "x",
    "experiment_id": "synth-fit",
}  # fmt: skip
FIT = """\
experiment_id: synth-crossfit
description: "crossfit2 on synth (never reported)"
dataset: {parts: [synth], cases: all, exclude: null, normal_windows: none}
split: {family: synth, scheme: crossfit2, seed: 20261108}
protocol: {alert: oracle, shift_s: 0, sources_drop: []}
methods:
  - {id: "veyltrace:off", kind: veyltrace, ai: {mode: "off"}, overrides: {}}
  - {id: "causatrix:rrf", kind: causatrix, ai: {mode: "off"}, overrides: {}}
calibration: {fit: FIT, alpha: 0.10, no_fault_beta: 0.10}
metrics: [ac_at_k]
resources: {workers: 1, timeout_s: 600}
"""


@pytest.fixture
def config_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of config/ under tmp_path/repo, the runner's repo root (out dirs stay outside it)."""
    shutil.copytree(REPO / "config", tmp_path / "repo" / "config")
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path / "repo" / "config"))
    assert cli.main(["data", "fetch", "synth"]) == 0
    return tmp_path / "repo" / "config"


def _yaml(tmp_path: Path, text: str, name: str) -> Path:
    path = tmp_path / f"{name}.yaml"
    textio.write_bytes(path, text.encode())
    return path


def _rows(out: Path) -> list[dict[str, object]]:
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    return table.to_pylist()


def _off_runs(out: Path) -> int:
    runs = json.loads(textio.read_text(out / "manifest.json"))["runs"]
    return sum(r["method"] == "veyltrace:off" for r in runs)


def test_crossfit2_fits_both_folds_and_tests_each_case_on_the_other(
    tmp_path: Path, config_root: Path
) -> None:
    exp = _yaml(tmp_path, FIT.replace("FIT", "true"), "fit")
    out, _ = runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    rows = _rows(out)
    off = {str(r["case_id"]): r for r in rows if r["method"] == "veyltrace:off"}
    keys = {c: k for c, k in answer_keys.load_answer_keys("synth").items() if c in off}  # the 5 listed
    plan = splits.crossfit2(keys, 20261108)
    files = {
        f: load_calibration(config_root / "calibration" / f"synth.off.oracle.{f}.json") for f in splits.FOLDS
    }
    for fold, ref in files.items():  # each file is fitted on its own fold's cases only
        faults = [c for c in plan.fits[fold] if not keys[c].is_no_fault]
        assert (ref.content.n, ref.content.split.fold, ref.content.experiment_id) == (
            len(faults),
            fold,
            "synth-crossfit",
        )
        windows = [c for c in plan.fits[fold] if keys[c].is_no_fault]
        assert ref.content.no_fault.m == len(windows) and not ref.content.no_fault.calibrated  # m < 9
        assert ref.content.no_fault.sources == (["synth-05"] if windows else [])
    assert {c: r["fold"] for c, r in off.items()} == dict(plan.test_fold)  # one held-out row per case
    assert all(r["fold"] == plan.test_fold[str(r["case_id"])] for r in rows)  # rrf rows too
    assert _off_runs(out) == 2 * len(keys)  # calibration runs + held-out runs
    for run_dir in (tmp_path / "runs").rglob("run_manifest.json"):
        got = io.read_model("run_manifest", run_dir.parent, models.RunManifest)
        verdict = io.read_model("verdict", run_dir.parent, models.Verdict)
        if verdict.calibration.family == "uncalibrated":
            continue  # a calibration run (also the run causatrix:rrf shares)
        applied = plan.applied[got.case_id]
        assert verdict.calibration.family == f"synth.off.oracle.{applied}"
        assert got.calibration_sha256 == sha256_file(
            config_root / "calibration" / f"synth.off.oracle.{applied}.json"
        )
    rates = {str(r["fold"]): r for r in calibration.held_out_rates(off.values())}
    assert sorted(rates) == ["foldA", "foldB", "pooled"] and rates["pooled"]["n_fault"] == 4  # #37's check
    assert rates["pooled"]["coverage"] == 1.0  # q_hat is +inf at n < 9: every set is the whole pool

    again = _yaml(tmp_path, FIT.replace("FIT", "false").replace("synth-crossfit", "synth-reuse"), "reuse")
    out2, _ = runner.run_experiment(again, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    reused = {str(r["case_id"]): r for r in _rows(out2) if r["method"] == "veyltrace:off"}
    assert [(r["fold"], r["status"], r["verdict_hash"]) for r in reused.values()] == [
        (off[c]["fold"], off[c]["status"], off[c]["verdict_hash"]) for c in reused
    ]  # the same file applied in one run: the same held-out verdicts
    assert _off_runs(out2) == len(keys)


def _write_fold_files(config_root: Path) -> None:
    """foldA keeps only the leader (q_hat 0), foldB the whole pool (q_hat +inf, n < 9)."""
    for fold, q in (("foldA", 0.0), ("foldB", None)):
        scores = [] if q is None else [q] * 9
        runs = [calibration.CalibrationRun(f"{i:012x}", None, score=s) for i, s in enumerate(scores)]
        write_calibration(config_root / "calibration", calibration.fit(runs, **{**FILE, "fold": fold}))


def test_fit_false_tests_each_case_with_the_file_fitted_without_it(tmp_path: Path, config_root: Path) -> None:
    _write_fold_files(config_root)
    exp = _yaml(tmp_path, FIT.replace("FIT", "false"), "reuse")
    out, _ = runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    rows = _rows(out)
    off = {str(r["case_id"]): r for r in rows if r["method"] == "veyltrace:off"}
    keys = {c: k for c, k in answer_keys.load_answer_keys("synth").items() if c in off}  # the 5 listed
    plan = splits.crossfit2(keys, 20261108)
    assert {c: r["fold"] for c, r in off.items()} == dict(plan.test_fold)  # one held-out row per case
    assert all(r["fold"] == plan.test_fold[str(r["case_id"])] for r in rows)  # rrf rows too
    assert _off_runs(out) == len(keys)  # one run per case: nothing is fitted
    for path in (tmp_path / "runs").rglob("run_manifest.json"):
        got = io.read_model("run_manifest", path.parent, models.RunManifest)
        verdict = io.read_model("verdict", path.parent, models.Verdict)
        family = f"synth.off.oracle.{plan.applied[got.case_id]}"  # rrf shares these runs (#172)
        assert verdict.calibration.family == family
        assert got.calibration_sha256 == sha256_file(config_root / "calibration" / f"{family}.json")
        if verdict.status != "NO_FAULT":  # the file's q_hat decided the set (09 §3.7)
            q_hat = 0.0 if plan.applied[got.case_id] == "foldA" else math.inf
            want = sorted(r.service for r in verdict.ranked if r.nonconformity <= q_hat)
            assert sorted(c.service for c in verdict.candidate_set) == want
    rates = {str(r["fold"]): r for r in calibration.held_out_rates(off.values())}
    assert sorted(rates) == ["foldA", "foldB", "pooled"] and rates["pooled"]["n_fault"] == 4  # #37's check


def test_fit_false_without_the_files_fails_before_any_run(tmp_path: Path, config_root: Path) -> None:
    exp = _yaml(tmp_path, FIT.replace("FIT", "false"), "nofile")
    with pytest.raises(ConfigError, match=r"no \['synth.off.oracle.foldA', 'synth.off.oracle.foldB'\]"):
        runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (
            (
                'overrides: {}}\n  - {id: "causatrix',
                'overrides: {causentra.alpha: 0.2}}\n  - {id: "causatrix',
            ),
            "alpha",
        ),
        (("scheme: crossfit2", "scheme: loso"), "two systems"),
        (("overrides: {}", "overrides: {causentra.calibration.fold: foldB}"), "bench sets them"),
    ],
)
def test_bad_calibration_setups_fail_before_any_run(
    tmp_path: Path, config_root: Path, change: tuple[str, str], match: str
) -> None:
    exp = _yaml(tmp_path, FIT.replace("FIT", "false").replace(*change, 1), "bad")
    with pytest.raises(ConfigError, match=match):
        runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")


def test_split_none_runs_stay_uncalibrated_whatever_files_exist(
    tmp_path: Path, config_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stray file named like the default fold must not calibrate a scheme-none run (#376)."""
    _write_fold_files(config_root)
    monkeypatch.setattr(runner, "IN_PROCESS", True)
    smoke = REPO / "bench" / "experiments" / "synth-smoke.yaml"
    runner.run_experiment(smoke, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    families = {
        io.read_model("verdict", p.parent, models.Verdict).calibration.family
        for p in (tmp_path / "runs").rglob("verdict.json")
    }
    assert families == {"uncalibrated"}
