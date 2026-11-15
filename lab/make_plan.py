"""Write one laptop's plan for one night of the collection grid (X-11; 05 §6, §8.3).

    uv run python lab/make_plan.py --seed 20261116 --laptops 3 --laptop 1 --night 1 \\
        --out lab/captures/night-1.yaml
    uv run python lab/campaign.py --plan lab/captures/night-1.yaml

Every laptop runs this with the same seed and its own ``--laptop`` number, so shares never overlap.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import yaml
from vlab.plan import parse
from vlab.plan_gen import PER_NIGHT, grid, night, plan_document, share


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab/make_plan.py", description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--laptops", type=int, default=3)
    ap.add_argument("--laptop", type=int, required=True, help="this laptop's number, 1..laptops")
    ap.add_argument("--night", type=int, required=True, help="1-based")
    ap.add_argument("--per-night", type=int, default=PER_NIGHT)
    ap.add_argument("--out", type=Path, help="default: print to stdout")
    args = ap.parse_args(argv)
    full = grid(args.seed)
    mine = share(full, laptops=args.laptops, laptop=args.laptop)
    entries = night(mine, night=args.night, per_night=args.per_night)
    if not entries:
        print(
            f"make_plan: night {args.night} is past the end of this laptop's {len(mine)} cases",
            file=sys.stderr,
        )
        return 1
    doc = plan_document(entries, seed=args.seed)
    parse(doc)  # the campaign will accept it
    text = yaml.safe_dump(doc, sort_keys=False)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    faults = Counter(e["fault"] for e in entries)
    nights = -(-len(mine) // args.per_night)
    print(
        f"make_plan: grid {len(full)} cases; laptop {args.laptop}/{args.laptops} has {len(mine)} "
        f"({nights} nights); night {args.night}: {len(entries)} cases {dict(sorted(faults.items()))}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
