# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6"]
# ///
"""Sync GitHub labels from .github/labels.yml using the GitHub CLI.

Each label is created or updated with `gh label create <name> --color --description --force`,
so re-running is safe. Labels that exist on GitHub but not in the file are left alone
unless you pass --prune (which deletes them; GitHub's default labels such as `bug`,
`enhancement` and `question` would be removed).

Usage
  uv run scripts/sync_labels.py                    # dry run (default): print what would change
  uv run scripts/sync_labels.py --apply            # create/update labels
  uv run scripts/sync_labels.py --apply --prune    # also delete labels not in the file
  uv run scripts/sync_labels.py --apply --repo OWNER/NAME

Run with `uv run scripts/sync_labels.py` (not `uv run python ...`) so uv installs the
inline PyYAML dependency. Needs `gh auth login` for --apply.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LABELS_FILE = ROOT / ".github" / "labels.yml"
DEFAULT_REPO = "DuhItzAniket/Veyltrace"


def load() -> list[dict[str, str]]:
    data = yaml.safe_load(LABELS_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"{LABELS_FILE}: expected a list of labels")
    seen: set[str] = set()
    for item in data:
        name, color = str(item.get("name", "")), str(item.get("color", ""))
        if not name or not re.fullmatch(r"[0-9a-fA-F]{6}", color):
            raise SystemExit(f"bad label entry: {item}")
        if len(str(item.get("description", ""))) > 100:
            raise SystemExit(f"{name}: description longer than GitHub's 100-character limit")
        if name in seen:
            raise SystemExit(f"duplicate label: {name}")
        seen.add(name)
    return data


def gh(*args: str) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise SystemExit(f"gh {' '.join(args[:3])} ... failed:\n{proc.stderr.strip()}")
    return proc.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="create/update labels on GitHub (default: dry run)")
    ap.add_argument("--prune", action="store_true", help="with --apply: delete labels not in labels.yml")
    ap.add_argument("--repo", default=DEFAULT_REPO, help=f"OWNER/NAME (default {DEFAULT_REPO})")
    args = ap.parse_args()

    labels = load()
    if not args.apply:
        print(f"DRY RUN for {args.repo} (use --apply). {len(labels)} label(s) in {LABELS_FILE.relative_to(ROOT).as_posix()}:")
        for lb in labels:
            print(f"  {lb['name']:<20} #{lb['color']}  {lb.get('description', '')}")
        if args.prune:
            print("--prune would also delete labels on GitHub that are not listed above.")
        return 0

    if shutil.which("gh") is None:
        raise SystemExit("gh CLI not found. Install it and run `gh auth login`.")
    for lb in labels:
        gh("label", "create", lb["name"], "--repo", args.repo, "--color", lb["color"],
           "--description", str(lb.get("description", "")), "--force")
        print(f"synced  {lb['name']}")
    if args.prune:
        wanted = {lb["name"] for lb in labels}
        current = [l["name"] for l in json.loads(gh("label", "list", "--repo", args.repo, "--limit", "500", "--json", "name"))]
        for name in sorted(set(current) - wanted):
            gh("label", "delete", name, "--repo", args.repo, "--yes")
            print(f"deleted {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
