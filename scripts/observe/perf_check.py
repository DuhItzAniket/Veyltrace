"""Time and peak memory of the pipeline per case, AI off (O-11 acceptance; 04 §2 H5).

Usage: `uv run python scripts/observe/perf_check.py re2-ob re2-ss re2-tt [--cases N]
[--budget-s 30] [--budget-mb 3072] [--runs-root DIR] [--passes N] [--out FILE.csv]`

Why: H5 asks for p95 ≤ 30 s and ≤ 3 GB peak RSS per RE2 case on the slowest laptop, and O-11 is
"measured on the slowest laptop". Each case runs in its own child process, so its peak resident
set size is that case's alone. The child reports the pipeline's wall time per step
(`RunSummary.wall_ms`, never written to an artefact) and its peak RSS, measured as bench measures
it. Per dataset the script prints the median and p95 of the total, the largest peak, and the median
time of each step, then the machine. It exits 1 if a p95 or a peak is over budget, or a case fails.

Runs go to a temporary directory unless `--runs-root` is given, so every case is executed, never
reused. The first pass over a dataset also converts the raw files (Infralume's cache is cold);
`--passes 2` runs everything twice, and the last pass is the one that decides the exit code and the
one to report for the bench path, where the cache is filled first. `--out` writes one row per case
and pass (case, system, pass, outcome, wall_ms, peak_rss_mb, then one column per step), so a run
can be committed and cited (lead's decision on #36). Case ids only: canonical names stay inside
the adapters.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

BUDGET_S = 30.0  # 04 §2 H5 / SC-1: deterministic p95 per RE2 case
BUDGET_MB = 3072.0  # 04 §2 H5 / SC-8: 3 GB peak RSS
P95 = 0.95
THREAD_PINS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")  # as check.py pins them


def run_one(dataset: str, case: str, runs_root: Path) -> dict[str, object]:
    """Run one case in this process: outcome, total and per-step seconds, peak RSS in MiB."""
    from veyltrace_bench.child import peak_rss_mb
    from veyltrace_core.pipeline import run_case

    start = time.perf_counter()
    summary = run_case(dataset, case, "off", runs_root=runs_root)
    total = time.perf_counter() - start
    steps = {name: ms / 1000.0 for name, ms in summary.wall_ms.items()}
    return {
        "case": case,
        "outcome": summary.outcome,
        "total_s": total,
        "steps_s": steps,
        "peak_mb": peak_rss_mb(),
    }


def quantile(values: Sequence[float], q: float) -> float:
    """The smallest value with at least a share `q` of the values at or below it (nearest rank)."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def summarise(rows: Sequence[dict[str, object]], budget_s: float, budget_mb: float) -> tuple[list[str], bool]:
    """Report lines for one dataset's rows, and whether it is within both budgets with no failure."""
    done = [r for r in rows if r.get("outcome") == "ok"]
    failed = sorted(str(r["case"]) for r in rows if r.get("outcome") != "ok")
    if not done:
        return [f"  no case finished ok; failed: {', '.join(failed) or 'none run'}"], False
    totals = [float(str(r["total_s"])) for r in done]
    peaks = [float(str(r["peak_mb"])) for r in done]
    p95, peak = quantile(totals, P95), max(peaks)
    names: list[str] = []
    for r in done:
        names += [n for n in dict(r["steps_s"]) if n not in names]  # type: ignore[call-overload]  # JSON row
    steps = {n: statistics.median(float(dict(r["steps_s"]).get(n, 0.0)) for r in done) for n in names}  # type: ignore[call-overload]
    top = sorted(steps.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
    lines = [
        f"  cases {len(done)} ok, {len(failed)} not ok{': ' + ', '.join(failed) if failed else ''}",
        f"  total  median {statistics.median(totals):6.1f} s   p95 {p95:6.1f} s   max {max(totals):6.1f} s"
        f"   (budget {budget_s:g} s)",
        f"  peak RSS  median {statistics.median(peaks):6.0f} MiB   max {peak:6.0f} MiB"
        f"   (budget {budget_mb:g} MiB)",
        "  slowest steps (median s): " + ", ".join(f"{n} {s:.1f}" for n, s in top),
    ]
    return lines, not failed and p95 <= budget_s and peak <= budget_mb


def csv_rows(rows: Sequence[dict[str, object]]) -> tuple[list[str], list[list[object]]]:
    """The header and the rows of the per-case CSV: one row per (system, pass, case), sorted; times
    in ms rounded to 0.1, peak RSS in MiB as measured; a case that did not finish has empty cells."""
    steps = sorted({name for r in rows for name in dict(r.get("steps_s") or {})})  # type: ignore[call-overload]  # JSON row
    header = ["case", "system", "pass", "outcome", "wall_ms", "peak_rss_mb", *(f"{n}_ms" for n in steps)]
    out: list[list[object]] = []
    for r in sorted(rows, key=lambda r: (str(r["system"]), int(str(r["pass"])), str(r["case"]))):
        done = "total_s" in r
        per_step = dict(r.get("steps_s") or {})  # type: ignore[call-overload]  # JSON row
        out.append([
            r["case"], r["system"], r["pass"], r.get("outcome"),
            round(float(str(r["total_s"])) * 1000.0, 1) if done else "",
            round(float(str(r["peak_mb"])), 1) if done else "",
            *(round(float(per_step[n]) * 1000.0, 1) if n in per_step else "" for n in steps),
        ])  # fmt: skip
    return header, out


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Pipeline time and peak memory per case (O-11).")
    parser.add_argument("datasets", nargs="*", help="dataset ids, e.g. re2-ob re2-ss re2-tt")
    parser.add_argument("--cases", type=int, default=None, help="only the first N case ids of each dataset")
    parser.add_argument("--budget-s", type=float, default=BUDGET_S)
    parser.add_argument("--budget-mb", type=float, default=BUDGET_MB)
    parser.add_argument("--runs-root", type=Path, default=None)
    parser.add_argument(
        "--passes", type=int, default=1, help="run every case this many times; the last pass decides"
    )
    parser.add_argument("--out", type=Path, default=None, help="write one CSV row per case and pass")
    parser.add_argument("--one", nargs=3, metavar=("DATASET", "CASE", "RUNS"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.one:  # the child: one case, one JSON line
        dataset, case, runs = args.one
        print(json.dumps(run_one(dataset, case, Path(runs))))
        return 0
    if not args.datasets:
        parser.error("name at least one dataset")
    if args.passes < 1:
        parser.error("--passes must be at least 1")
    from veyltrace_core.adapters import adapter_for
    from veyltrace_core.config import data_root

    env = {**os.environ, **{v: os.environ.get(v, "1") for v in THREAD_PINS}}
    within = True
    every: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="veyltrace-perf-") as tmp:
        base = args.runs_root if args.runs_root is not None else Path(tmp)
        for number in range(1, args.passes + 1):
            # A pass of its own directory, so the second pass executes every case again.
            runs_root = base if args.passes == 1 else base / f"pass-{number}"
            within = True  # the last pass decides
            if args.passes > 1:
                print(f"pass {number} of {args.passes}")
            for dataset in args.datasets:
                cases = sorted(adapter_for(dataset).list_cases(dataset, data_root()))[: args.cases]
                rows: list[dict[str, object]] = []
                for case in cases:
                    cmd = [sys.executable, __file__, "--one", dataset, case, str(runs_root)]
                    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
                    line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.startswith("{")), None)
                    rows.append(
                        json.loads(line) if line else {"case": case, "outcome": f"exit {proc.returncode}"}
                    )
                every += [{**r, "system": dataset, "pass": number} for r in rows]
                lines, ok = summarise(rows, args.budget_s, args.budget_mb)
                within = within and ok and bool(cases)
                print(f"{dataset}: {'WITHIN' if ok and cases else 'OVER'} budget")
                print("\n".join(lines if cases else ["  no fetched case"]))
    if args.out is not None:
        header, table = csv_rows(every)
        with args.out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(table)
    cpus, python = os.cpu_count(), platform.python_version()
    print(f"machine: {platform.platform()}, {platform.machine()}, {cpus} logical CPUs, Python {python}")
    return 0 if within else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
