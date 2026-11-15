"""Daily collection count for the standup (X-11; 05 §8.2 rule 5, §8.3).

    uv run python lab/report.py                    # today (local date)
    uv run python lab/report.py --date 2026-11-09
    uv run python lab/report.py --all              # every attempt so far

Reads ``lab/captures/attempts.jsonl`` and the answer keys, and prints a Markdown block to paste:
attempts, captures and validated cases per fault type, the reasons cases were lost, and progress
toward the dataset target. For the team total, run it on the merged captures of all laptops.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from vlab import CAPTURES_DIR, answer_key

#: v1.0 dataset target: at least 120 validated cases (05 §12; 02 §12 default).
TARGET_VALIDATED = 120


def _day(t_ns: int | None) -> str:
    return "undated" if t_ns is None else datetime.fromtimestamp(t_ns / 1e9).date().isoformat()


def load_attempts(captures: Path) -> list[dict[str, Any]]:
    """Attempts with their day and the validation recorded in their answer key, if any.

    Attempts logged before X-11 carry neither ``t_ns`` nor a validation; the key or the capture's
    orchestrator.json fills them in. A capture id logged twice (e.g. superseded) counts once, as its
    last record.
    """
    path = captures / "attempts.jsonl"
    if not path.is_file():
        return []
    latest: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            latest[rec["capture_id"]] = rec
    out = []
    for cid, rec in latest.items():
        key_path = captures / answer_key.ANSWER_KEYS / f"{cid}.json"
        key = json.loads(key_path.read_text(encoding="utf-8")) if key_path.is_file() else {}
        t_ns = rec.get("t_ns") or key.get("t_inject_ns")
        orch = captures / cid / "orchestrator.json"
        if t_ns is None and orch.is_file():
            t_ns = json.loads(orch.read_text(encoding="utf-8")).get("t_capture_start_ns")
        validated = key.get("validated", rec.get("validated"))
        impact = json.loads(key["sli_impact_json"]) if key.get("sli_impact_json") else {}
        reason = impact.get("reason", rec.get("reason"))  # the verdict's own reason, not a stale one
        out.append({**rec, "day": _day(t_ns), "validated": validated, "reason": reason})
    return out


def render(
    attempts: Iterable[Mapping[str, Any]], *, title: str, all_attempts: Sequence[Mapping[str, Any]]
) -> str:
    rows = list(attempts)
    per: dict[str, Counter[str]] = defaultdict(Counter)
    lost: Counter[str] = Counter()
    for a in rows:
        c = per[a["fault"]]
        c["attempts"] += 1
        if a["outcome"] == "captured":
            c["captured"] += 1
            c["validated"] += a["validated"] is True
            if a["validated"] is False:
                lost[f"not validated ({a.get('reason', 'no_impact')})"] += 1
        else:
            lost[a["outcome"]] += 1
    total = Counter[str]()
    for c in per.values():
        total.update(c)
    lines = [
        f"**Lab collection: {title}**",
        "",
        "| Fault | Attempts | Captured | Validated |",
        "|---|---|---|---|",
    ]
    for fault in sorted(per):
        c = per[fault]
        lines.append(f"| {fault} | {c['attempts']} | {c['captured']} | {c['validated']} |")
    rate = f"{100 * total['validated'] / total['attempts']:.0f}%" if total["attempts"] else "n/a"
    lines += [
        f"| **Total** | **{total['attempts']}** | **{total['captured']}** | **{total['validated']}** |",
        "",
    ]
    lines.append(f"Acceptance rate: {rate} of attempts validated.")
    if lost:
        lines.append("Lost: " + ", ".join(f"{n} {why}" for why, n in sorted(lost.items())) + ".")
    so_far = sum(1 for a in all_attempts if a["outcome"] == "captured" and a["validated"] is True)
    lines.append(f"Validated so far: {so_far} / {TARGET_VALIDATED} (dataset target).")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab/report.py", description=__doc__.splitlines()[0])
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--date", type=date.fromisoformat, help="YYYY-MM-DD (default: today)")
    group.add_argument("--all", action="store_true", help="every attempt, not one day")
    ap.add_argument("--captures", type=Path, default=CAPTURES_DIR)
    args = ap.parse_args(argv)
    attempts = load_attempts(args.captures)
    if args.all:
        chosen, title = attempts, "all attempts"
    else:
        day = (args.date or date.today()).isoformat()
        chosen, title = [a for a in attempts if a["day"] == day], day
    if not chosen:
        print(f"report: no attempts for {title}", file=sys.stderr)
        return 1
    print(render(chosen, title=title, all_attempts=attempts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
