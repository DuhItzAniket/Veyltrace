"""#225 items 5-11 and #222 follow-up 4: one regression test per finding."""

import json
import subprocess
from pathlib import Path
from typing import Any

import campaign
import package as package_cli
import pytest
import report
from test_package import CTX, T0, _span_req, _write_capture
from vlab.faults import CATALOG
from vlab.package import package_capture, scrub_request
from vlab.plan import parse


def test_f05_uses_the_pre_registered_indicator() -> None:
    assert CATALOG["F05"].indicator == "latency"  # 04 §7: loss -> latency (#227 D6)


def test_injection_json_records_what_was_applied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import jsonschema
    from test_answer_key import _content_schema
    from test_campaign_errors import InstantRunner

    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "", ""))
    plan = parse({"profile": "ob", "seed": 1, "entries": [{"fault": "F04", "target": "cartservice"}]})
    from vlab.cluster import load_pins

    campaign.run_case(InstantRunner(dry_run=False), load_pins(), plan, plan.entries[0], tmp_path)
    (key_path,) = (tmp_path / "answer_keys").glob("*.json")
    injection = json.loads(json.loads(key_path.read_text(encoding="utf-8"))["injection_json"])
    jsonschema.validate(injection, _content_schema("injection_json"))
    (manifest,) = injection["params"]["applied"]["manifests"]
    assert manifest["kind"] == "NetworkChaos"
    assert {"direction", "mode", "duration"} <= set(manifest["spec"])
    assert manifest["spec"]["delay"]["correlation"] == "0"


def test_events_rows_validate_against_the_contract(tmp_path: Path) -> None:
    from veyltrace_contracts.models import TelemetryEventsRow

    cap = _write_capture(tmp_path)
    out = tmp_path / "pkg" / cap.name
    assert package_capture(cap, T0 + 5, out, CTX).deny_hits == []
    rows = [json.loads(line) for line in (out / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows and all(TelemetryEventsRow.model_validate(r).actor is None for r in rows)  # 03 §2.5


@pytest.mark.parametrize("kind", ["StressChaos", "NetworkChaos", "PodChaos", "IOChaos", "HTTPChaos"])
def test_a_crd_kind_fails_the_scan(tmp_path: Path, kind: str) -> None:
    cap = _write_capture(tmp_path, {"note": f"applied {kind}"})
    report_ = package_capture(cap, T0 + 5, tmp_path / "pkg" / cap.name, CTX)
    assert {hit.split(": ")[-1].lower() for hit in report_.deny_hits} >= {"chaos"}  # no word start


def test_feature_flag_attributes_are_stripped_from_span_events_and_data_points() -> None:
    req = _span_req({"service.name": "frontend"}, {})
    span = req["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    flag = [{"key": "feature_flag.key", "value": {"stringValue": "x"}}]
    span["events"] = [{"name": "evaluation", "attributes": list(flag)}]
    span["links"] = [{"traceId": "t", "attributes": list(flag)}]
    scrub_request(req, "traces", CTX, _report(), [])
    assert "feature_flag" not in json.dumps(req)
    metric = {"name": "m", "sum": {"dataPoints": [{"asInt": "1", "attributes": list(flag)}]}}
    mreq = {"resourceMetrics": [{"resource": {"attributes": []}, "scopeMetrics": [{"metrics": [metric]}]}]}
    scrub_request(mreq, "metrics", CTX, _report(), [])
    assert "feature_flag" not in json.dumps(mreq)


def _report() -> Any:
    from vlab.package import Report

    return Report()


def test_a_surviving_feature_flag_fails_packaging(tmp_path: Path) -> None:
    cap = _write_capture(tmp_path, {"message": "evaluated feature_flag.key"})  # in a value, not a key
    report_ = package_capture(cap, T0 + 5, tmp_path / "pkg" / cap.name, CTX)
    assert any("feature_flag" in hit for hit in report_.deny_hits)


def test_campaign_sweeps_before_the_first_case_and_cleanup_only_sweeps(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from vlab import LAB_DIR

    assert campaign.main(["--plan", str(LAB_DIR / "plans" / "x02-smoke.yaml"), "--dry-run"]) == 0
    cmds = [line for line in capsys.readouterr().out.splitlines() if line.startswith("+ ")]
    first_case = next(i for i, c in enumerate(cmds) if "rollout restart" in c)
    assert any("delete stresschaos" in c for c in cmds[:first_case])  # leftovers cleared first
    assert campaign.main(["--cleanup", "--dry-run"]) == 0
    only = [line for line in capsys.readouterr().out.splitlines() if line.startswith("+ ")]
    assert len(only) == 2 and "delete" in only[0] and "apply -k" in only[1]


def test_package_refuses_a_data_root_inside_a_git_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".git").mkdir()
    inside = tmp_path / "data"
    assert (
        package_cli.main(
            ["--dataset", "veyllab-ob", "--captures", str(tmp_path / "x"), "--data-root", str(inside)]
        )
        == 2
    )
    assert "inside a git work tree" in capsys.readouterr().err
    assert not inside.exists()


def test_report_takes_the_reason_from_the_verdict(tmp_path: Path) -> None:
    (tmp_path / "answer_keys").mkdir()
    (tmp_path / "attempts.jsonl").write_text(
        json.dumps(
            {"capture_id": "a", "fault": "F01", "outcome": "captured", "t_ns": T0, "reason": "no_impact"}
        )
        + "\n",
        encoding="utf-8",
    )
    impact = {"reason": "impact", "rule": "05-8.2"}
    (tmp_path / "answer_keys" / "a.json").write_text(
        json.dumps({"validated": True, "sli_impact_json": json.dumps(impact)}), encoding="utf-8"
    )
    (row,) = report.load_attempts(tmp_path)
    assert (row["validated"], row["reason"]) == (True, "impact")
