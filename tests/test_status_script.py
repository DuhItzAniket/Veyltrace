"""scripts/status.py (#240): the status issue and board must agree with the issues and PRs, so
these pin the matching rules and the bottom-first stack order on hand-made inputs (no GitHub)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

ROADMAP = """\
## 2. Phase 0 — Ground (Sat 31 Oct – Tue 3 Nov)

| ID | Task | Lane | Est | Depends | Acceptance criteria |
|---|---|---|---|---|---|
| R-01 | Contracts v0.1: JSON Schemas for [03](03-contracts.md) | R | 1 | — | ok |
| O-04 | Anomara: robust z; BOCPD | O | 2 | R-01 | ok |

## 7. Release (Mon 30 Nov – Tue 1 Dec) → M5

| L-07 | Retrospective; plan in [the ADRs](adr/) | all | 0.5 | ADR merged |
"""


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("status", ROOT / "scripts" / "status.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["status"] = mod
    spec.loader.exec_module(mod)
    return mod


status = _load()


def _issue(number: int, title: str, state: str = "OPEN") -> dict[str, Any]:
    return {"number": number, "title": title, "state": state, "url": f"u/{number}"}


def _pr(number: int, head: str, base: str = "main", **kw: Any) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"feat(x): t (#{number})",
        "headRefName": head,
        "baseRefName": base,
        "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        **kw,
    }


def test_roadmap_rows_keep_phase_and_short_title() -> None:
    tasks = status.parse_roadmap(ROADMAP)
    assert [(t.id, t.title, t.lane, t.phase) for t in tasks] == [
        ("R-01", "Contracts v0.1", "Reason", "Phase 0 — Ground"),
        ("O-04", "Anomara", "Observe", "Phase 0 — Ground"),
        ("L-07", "Retrospective", "all", "Release"),
    ]


def test_issues_split_into_task_sub_and_follow_up() -> None:
    tasks = status.parse_roadmap(ROADMAP)
    status.attach_issues(
        tasks,
        [
            _issue(21, "O-04 Anomara: robust z"),
            _issue(84, "O-04c Anomara series layer", "CLOSED"),
            _issue(82, "O-04a Observe deps", "CLOSED"),
            _issue(300, "O-04 follow-up: minors"),
            _issue(301, "O-040 is not O-04"),
        ],
    )
    o04 = tasks[1]
    assert o04.issue is not None and o04.issue["number"] == 21
    assert [i["number"] for i in o04.subs] == [82, 84]
    assert [i["number"] for i in o04.followups] == [300]


def test_task_done_needs_its_issue_and_every_sub_issue_closed() -> None:
    own, sub, fup = _issue(21, "O-04 x"), _issue(85, "O-04f y"), _issue(300, "O-04 follow-up")
    task = status.Task("O-04", "Anomara", "Observe", "p", issue=own, subs=[sub], followups=[fup])
    assert status.task_state(task, set()) == status.TODO
    assert status.task_state(task, {85}) == status.DOING
    sub["state"] = "CLOSED"
    assert status.task_state(task, set()) == status.DOING  # its own issue is still open
    own["state"] = "CLOSED"
    assert status.task_state(task, set()) == status.DONE  # an open follow-up does not reopen it


def test_stacks_run_bottom_first_and_next_step_reads_the_bottom() -> None:
    prs = [
        _pr(3, "observe/3-c", "observe/2-b"),
        _pr(2, "observe/2-b", "observe/1-a"),
        _pr(1, "observe/1-a", mergeStateStatus="DIRTY"),
        _pr(9, "reason/9-z", reviewDecision="APPROVED", mergeStateStatus="BEHIND"),
    ]
    chains = status.stacks(prs)
    assert [[p["number"] for p in c] for c in chains] == [[1, 2, 3], [9]]
    assert status.next_step(chains[0][0]) == "merge main into it (conflicts)"
    assert status.next_step(chains[1][0]) == "ready to merge"
    assert status.pr_issue(prs[0]) == 3


def test_render_is_stable_for_the_same_input() -> None:
    tasks = status.parse_roadmap(ROADMAP)
    prs = [_pr(1, "observe/1-a")]
    assert status.render(tasks, prs, "abc1234def") == status.render(tasks, prs, "abc1234def")
    assert "at main `abc1234`" in status.render(tasks, prs, "abc1234def")
