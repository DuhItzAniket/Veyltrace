"""RQ5 AI-path cost from the recorded model time of the kept runs (H5; #545).

Usage: `uv run --no-project python scripts/rq5_ai_cost.py --runs-root DIR [--results bench/results]`

Why: H5 bounds what the AI path adds (`brief` ≤ 180 s p95, 04 §2). `re2-oracle-rq2-v1` scored its
brief rows by replaying the recordings, so their `wall_ms` and tokens are empty and its
`summary.json` has no AI cost. The recorded cost is in each kept run's `proposals.json`
`budget_used` (08 §3): `wall_ms` is the sum of the recorded call latencies, plus tokens and turns.
The runs are exactly the Tier 1 runs of the committed recording replay
(`replay/recording/replay.csv`), so this file and RQ6 count the same 801 runs.

Writes `<results>/rq5-ai-cost/<experiment>.csv` (one row per run, sorted) and `summary.json`
(per system: n, and the nearest-rank p50 and p95 of each column, the rule of 03 §13.3). Narration
adds nothing here: every checked R-16 card is template-narrated, with no model call (#520).
Only the standard library is used, so the script runs without `uv sync`.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path

EXPERIMENT = "re2-oracle-rq2-v1"  # the only experiment with recorded AI runs in v1.0 (#533)
KEPT = "bench-ai"  # veyltrace_bench.ai_arms.KEPT
COLUMNS = ("model_wall_ms", "tokens_in", "tokens_out", "turns")
PERCENTILES = (50, 95)


def nearest_rank(values: Sequence[float], p: int) -> float | None:
    """The p-th percentile by nearest rank, the ceil(p*n/100)-th smallest (03 §13.3)."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p * len(ordered) / 100)) - 1]


def runs(results: Path) -> list[dict[str, str]]:
    """The Tier 1 runs of the recording replay that came from `EXPERIMENT`."""
    path = results / "replay" / "recording" / "replay.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["tier"] == "1" and EXPERIMENT in r["experiments"]]
    return sorted(rows, key=lambda r: (r["dataset"], r["case_id"], int(r["seed"]), r["run_id"]))


def cost_row(run: dict[str, str], runs_root: Path) -> dict[str, object]:
    """One output row: the run's identity and its proposals.json budget_used."""
    proposals = runs_root / KEPT / run["dataset"] / run["case_id"] / run["run_id"] / "proposals.json"
    doc = json.loads(proposals.read_text(encoding="utf-8"))
    used = doc.get("budget_used") or {}
    return {
        "dataset": run["dataset"],
        "system": run["system"],
        "case_id": run["case_id"],
        "seed": int(run["seed"]),
        "run_id": run["run_id"],
        "status": doc.get("status"),
        "model_wall_ms": round(float(used.get("wall_ms", 0.0)), 1),
        "tokens_in": int(used.get("tokens_in", 0)),
        "tokens_out": int(used.get("tokens_out", 0)),
        "turns": int(used.get("turns", 0)),
    }


def summarise(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    """Per system: n, statuses, and the p50/p95 of each cost column."""
    out: dict[str, object] = {}
    for system in sorted({str(r["system"]) for r in rows}):
        mine = [r for r in rows if r["system"] == system]
        entry: dict[str, object] = {"n": len(mine)}
        statuses: dict[str, int] = {}
        for r in mine:
            statuses[str(r["status"])] = statuses.get(str(r["status"]), 0) + 1
        entry["status"] = dict(sorted(statuses.items()))
        for column in COLUMNS:
            values = [float(str(r[column])) for r in mine]
            for p in PERCENTILES:
                entry[f"{column}_p{p}"] = nearest_rank(values, p)
        out[system] = entry
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rq5_ai_cost.py", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--runs-root", type=Path, required=True, help="the runs root that holds bench-ai/")
    ap.add_argument("--results", type=Path, default=Path("bench/results"), help="results root")
    args = ap.parse_args(argv)
    chosen = runs(args.results)
    if not chosen:
        print(f"rq5: no Tier 1 runs of {EXPERIMENT} in the recording replay", file=sys.stderr)
        return 2
    rows = [cost_row(r, args.runs_root) for r in chosen]
    out = args.results / "rq5-ai-cost"
    out.mkdir(parents=True, exist_ok=True)
    header = ["dataset", "system", "case_id", "seed", "run_id", "status", *COLUMNS]
    with (out / f"{EXPERIMENT}.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "experiment_id": EXPERIMENT,
        "source": "replay/recording/replay.csv tier 1",
        "systems": summarise(rows),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"rq5: {len(rows)} runs -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
