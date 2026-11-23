"""`veyltrace replay` (10 §3.9): every exit code on real synth runs, AI off and with a recording."""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from veyltrace_causivra.replay import main, replay
from veyltrace_core.canonical import canonical_json
from veyltrace_core.errors import CassetteMiss, ReplayExit, StepFailed
from veyltrace_core.ids import AIMode, case_id
from veyltrace_core.pipeline import env_info, run_case
from veyltrace_core.testing import FIXTURE_CODE_COMMIT, repo_root

CONFIG = repo_root() / "config"


def _run(root: Path, ai_mode: Any, overrides: dict[str, Any]) -> Path:
    summary = run_case(
        "synth", case_id("synth-01"), ai_mode, overrides,
        runs_root=root, config_dir=CONFIG, code_commit=FIXTURE_CODE_COMMIT,
    )  # fmt: skip
    assert summary.outcome == "ok", (summary.failed_step, summary.reason)
    return summary.run_dir


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("replay") / "runs"
    return {"off": _run(root, "off", {}), "record": _run(root, "record", {"llm.provider": "fake"})}


@pytest.fixture
def copy(runs: dict[str, Path], tmp_path: Path) -> Path:
    """A run dir the test may damage."""
    target = tmp_path / "run"
    shutil.copytree(runs["off"], target)
    return target


def _edit_receipt(run_dir: Path, **predicate: Any) -> None:
    path = run_dir / "receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["predicate"].update(predicate)
    path.write_bytes(canonical_json(receipt) + b"\n")


@pytest.mark.parametrize("mode", ["off", "record"])
def test_a_fresh_run_replays(runs: dict[str, Path], mode: str) -> None:
    report = replay(runs[mode] / "receipt.json")
    assert report.exit_code == ReplayExit.OK, report.as_json()
    assert report.hashes["verdict_hash"]["expected"] == report.hashes["verdict_hash"]["actual"]
    if mode == "record":  # the recorded failed brief call replays from the cassette
        assert report.hashes["agent_trace_head"]["actual"] is not None


def test_main_prints_the_report_and_returns_the_exit_code(
    runs: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "report.json"
    assert main([str(runs["off"] / "receipt.json"), "--report", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == json.loads(out.read_text(encoding="utf-8")) and printed["exit_code"] == 0
    assert {c["id"] for c in printed["checks"]} >= {"R1", "R3", "R4", "R5", "R6", "R7", "R8"}
    assert main([str(runs["off"] / "receipt.json"), "--full"]) == ReplayExit.ERROR


def test_a_malformed_receipt_is_exit_1(copy: Path) -> None:
    (copy / "receipt.json").write_text("{}", encoding="utf-8")
    assert replay(copy / "receipt.json").exit_code == ReplayExit.ERROR


@pytest.mark.parametrize("name", ["alert.json", "verdict.json"])  # a step 0-4 output; the subject
def test_a_changed_file_is_exit_3(copy: Path, name: str) -> None:
    (copy / name).write_bytes((copy / name).read_bytes() + b" ")
    report = replay(copy / "receipt.json")
    assert report.exit_code == ReplayExit.INPUTS_CHANGED and name in report.checks[-1]["detail"]


def test_a_changed_config_lock_is_exit_4(copy: Path) -> None:
    lock = copy / "config.lock.json"
    lock.write_bytes(lock.read_bytes().replace(b'"k_default":6', b'"k_default":5'))
    assert replay(copy / "receipt.json").exit_code == ReplayExit.CONFIG


def test_environment_drift_is_exit_5_unless_allowed(copy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = env_info()
    monkeypatch.setattr("veyltrace_causivra.replay.env_info", lambda: {**real, "python": "9.99.0"})
    report = replay(copy / "receipt.json")
    assert report.exit_code == ReplayExit.ENV_DRIFT and report.env_drift[0].startswith("python")
    assert replay(copy / "receipt.json", allow_env_drift=True).exit_code == ReplayExit.OK


def test_a_different_verdict_hash_is_exit_2(copy: Path) -> None:
    _edit_receipt(copy, verdict_hash="0" * 64)
    report = replay(copy / "receipt.json")
    got = report.hashes["verdict_hash"]
    assert report.exit_code == ReplayExit.HASH_MISMATCH and got["expected"] == "0" * 64 != got["actual"]


def test_a_card_only_difference_is_exit_6(copy: Path) -> None:
    _edit_receipt(copy, card_hash="0" * 64)
    assert replay(copy / "receipt.json").exit_code == ReplayExit.NARRATIVE_MISMATCH


def test_a_missing_recording_is_exit_3(runs: dict[str, Path], tmp_path: Path) -> None:
    target = tmp_path / "run"
    shutil.copytree(runs["record"], target)
    shutil.rmtree(target / "cassette")
    assert replay(target / "receipt.json").exit_code == ReplayExit.INPUTS_CHANGED


@pytest.mark.parametrize(("drift", "allow", "code"), [(False, False, 2), (True, False, 5), (True, True, 2)])
def test_a_cassette_miss_in_the_rerun_is_exit_2_after_drift(
    runs: dict[str, Path], monkeypatch: Any, drift: bool, allow: bool, code: int
) -> None:
    real = env_info()
    if drift:  # R9: unallowed drift (5) outranks a cassette miss (2), review of #434
        monkeypatch.setattr("veyltrace_causivra.replay.env_info", lambda: {**real, "python": "9.99.0"})

    def miss(*args: Any, **kwargs: Any) -> Any:  # the step error comes back wrapped, as run_case does
        error = StepFailed("relentra", CassetteMiss("a request the recording never saw"))
        return dataclasses.replace(
            run_case(*args, **kwargs), outcome="failed", failed_step="relentra", error=error
        )

    monkeypatch.setattr("veyltrace_causivra.replay.run_case", miss)
    assert replay(runs["record"] / "receipt.json", allow_env_drift=allow).exit_code == code


def _config_before_narration(tmp_path: Path) -> Path:
    """config/ as locked at results-code-v1: causivra.yaml without the checker and narration keys."""
    target = tmp_path / "config"
    shutil.copytree(CONFIG, target)
    path = target / "causivra.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: text.index("\n# Claim checker")] + "\n", encoding="utf-8")
    return target


@pytest.mark.parametrize("mode", ["off", "record"])
def test_a_receipt_locked_before_narration_replays(tmp_path: Path, mode: AIMode) -> None:
    """#467 review: main must replay results-code-v1 receipts, whose config.lock has no narration."""
    summary = run_case(
        "synth", case_id("synth-01"), mode, {"llm.provider": "fake"} if mode == "record" else {},
        runs_root=tmp_path / "runs", config_dir=_config_before_narration(tmp_path),
        code_commit=FIXTURE_CODE_COMMIT,
    )  # fmt: skip
    assert summary.outcome == "ok", (summary.failed_step, summary.reason)
    assert '"narration"' not in (summary.run_dir / "config.lock.json").read_text(encoding="utf-8")
    report = replay(summary.run_dir / "receipt.json")
    assert report.exit_code == ReplayExit.OK, report.as_json()


def test_a_fake_ai_run_reports_narration_in_run_manifest_ai(runs: dict[str, Path]) -> None:
    """#467 review: the card step's AIManifest reaches run_manifest.ai through the full pipeline."""
    ai = json.loads((runs["record"] / "run_manifest.json").read_text(encoding="utf-8"))["ai"]
    assert ai["provider"] == "fake" and ai["model"] is not None
    assert ai["prompt_sha256"] is not None and ai["schema_sha256"] is not None
    assert (runs["record"] / "cassette" / "narration" / "index.json").is_file()
