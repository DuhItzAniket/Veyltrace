"""Causentra with a calibration file (09 §3.7–§3.9, §3.15): the conformal set and NO_FAULT threshold.

Fitting is bench's (R-13), so the file is hand-made: `fixtures/handmade/calibration.<family>.json`
holds q̂ = 0.8 and a calibrated τ_nf = log1p(1). On the committed synth fixtures, synth-01's
runner-up has s = 0.781312317 ≤ q̂ (the set grows from 1 to 2) and synth-05's statistic is
M = 0.802466891 > τ_nf (no longer NO_FAULT), so each value visibly decides something.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from veyltrace_causentra import api
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.calibration import UNCALIBRATED, write_calibration
from veyltrace_core.context import EngineResult
from veyltrace_core.testing import fixture_run_dir, make_context, repo_root

FAMILY = "synth.off.oracle.foldA"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "handmade" / f"calibration.{FAMILY}.json"
THROUGH = "faultloom.claim_pass"


def _fixture(**changes: Any) -> dict[str, Any]:
    content: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    no_fault = content["no_fault"] | changes.pop("no_fault", {})
    return content | changes | {"no_fault": no_fault}


def _run(case: str, tmp_path: Path, content: dict[str, Any] | None) -> tuple[EngineResult, Path]:
    config_dir = tmp_path / "config"
    shutil.copytree(repo_root() / "config", config_dir)
    if content is not None:
        write_calibration(config_dir / "calibration", content)
    run_dir = fixture_run_dir(case, tmp_path / "run", through=THROUGH)
    ctx = make_context("causentra", run_dir, config_dir=config_dir)
    assert (ctx.config.calibration is None) == (content is None)
    return api.run(ctx), run_dir


def _verdict(run_dir: Path) -> models.Verdict:
    return io.read_model("verdict", run_dir, models.Verdict, validate=True)


def test_the_fixture_is_a_valid_canonical_calibration_file(tmp_path: Path) -> None:
    written = write_calibration(tmp_path, _fixture())
    assert written.read_bytes() == FIXTURE.read_bytes()  # canonical bytes, as bench writes them


def test_calibrated_q_hat_widens_the_set(tmp_path: Path) -> None:
    result, run_dir = _run("synth-01", tmp_path, _fixture())
    assert result.status == "ok", result.notes
    v = _verdict(run_dir)
    assert (v.calibration.family, v.confidence.q_hat, v.confidence.alpha) == (FAMILY, 0.8, 0.1)
    assert [c.service for c in v.candidate_set] == ["checkout", "frontend"]  # s = 0 and 0.781312317
    # |C| = 2 rules out CONFIRMED; mandatory trials pass and the margin 0.78 >= c_med: LIKELY (09 §3.9).
    assert (v.status, v.confidence.level, v.confidence.set_size) == ("LIKELY", "medium", 2)
    assert v.root is not None and v.root.service == "checkout"
    _, run_dir = _run("synth-01", tmp_path / "u", None)
    u = _verdict(run_dir)
    assert (u.calibration.family, u.confidence.q_hat, u.status) == (UNCALIBRATED, 0.0, "CONFIRMED")
    assert [r.v for r in u.ranked] == [r.v for r in v.ranked]  # calibration moves the set, never V


def test_calibrated_tau_decides_no_fault(tmp_path: Path) -> None:
    _, run_dir = _run("synth-05", tmp_path / "default", None)
    assert _verdict(run_dir).status == "NO_FAULT"  # M = 0.802 <= log1p(3)
    _, run_dir = _run("synth-05", tmp_path / "calibrated", _fixture())
    flagged = _verdict(run_dir)
    assert flagged.status != "NO_FAULT" and flagged.candidate_set  # M = 0.802 > tau_nf = 0.693
    _, run_dir = _run("synth-05", tmp_path / "unfitted", _fixture(no_fault={"calibrated": False}))
    assert _verdict(run_dir).status == "NO_FAULT"  # m < 9: tau_nf not fitted, default_tau applies


def test_a_file_fitted_at_another_beta_fails_the_step(tmp_path: Path) -> None:
    result, run_dir = _run("synth-01", tmp_path, _fixture(no_fault={"beta": 0.2}))
    assert result.status == "failed" and result.outputs == ()
    assert any("no_fault.beta=0.2" in note for note in result.notes)
    assert not io.exists("verdict", run_dir)
