"""#225 items 1-3: the reset really waits, one failing case never ends the night, probes don't raise."""

import http.client
import json
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

import campaign
import pytest
from vlab import validate
from vlab.cluster import deployments, load_pins
from vlab.plan import parse
from vlab.shell import Runner

PLAN = parse({"profile": "ob", "seed": 1, "entries": [{"fault": "F01", "target": "frontend"}]})


class InstantRunner(Runner):
    def sleep(self, seconds: float, reason: str) -> None:
        self.log.append(f"sleep {seconds:g}  # {reason}")

    def http_ok(self, url: str, timeout_s: float = 10.0) -> bool:
        return True


def _cluster(monkeypatch: pytest.MonkeyPatch, fail_when: str | None = None) -> None:
    """A fake cluster: every command succeeds, except the first one containing ``fail_when``."""
    state = {"failed": False}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if fail_when and not state["failed"] and fail_when in " ".join(argv):
            state["failed"] = True
            return subprocess.CompletedProcess(argv, 1, "", f"{fail_when} failed")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)


def _attempts(captures: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (captures / "attempts.jsonl").read_text("utf-8").splitlines()]


def test_reset_waits_for_every_deployment_rollout(capsys: pytest.CaptureFixture[str]) -> None:
    pins = load_pins()
    runner = Runner(dry_run=True)
    campaign.reset(runner, pins)
    waits = [c for c in runner.log if "rollout status deploy/" in c]
    names = deployments(pins)
    assert len(names) == 12 and len(waits) == len(names)  # every OB Deployment, not `wait --all`
    assert not any("--for=condition=available" in c for c in runner.log)


def test_a_rollout_that_does_not_finish_is_reset_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _cluster(monkeypatch, fail_when="rollout status deploy/cartservice")
    runner = InstantRunner(dry_run=False)
    assert campaign.run_case(runner, load_pins(), PLAN, PLAN.entries[0], tmp_path) == "reset_failed"
    (attempt,) = _attempts(tmp_path)
    assert attempt["outcome"] == "reset_failed" and "cartservice" in attempt["error"]
    assert not any("apply -f -" in c for c in runner.log)  # no fault was injected
    assert "delete stresschaos" in runner.log[-1]  # the sweep still ran


def test_a_failing_case_is_logged_and_the_next_one_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _cluster(monkeypatch, fail_when="kind version")  # fails while exporting the first case
    runner = InstantRunner(dry_run=False)
    pins = load_pins()
    first = campaign.run_case(runner, pins, PLAN, PLAN.entries[0], tmp_path)
    second = campaign.run_case(runner, pins, PLAN, PLAN.entries[0], tmp_path)
    assert (first, second) == ("case_failed", "captured")
    a, b = _attempts(tmp_path)
    assert a["outcome"] == "case_failed" and "CommandError" in a["error"]
    assert b["outcome"] == "captured"


def test_the_key_is_kept_when_validation_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _cluster(monkeypatch)

    def broken(capture_dir: Path, key: Any) -> Any:
        raise ValueError("Expecting value: line 1 column 1 (char 0)")  # a truncated spool line

    monkeypatch.setattr(validate, "validate_capture", broken)
    outcome = campaign.run_case(InstantRunner(dry_run=False), load_pins(), PLAN, PLAN.entries[0], tmp_path)
    assert outcome == "captured"
    (key_path,) = (tmp_path / "answer_keys").glob("*.json")
    assert json.loads(key_path.read_text(encoding="utf-8"))["validated"] is None
    (attempt,) = _attempts(tmp_path)
    assert attempt["reason"].startswith("validation_error: ValueError")


@pytest.mark.parametrize(
    "error",
    [
        http.client.RemoteDisconnected("closed"),
        ConnectionResetError("reset"),
        ConnectionAbortedError("aborted"),
    ],
)
def test_http_ok_returns_false_instead_of_raising(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    assert Runner(dry_run=False).http_ok("http://127.0.0.1:8080/") is False
