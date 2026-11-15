"""Status report: roadmap tasks, their issues and the open PR stacks (L-08, #240).

Why: with 40+ stacked PRs, GitHub had no single page saying what is done and what is left.
This joins the task tables of docs/07-roadmap.md with the issues and PRs into one Markdown
report, written to a file (`--out`, `-` for stdout), to the pinned status issue (`--issue N`),
and as the Status field (Backlog / In progress / Done) on GitHub Project N (`--project N`).

Matching: a task's issue title starts with "<ID> " ("O-04 Anomara: …"); sub-issues add a
letter suffix ("O-04a", "O-01b2"); follow-ups start with "<ID> follow-up"; a PR belongs to
issue N when its branch is "<lane>/<N>-<slug>". A task is done when its issue and every
sub-issue are closed (open follow-ups are listed, not counted); it is in progress when any
of them is closed or has an open PR. The text is sorted and names the main commit instead
of a timestamp, so the same GitHub state gives the same report.

Usage: uv run python scripts/status.py --out -   |   ... --issue 241 --project 3
Needs `gh auth login` (and the `project` scope for --project).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ROADMAP = ROOT / "docs" / "07-roadmap.md"

PHASE = re.compile(r"^## \d+\. (.+?)(?: \(.*)?$")
ROW = re.compile(r"^\| ([LROX]-\d+) \| (.+?) \| (R|O|X|all) \|")
TITLE_ID = re.compile(r"^([LROX]-\d+)([a-z]\d*)?( follow-up)?[ :]")
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
SCOPE = re.compile(r"^\w+\(([^)]+)\)")
BRANCH_ISSUE = re.compile(r"^[a-z]+/(\d+)-")
LANES = {"R": "Reason", "O": "Observe", "X": "Explain", "all": "all"}
BAD = {"FAILURE", "ERROR", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
DONE, DOING, TODO = "Done", "In Progress", "Todo"
FMT = ("--format", "json")
# Board columns per state, first one is set; an item already in any of them is left alone, so
# hand-moved cards (Ready, In review) keep their column. Names match the Veyltrace Roadmap board.
COLUMNS = {DONE: ("Done",), DOING: ("In progress", "In review"), TODO: ("Backlog", "Ready")}
PR_FIELDS = "number,title,headRefName,baseRefName,reviewDecision,mergeStateStatus,isDraft,statusCheckRollup"


@dataclass
class Task:
    id: str
    title: str
    lane: str
    phase: str
    issue: dict[str, Any] | None = None
    subs: list[dict[str, Any]] = field(default_factory=lambda: [])
    followups: list[dict[str, Any]] = field(default_factory=lambda: [])


def parse_roadmap(text: str) -> list[Task]:
    """Task rows of docs/07-roadmap.md in file order, each with its phase heading."""
    tasks: list[Task] = []
    phase = ""
    for line in text.splitlines():
        if m := PHASE.match(line):
            phase = m.group(1)
        elif m := ROW.match(line):
            text = LINK.sub(r"\1", m.group(2))
            title = re.split(r"[:;(]", text, maxsplit=1)[0].strip().replace("`", "")
            tasks.append(Task(m.group(1), title, LANES[m.group(3)], phase))
    return tasks


def attach_issues(tasks: list[Task], issues: list[dict[str, Any]]) -> None:
    """Give each task its issue, sub-issues and follow-ups (sorted by number)."""
    by_id = {t.id: t for t in tasks}
    for issue in sorted(issues, key=lambda i: i["number"]):
        m = TITLE_ID.match(issue["title"])
        if not m or m.group(1) not in by_id:
            continue
        task = by_id[m.group(1)]
        if m.group(3):
            task.followups.append(issue)
        elif m.group(2):
            task.subs.append(issue)
        elif task.issue is None:
            task.issue = issue


def pr_issue(pr: dict[str, Any]) -> int | None:
    m = BRANCH_ISSUE.match(pr["headRefName"])
    return int(m.group(1)) if m else None


def issue_state(issue: dict[str, Any], open_prs: set[int]) -> str:
    if issue["state"] == "CLOSED":
        return DONE
    return DOING if issue["number"] in open_prs else TODO


def task_state(task: Task, open_prs: set[int]) -> str:
    own = ([task.issue] if task.issue else []) + task.subs
    states = [issue_state(i, open_prs) for i in own]
    if states and all(s == DONE for s in states):
        return DONE
    return DOING if any(s != TODO for s in states) else TODO


def ci_state(pr: dict[str, Any]) -> str:
    runs = [c.get("conclusion") or c.get("state") or "" for c in pr.get("statusCheckRollup") or []]
    if any(r in BAD for r in runs):
        return "failing"
    if any(r in ("", "PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED") for r in runs):
        return "running"
    return "green" if runs else "none"


def review_state(pr: dict[str, Any]) -> str:
    return {
        "APPROVED": "approved",
        "CHANGES_REQUESTED": "changes requested",
        "REVIEW_REQUIRED": "needs review",
    }.get(pr.get("reviewDecision") or "", "not reviewed")


def stacks(prs: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Open PRs as stacks, bottom (based on main or a gone branch) to top, depth first."""
    heads = {p["headRefName"] for p in prs}
    children: dict[str, list[dict[str, Any]]] = {}
    for p in prs:
        children.setdefault(p["baseRefName"], []).append(p)
    for kids in children.values():
        kids.sort(key=lambda p: p["number"])
    out: list[list[dict[str, Any]]] = []
    for bottom in sorted((p for p in prs if p["baseRefName"] not in heads), key=lambda p: p["number"]):
        chain: list[dict[str, Any]] = []
        todo = [bottom]
        while todo:
            p = todo.pop(0)
            chain.append(p)
            todo[:0] = children.get(p["headRefName"], [])
        out.append(chain)
    return out


def next_step(bottom: dict[str, Any]) -> str:
    """What unblocks a stack, read from its bottom PR."""
    if bottom.get("isDraft"):
        return "draft"
    if bottom["baseRefName"] != "main":
        return f"base branch {bottom['baseRefName']} is gone: retarget to main"
    if bottom.get("mergeStateStatus") == "DIRTY":
        return "merge main into it (conflicts)"
    ci = ci_state(bottom)
    if ci != "green":
        return {"failing": "fix CI", "running": "wait for CI"}.get(ci, "push to run CI")
    if bottom.get("reviewDecision") == "CHANGES_REQUESTED":
        return "author fixes, then re-review"
    if bottom.get("reviewDecision") == "REVIEW_REQUIRED":
        return "review, then merge"
    return "ready to merge"


def render(tasks: list[Task], prs: list[dict[str, Any]], main_sha: str) -> str:
    open_prs = {n for n in (pr_issue(p) for p in prs) if n is not None}
    lines = [
        "# Veyltrace status",
        "",
        f"Generated by `scripts/status.py` from `docs/07-roadmap.md`, the issues and the open PRs, "
        f"at main `{main_sha[:7]}`. Edits to this text are overwritten; change the issues instead.",
        "",
    ]
    counts = {s: sum(task_state(t, open_prs) == s for t in tasks) for s in (DONE, DOING, TODO)}
    lines += [
        f"**Tasks:** {counts[DONE]} done · {counts[DOING]} in progress · {counts[TODO]} not started"
        f" · **open PRs:** {len(prs)}",
        "",
        "## Open PR stacks (bottom first; merge in this order)",
        "",
    ]
    for chain in stacks(prs):
        bottom = chain[0]
        m = SCOPE.match(bottom["title"])
        lane = bottom["headRefName"].split("/")[0]
        held = sum(p.get("reviewDecision") == "CHANGES_REQUESTED" for p in chain)
        lines.append(
            f"**{m.group(1) if m else lane} ({lane}, {len(chain)} PR{'s' * (len(chain) > 1)})"
            f" · next: {next_step(bottom)}"
            f" · {held} with changes requested**"
        )
        lines.append("")
        lines.append("| PR | Issue | Title | Review | CI | Merge state |")
        lines.append("|---|---|---|---|---|---|")
        for p in chain:
            n = pr_issue(p)
            title = p["title"].replace("|", "\\|")
            lines.append(
                f"| #{p['number']} | {f'#{n}' if n else '—'} | {title} | {review_state(p)} "
                f"| {ci_state(p)} | {(p.get('mergeStateStatus') or '').lower()} |"
            )
        lines.append("")
    marks = {DONE: "✅", DOING: "🟡", TODO: "⬜"}
    phase = None
    for t in tasks:
        if t.phase != phase:
            phase = t.phase
            lines += ["", f"## {phase}", "", "| | Task | Lane | Issue | Sub-issues done | Open follow-ups |"]
            lines.append("|---|---|---|---|---|---|")
        subs_done = sum(s["state"] == "CLOSED" for s in t.subs)
        subs = f"{subs_done}/{len(t.subs)}" if t.subs else "—"
        fups = " ".join(f"#{f['number']}" for f in t.followups if f["state"] == "OPEN") or "—"
        issue = f"#{t.issue['number']}" if t.issue else "no issue"
        lines.append(
            f"| {marks[task_state(t, open_prs)]} | **{t.id}** {t.title} | {t.lane} | {issue} "
            f"| {subs} | {fups} |"
        )
    lines += ["", "✅ done · 🟡 in progress (an issue closed or a PR open) · ⬜ not started", ""]
    return "\n".join(lines)


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout


def gh_json(*args: str) -> Any:
    return json.loads(gh(*args))


def sync_project(number: int, owner: str, tasks: list[Task], open_prs: set[int]) -> int:
    """Set Status on every task issue in Project `number`; returns how many items changed."""
    proj = gh_json("project", "view", str(number), "--owner", owner, "--format", "json")
    fields = gh_json("project", "field-list", str(number), "--owner", owner, "--format", "json")
    status = next(f for f in fields["fields"] if f["name"] == "Status")
    options = {o["name"]: o["id"] for o in status["options"]}
    items = gh_json("project", "item-list", str(number), "--owner", owner, "--format", "json", "-L", "1000")
    have = {i["content"].get("number"): i for i in items["items"] if i.get("content")}
    wanted: dict[int, tuple[str, str]] = {}
    for t in tasks:
        if t.issue:
            wanted[t.issue["number"]] = (t.issue["url"], task_state(t, open_prs))
        for i in t.subs + t.followups:
            wanted[i["number"]] = (i["url"], issue_state(i, open_prs))
    changed = 0
    for num in sorted(wanted):
        url, state = wanted[num]
        item = have.get(num)
        if item is None:
            add = gh_json("project", "item-add", str(number), "--owner", owner, "--url", url, *FMT)
            item = {"id": add["id"], "status": None}
        if item.get("status") not in COLUMNS[state]:
            ids = ["--id", item["id"], "--project-id", proj["id"], "--field-id", status["id"]]
            gh("project", "item-edit", *ids, "--single-select-option-id", options[COLUMNS[state][0]])
            changed += 1
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Write the Veyltrace status report (roadmap, issues, PR stacks)."
    )
    ap.add_argument("--out", help="write the report to this file ('-' for stdout)")
    ap.add_argument("--issue", type=int, help="replace the body of this issue with the report")
    ap.add_argument("--project", type=int, help="sync Status on this GitHub Project (owner = repo owner)")
    args = ap.parse_args(argv)
    if not (args.out or args.issue or args.project):
        ap.error("give at least one of --out, --issue, --project")
    tasks = parse_roadmap(ROADMAP.read_text(encoding="utf-8"))
    issues = gh_json("issue", "list", "--state", "all", "-L", "1000", "--json", "number,title,state,url")
    attach_issues(tasks, issues)
    prs = gh_json("pr", "list", "--state", "open", "-L", "500", "--json", PR_FIELDS)
    main_sha = gh("api", "repos/{owner}/{repo}/commits/main", "-q", ".sha").strip()
    report = render(tasks, prs, main_sha)
    if args.out == "-":
        sys.stdout.write(report)
    elif args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    if args.issue:
        edit = ["gh", "issue", "edit", str(args.issue), "--body-file", "-"]
        subprocess.run(edit, input=report, check=True, text=True, encoding="utf-8", capture_output=True)
    if args.project:
        owner = gh("repo", "view", "--json", "owner", "-q", ".owner.login").strip()
        open_prs = {n for n in (pr_issue(p) for p in prs) if n is not None}
        print(f"project {args.project}: {sync_project(args.project, owner, tasks, open_prs)} items updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
