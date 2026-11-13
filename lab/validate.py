"""Apply the 05 §8.2 validation rule to raw captures and record the result in their answer keys.

    uv run python lab/validate.py                      # every capture with an answer key
    uv run python lab/validate.py --captures DIR [ID ...]

New cases are validated by ``lab/campaign.py`` at export; this command (re)validates older ones,
for example after the rule's parameters change.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from vlab import CAPTURES_DIR, answer_key
from vlab.validate import validate_capture


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab/validate.py", description=__doc__.splitlines()[0])
    ap.add_argument("ids", nargs="*", help="capture ids (default: all with an answer key)")
    ap.add_argument("--captures", type=Path, default=CAPTURES_DIR)
    args = ap.parse_args(argv)
    keys_dir = args.captures / answer_key.ANSWER_KEYS
    ids = args.ids or sorted(p.stem for p in keys_dir.glob("*.json"))
    if not ids:
        print(f"validate: no answer keys under {keys_dir}", file=sys.stderr)
        return 1
    kept = 0
    for capture_id in ids:
        key = json.loads((keys_dir / f"{capture_id}.json").read_text(encoding="utf-8"))
        result = validate_capture(args.captures / capture_id, key)
        key = {c: key.get(c) for c in answer_key.COLUMNS}  # older keys may lack columns
        key["validated"], key["sli_impact_json"] = result.validated, result.sli_impact_json
        answer_key.write(key, capture_id=capture_id, captures_dir=args.captures)
        kept += result.validated
        print(
            f"{capture_id}  {key['fault_label']:4s} {key['root_service'] or '-'!s:22s} "
            f"{'KEEP' if result.validated else 'drop'}  {result.reason}"
        )
    print(f"validate: {kept} of {len(ids)} validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
