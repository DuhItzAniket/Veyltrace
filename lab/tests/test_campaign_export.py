"""Export runs the 05 §8.2 rule and records it in the key and the attempt log (X-11)."""

import json
import subprocess
from pathlib import Path
from typing import Any

import campaign
import pytest
import validate as validate_cli
from vlab.cluster import load_pins
from vlab.plan import parse
from vlab.shell import Runner


class InstantRunner(Runner):
    def sleep(self, seconds: float, reason: str) -> None:
        self.log.append(f"sleep {seconds:g}  # {reason}")

    def http_ok(self, url: str, timeout_s: float = 10.0) -> bool:
        return True


@pytest.fixture
def fake_cluster(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)


@pytest.mark.usefixtures("fake_cluster")
@pytest.mark.parametrize("entry", [{"fault": "F14"}, {"fault": "F01", "target": "frontend"}])
def test_export_validates_and_logs(tmp_path: Path, entry: dict[str, str]) -> None:
    plan = parse({"profile": "ob", "seed": 1, "entries": [entry]})
    runner = InstantRunner(dry_run=False)
    outcome = campaign.run_case(runner, load_pins(), plan, plan.entries[0], tmp_path)
    assert outcome == "captured"
    (attempt,) = [json.loads(line) for line in (tmp_path / "attempts.jsonl").read_text("utf-8").splitlines()]
    (key_path,) = (tmp_path / "answer_keys").glob("*.json")
    key = json.loads(key_path.read_text(encoding="utf-8"))
    # The fake cluster copies no telemetry, so the rule has no baseline: recorded, not kept.
    assert attempt["validated"] is False and attempt["reason"] == "insufficient_baseline"
    assert key["validated"] is False and json.loads(key["sli_impact_json"])["rule"] == "05-8.2"
    assert key["is_no_fault"] is (entry["fault"] == "F14")
    assert isinstance(attempt["t_ns"], int)
    if entry["fault"] == "F14":
        assert any("control window" in c for c in runner.log)
        assert not any("apply -f -" in c for c in runner.log)


def test_validate_cli_rewrites_keys(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    keys = tmp_path / "answer_keys"
    keys.mkdir()
    (keys / ("a" * 32 + ".json")).write_text(
        json.dumps(
            {
                "case_id": "x",
                "dataset": "veyllab-ob",
                "is_no_fault": False,
                "fault_label": "F01",
                "root_service": "frontend",
                "t_inject_ns": 10**18,
            }
        ),
        encoding="utf-8",
    )
    assert validate_cli.main(["--captures", str(tmp_path)]) == 0
    key = json.loads((keys / ("a" * 32 + ".json")).read_text(encoding="utf-8"))
    assert key["validated"] is False and "mode" in key  # every column written back
    assert "0 of 1 validated" in capsys.readouterr().out
