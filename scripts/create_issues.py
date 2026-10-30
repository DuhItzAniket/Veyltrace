"""Create the GitHub milestones and issues listed in docs/07-roadmap.md (task L-00).

Reads
  - milestones M0-M5 (title and date) from the mermaid gantt in docs/07-roadmap.md,
    and their exit criteria from the milestone table;
  - every task table (columns ID | Task | Lane | Est | Depends | Acceptance criteria;
    the Release table has no Depends column).

Creates (only with --apply)
  - each missing milestone, due on its date;
  - one issue per task, titled "<ID> <task>", with the acceptance criteria as a
    checklist, the estimate and dependencies, labels lane:<lane> and type:<type>,
    and the milestone of the task's phase (Phase N -> MN, Release -> M5).
Idempotent: a milestone with the same title, or an issue whose title starts with
"<ID> ", is skipped. Labels must exist first: run scripts/sync_labels.py --apply.

Usage
  python scripts/create_issues.py                  # dry run (default): print the plan, call nothing
  python scripts/create_issues.py --apply          # create missing milestones and issues with gh
  python scripts/create_issues.py --apply --repo OWNER/NAME

Needs the GitHub CLI (`gh auth login`) for --apply. Standard library only.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROADMAP = ROOT / "docs" / "07-roadmap.md"
DEFAULT_REPO = "DuhItzAniket/Veyltrace"

LANES = {"R": ["reason"], "O": ["observe"], "X": ["explain"], "all": ["reason", "observe", "explain"]}

# Issue type per task. Anything not listed is type:feat. Keep in step with docs/07-roadmap.md.
TYPE_OF = {
    "L-00": "chore", "L-01": "chore", "L-02": "docs", "L-03": "chore", "L-04": "chore",
    "L-05": "chore", "L-06": "docs", "L-07": "adr",
    "R-05": "exp", "R-07": "chore", "R-11": "exp", "R-13": "exp", "R-16": "exp", "R-17": "exp",
    "R-18": "paper", "O-12": "docs", "X-11": "exp", "X-13": "paper",
}

GANTT_MILESTONE = re.compile(r"^\s*(M\d [^:]+?)\s*:milestone,\s*m\d+,\s*(\d{4}-\d{2}-\d{2})")
MILESTONE_ROW = re.compile(r"^\|\s*\*\*(M\d[^*]*)\*\*\s*\|([^|]*)\|([^|]*)\|([^|]*)\|")
PHASE_HEADING = re.compile(r"^##\s+\d+\.\s+(Phase\s+(\d)|Release)\b(.*)$")
REL_LINK = re.compile(r"\]\((?!https?:|#)([^)\s]+)\)")


@dataclass
class Milestone:
    key: str          # "M0"
    title: str        # "M0 Ground ready"
    due: str          # "2026-11-03"
    description: str = ""


@dataclass
class Task:
    id: str
    task: str
    lane: str
    est: str
    depends: str
    acceptance: str
    phase: str
    milestone: str
    labels: list[str] = field(default_factory=list)


def split_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def absolutise(text: str, repo: str) -> str:
    """Turn docs-relative links into absolute GitHub links so they work in issue bodies."""
    def fix(m: re.Match[str]) -> str:
        target = m.group(1)
        path = (ROADMAP.parent / target.split("#")[0]).resolve()
        try:
            relp = path.relative_to(ROOT).as_posix()
        except ValueError:
            return m.group(0)
        anchor = "#" + target.split("#", 1)[1] if "#" in target else ""
        return f"](https://github.com/{repo}/blob/main/{relp}{anchor})"
    return REL_LINK.sub(fix, text)


def parse(repo: str) -> tuple[list[Milestone], list[Task]]:
    lines = ROADMAP.read_text(encoding="utf-8").splitlines()
    milestones: dict[str, Milestone] = {}
    for line in lines:
        m = GANTT_MILESTONE.match(line)
        if m:
            title = m.group(1).strip()
            milestones[title.split()[0]] = Milestone(title.split()[0], title, m.group(2))
    for line in lines:
        m = MILESTONE_ROW.match(line)
        if m:
            key = m.group(1).split()[0]
            if key in milestones:
                criteria = m.group(3).strip()
                tag = m.group(4).strip().strip("`")
                milestones[key].description = f"{criteria} Tag: {tag}."[:750]
    if len(milestones) != 6:
        raise SystemExit(f"expected milestones M0-M5 in the gantt chart, found {sorted(milestones)}")

    tasks: list[Task] = []
    phase = ""
    milestone = ""
    header: list[str] | None = None
    for line in lines:
        h = PHASE_HEADING.match(line)
        if h:
            phase = re.sub(r"^\d+\.\s*", "", line.lstrip("#").strip())
            key = f"M{h.group(2)}" if h.group(2) is not None else "M5"
            milestone = milestones[key].title
            header = None
            continue
        if line.startswith("## "):
            phase, milestone, header = "", "", None
            continue
        if not phase or not line.startswith("|"):
            continue
        cells = split_row(line)
        if cells and cells[0] == "ID":
            header = cells
            continue
        if header is None or set("".join(cells)) <= set("-: "):
            continue
        row = dict(zip(header, cells))
        tid = row.get("ID", "")
        if not re.fullmatch(r"[LROX]-\d{2}", tid):
            continue
        lane_code = row.get("Lane", "")
        if lane_code not in LANES:
            raise SystemExit(f"{tid}: unknown lane '{lane_code}' (expected R, O, X or all)")
        labels = [f"lane:{ln}" for ln in LANES[lane_code]] + [f"type:{TYPE_OF.get(tid, 'feat')}"]
        tasks.append(Task(
            id=tid,
            task=absolutise(row.get("Task", ""), repo),
            lane=lane_code,
            est=row.get("Est", "?"),
            depends=row.get("Depends", "—") or "—",
            acceptance=absolutise(row.get("Acceptance criteria", ""), repo),
            phase=phase,
            milestone=milestone,
            labels=labels,
        ))
    ids = [t.id for t in tasks]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise SystemExit(f"duplicate task IDs in roadmap: {dupes}")
    return list(milestones.values()), tasks


def plain_title(task: Task) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", task.task)   # drop link targets
    text = text.replace("`", "")
    # Keep as many leading clauses as fit in ~90 characters; the full text is in the body.
    clauses = [c.strip() for c in text.split("; ") if c.strip()]
    first = clauses[0] if clauses else text.strip()
    for clause in clauses[1:]:
        if len(first) + 2 + len(clause) > 90:
            break
        first = f"{first}, {clause}"
    if len(first) > 100:
        first = first[:97].rstrip() + "..."
    return f"{task.id} {first}"


def body(task: Task, numbers: dict[str, int], repo: str) -> str:
    def link_ids(text: str) -> str:
        return re.sub(r"\b([LROX]-\d{2})\b", lambda m: f"{m.group(1)} (#{numbers[m.group(1)]})" if m.group(1) in numbers else m.group(1), text)

    lanes = ", ".join(LANES[task.lane])
    return "\n".join([
        f"**Roadmap task** `{task.id}` · {task.phase} · milestone **{task.milestone}**",
        f"**Lane:** {lanes} · **Estimate:** {task.est} person-days (*estimate*) · **Depends on:** {link_ids(task.depends)}",
        "",
        "### Task",
        task.task,
        "",
        "### Acceptance criteria",
        f"- [ ] {task.acceptance}",
        "",
        "### Before you start",
        f"- Read [AGENTS.md](https://github.com/{repo}/blob/main/AGENTS.md), then the docs linked above, then the engine spec in `docs/engines/` if any.",
        f"- Follow the session protocol in [docs/09-ai-agent-playbook.md §4](https://github.com/{repo}/blob/main/docs/09-ai-agent-playbook.md#4-session-protocol).",
        "- The PR must tick the Definition of Done and carry `lane:*`, `type:*` and `agent:*` labels.",
        "",
        f"<sub>Generated by `scripts/create_issues.py` from [docs/07-roadmap.md](https://github.com/{repo}/blob/main/docs/07-roadmap.md). Change scope in the roadmap first.</sub>",
    ])


def gh(*args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise SystemExit(f"gh {' '.join(args[:3])} ... failed:\n{proc.stderr.strip()}")
    return proc.stdout


def apply(repo: str, milestones: list[Milestone], tasks: list[Task]) -> int:
    if shutil.which("gh") is None:
        raise SystemExit("gh CLI not found. Install it and run `gh auth login`.")

    have_labels = {l["name"] for l in json.loads(gh("label", "list", "--repo", repo, "--limit", "500", "--json", "name"))}
    missing = sorted({l for t in tasks for l in t.labels} - have_labels)
    if missing:
        raise SystemExit(f"labels missing in {repo}: {missing}\nRun first: uv run scripts/sync_labels.py --apply")

    existing_ms = {m["title"] for m in json.loads(gh("api", f"repos/{repo}/milestones?state=all&per_page=100"))}
    for ms in milestones:
        if ms.title in existing_ms:
            print(f"skip milestone  {ms.title} (exists)")
            continue
        gh("api", f"repos/{repo}/milestones", "-X", "POST",
           "-f", f"title={ms.title}", "-f", f"due_on={ms.due}T12:00:00Z", "-f", f"description={ms.description}")
        print(f"created milestone {ms.title} due {ms.due}")

    issues = json.loads(gh("issue", "list", "--repo", repo, "--state", "all", "--limit", "1000", "--json", "number,title"))
    numbers: dict[str, int] = {}
    for it in issues:
        m = re.match(r"([LROX]-\d{2}) ", it["title"])
        if m:
            numbers.setdefault(m.group(1), it["number"])
    created = 0
    for t in tasks:
        if t.id in numbers:
            print(f"skip issue      {t.id} (#{numbers[t.id]} exists)")
            continue
        args = ["issue", "create", "--repo", repo, "--title", plain_title(t), "--body-file", "-", "--milestone", t.milestone]
        for label in t.labels:
            args += ["--label", label]
        url = gh(*args, stdin=body(t, numbers, repo)).strip()
        num = int(url.rstrip("/").rsplit("/", 1)[-1])
        numbers[t.id] = num
        created += 1
        print(f"created issue   #{num} {plain_title(t)}")
    print(f"done: {created} issue(s) created, {len(tasks) - created} skipped.")
    return 0


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):  # Windows pipes default to cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="print the plan; call nothing (default)")
    mode.add_argument("--apply", action="store_true", help="create missing milestones and issues with gh")
    ap.add_argument("--repo", default=DEFAULT_REPO, help=f"OWNER/NAME (default {DEFAULT_REPO})")
    ap.add_argument("--show-body", action="store_true", help="dry run: also print each issue body")
    args = ap.parse_args()

    milestones, tasks = parse(args.repo)
    if args.apply:
        return apply(args.repo, milestones, tasks)

    print(f"DRY RUN (nothing is created; use --apply). Repo: {args.repo}\n")
    print("Milestones:")
    for ms in milestones:
        print(f"  {ms.title:<22} due {ms.due}")
    print(f"\nIssues ({len(tasks)}):")
    for t in tasks:
        print(f"  {plain_title(t):<70} [{', '.join(t.labels)}] -> {t.milestone}")
        if args.show_body:
            print("    " + body(t, {}, args.repo).replace("\n", "\n    ") + "\n")
    print("\nOn --apply, milestones and issues that already exist (same title / same ID prefix) are skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
