"""Package raw captures for Infralume's `veyllab` adapter and publish their answer keys (05 §10).

    uv run python lab/package.py --dataset veyllab-ob --captures lab/captures/<capture_id> [...]

Each capture goes to ``${VEYLTRACE_DATA}/veyllab/<dataset>/<capture_id>/``; its answer key is merged
into ``${VEYLTRACE_DATA}/answer_keys/<dataset>.parquet``, where bench reads it (03 §13.1 registry
path). A capture whose package fails the deny-list scan is removed and its key is not published.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from vlab.answer_key import ANSWER_KEYS, COLUMNS
from vlab.cluster import load_pins
from vlab.faults import CONTAINER
from vlab.package import Context, host_replacements, package_capture
from vlab.validate import reference_time_ns

from veyltrace_bench.answer_keys import load_answer_keys, write_answer_keys
from veyltrace_contracts.models import AnswerKeyRow
from veyltrace_core.config import data_root
from veyltrace_core.errors import ArtifactMissing


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab/package.py", description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--captures", type=Path, nargs="+", required=True, help="raw capture folders")
    ap.add_argument("--data-root", type=Path, default=None, help="default: $VEYLTRACE_DATA")
    args = ap.parse_args(argv)
    root = args.data_root.resolve() if args.data_root else data_root()
    if any((p / ".git").exists() for p in (root, *root.parents)):  # as data_root() refuses (#225)
        print(f"package: {root} is inside a git work tree; packaged data may not go there", file=sys.stderr)
        return 2
    pins = load_pins()
    replacements = host_replacements()
    rows: list[AnswerKeyRow] = []
    failed = 0
    for capture_dir in (Path(c).resolve() for c in args.captures):
        capture_id = capture_dir.name
        key_path = capture_dir.parent / ANSWER_KEYS / f"{capture_id}.json"
        key = json.loads(key_path.read_text(encoding="utf-8"))
        if key["dataset"] != args.dataset:
            print(f"package: {capture_id} belongs to {key['dataset']}, not {args.dataset}", file=sys.stderr)
            return 2
        orch = json.loads((capture_dir / "orchestrator.json").read_text(encoding="utf-8"))
        ctx = Context(
            str(pins["app_namespace"]), int(orch["t_capture_start_ns"]), tuple(CONTAINER), replacements
        )
        out_dir = root / "veyllab" / args.dataset / capture_id
        t_alert = reference_time_ns(capture_dir, key)
        if t_alert is None:
            print(f"package: {capture_id} has no injection or reference time", file=sys.stderr)
            return 2
        report = package_capture(capture_dir, t_alert, out_dir, ctx)
        if report.deny_hits:
            failed += 1
            print(f"package: {capture_id} FAILED the deny-list scan:", file=sys.stderr)
            for hit in report.deny_hits[:20]:
                print(f"  {hit}", file=sys.stderr)
            continue
        rows.append(AnswerKeyRow.model_validate({c: key.get(c) for c in COLUMNS}))  # older keys lack columns
        print(f"package: {capture_id} -> {out_dir} ({report.events} events, {report.dropped_log_records} log "
              f"records and {report.dropped_resources} resources scrubbed)")  # fmt: skip
    if rows:
        try:
            existing = load_answer_keys(args.dataset, root)
        except ArtifactMissing:
            existing = {}
        merged = {**existing, **{r.case_id: r for r in rows}}
        path, digest = write_answer_keys(args.dataset, sorted(merged.values(), key=lambda r: r.case_id), root)
        print(f"package: {len(merged)} answer keys in {path} (sha256 {digest[:12]})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
