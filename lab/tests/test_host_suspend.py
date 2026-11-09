"""Regression for 2026-11-09: the laptop slept mid-fault and the case would have been kept."""

import json
import subprocess
from pathlib import Path
from typing import Any

import campaign
import pytest
from vlab.cluster import load_pins
from vlab.plan import parse
from vlab.shell import SLEEP_STEP_S, SUSPEND_TOLERANCE_S, HostSuspended, Runner


class FakeClock:
    def __init__(self, jump_at: float | None = None, jump_s: float = 0.0) -> None:
        self.now, self.jump_at, self.jump_s, self.paused = 1000.0, jump_at, jump_s, 0.0

    def time(self) -> float:
        return self.now

    def pause(self, seconds: float) -> None:
        self.paused += seconds
        self.now += seconds
        if self.jump_at is not None and self.paused >= self.jump_at:
            self.now += self.jump_s
            self.jump_at = None


def test_sleep_waits_the_full_time_in_steps() -> None:
    clock = FakeClock()
    Runner(dry_run=False, clock=clock.time, pause=clock.pause).sleep(61, "baseline")
    assert clock.paused == pytest.approx(61)


def test_sleep_raises_when_the_host_was_suspended() -> None:
    clock = FakeClock(jump_at=20, jump_s=SUSPEND_TOLERANCE_S + SLEEP_STEP_S + 1)
    with pytest.raises(HostSuspended):
        Runner(dry_run=False, clock=clock.time, pause=clock.pause).sleep(600, "fault window")


class SuspendingRunner(Runner):
    def sleep(self, seconds: float, reason: str) -> None:
        self.log.append(f"sleep {seconds:g}  # {reason}")
        if reason == "fault window":
            raise HostSuspended("wall clock jumped 1200 s during fault window")

    def http_ok(self, url: str, timeout_s: float = 10.0) -> bool:
        return True


def test_suspended_case_is_logged_cleaned_up_and_has_no_answer_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    plan = parse({"profile": "ob", "seed": 1, "entries": [{"fault": "F01", "target": "frontend"}]})
    runner = SuspendingRunner(dry_run=False)
    outcome = campaign.run_case(runner, load_pins(), plan, plan.entries[0], tmp_path)
    assert outcome == "host_suspended"
    (attempt,) = [json.loads(line) for line in (tmp_path / "attempts.jsonl").read_text("utf-8").splitlines()]
    assert attempt["outcome"] == "host_suspended"
    assert not (tmp_path / "answer_keys").exists()
    assert any("delete stresschaos vl-" in c for c in runner.log)  # the fault's own finally
    assert "delete stresschaos,networkchaos --all" in runner.log[-1]  # and the case-level sweep
