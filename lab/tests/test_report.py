"""X-11 acceptance: the daily count posted in the standup."""

import json
from pathlib import Path

import report

DAY_NS = 1_794_200_000 * 1_000_000_000  # 2026-11-09 (UTC)


def _write(tmp: Path, attempts: list[dict[str, object]], keys: dict[str, dict[str, object]]) -> None:
    (tmp / "answer_keys").mkdir()
    (tmp / "attempts.jsonl").write_text("".join(json.dumps(a) + "\n" for a in attempts), encoding="utf-8")
    for cid, key in keys.items():
        (tmp / "answer_keys" / f"{cid}.json").write_text(json.dumps(key), encoding="utf-8")


def test_counts_per_fault_with_reasons_and_target(tmp_path: Path) -> None:
    t = DAY_NS
    _write(
        tmp_path,
        [
            {"capture_id": "a", "fault": "F01", "outcome": "captured", "t_ns": t, "validated": True},
            {"capture_id": "b", "fault": "F01", "outcome": "host_suspended", "t_ns": t},
            {
                "capture_id": "c",
                "fault": "F02",
                "outcome": "captured",
                "t_ns": t,
                "validated": False,
                "reason": "no_impact",
            },
            {
                "capture_id": "d",
                "fault": "F06",
                "outcome": "captured",
            },  # pre-X-11: no t_ns, key has the result
            {"capture_id": "d", "fault": "F06", "outcome": "superseded"},  # a later record wins
        ],
        {"d": {"t_inject_ns": t, "validated": True}},
    )
    out = report.render(
        report.load_attempts(tmp_path), title="t", all_attempts=report.load_attempts(tmp_path)
    )
    assert "| F01 | 2 | 1 | 1 |" in out
    assert "| F02 | 1 | 1 | 0 |" in out
    assert "| F06 | 1 | 0 | 0 |" in out
    assert "| **Total** | **4** | **2** | **1** |" in out
    assert "1 host_suspended" in out and "1 not validated (no_impact)" in out and "1 superseded" in out
    assert "Validated so far: 1 / 120" in out


def test_cli_filters_by_day(tmp_path: Path, capsys: object) -> None:
    _write(
        tmp_path,
        [{"capture_id": "a", "fault": "F01", "outcome": "captured", "t_ns": DAY_NS, "validated": True}],
        {},
    )
    day = report.load_attempts(tmp_path)[0]["day"]
    assert report.main(["--captures", str(tmp_path), "--date", day]) == 0
    assert report.main(["--captures", str(tmp_path), "--date", "2000-01-01"]) == 1
