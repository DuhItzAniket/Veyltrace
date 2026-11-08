"""Convert every fetched case of RCAEval suites through the `rcaeval` adapter (O-01 acceptance).

Usage: `uv run python scripts/observe/ingest_check.py re2-ob re2-ss re2-tt [--budget-s 10]`

For each case of each suite's private index under `${VEYLTRACE_DATA}`: convert (no cache, so the
time is the convert time of 01 §3.1), check the tables against their contracts, and record the
time, row counts and sources. Prints one line per suite and every failure; exits 1 if any case
fails or exceeds the budget (O-01: "all RE2 cases ingest; ≤ 10 s/case"). Case ids only: the
canonical names stay inside the adapter.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections.abc import Sequence

from veyltrace_core import io
from veyltrace_core.adapters import TELEMETRY_CONTRACTS
from veyltrace_core.config import data_root, resolve_config
from veyltrace_infralume.adapters.rcaeval import RcaevalAdapter
from veyltrace_infralume.cache import full_table

DEFAULT_BUDGET_S = 10.0  # O-01 acceptance criterion


def check_suite(suite: str, budget_s: float) -> list[str]:
    """Convert every case of `suite`; returns the failure lines (empty when all pass)."""
    cfg = resolve_config({}, ai_mode="off").engine("infralume")
    adapter, root = RcaevalAdapter(), data_root()
    ids = adapter.list_cases(suite, root)
    times: list[float] = []
    rows = {source: 0 for source in TELEMETRY_CONTRACTS}
    no_traces = 0
    failures: list[str] = []
    for case_id in ids:
        started = time.perf_counter()
        try:
            case = adapter.convert(adapter.resolve(suite, case_id, root), cfg)
            for source, contract in TELEMETRY_CONTRACTS.items():
                io.encode(contract, full_table(contract, getattr(case.tables, source)))
        except Exception as exc:  # report every case, then fail the run
            failures.append(f"{suite} {case_id}: {type(exc).__name__}: {exc}")
            continue
        elapsed = time.perf_counter() - started
        times.append(elapsed)
        if elapsed > budget_s:
            failures.append(f"{suite} {case_id}: {elapsed:.1f} s > {budget_s:.0f} s")
        for source, table in case.tables.items():
            rows[source] += table.num_rows
        no_traces += not case.sources_present["traces"]
    if times:
        print(
            f"{suite}: {len(ids)} cases, {len(times)} converted, {len(failures)} failed; "
            f"time median {statistics.median(times):.2f} s, max {max(times):.2f} s; "
            f"rows {rows}; cases without traces {no_traces}"
        )
    else:
        print(f"{suite}: {len(ids)} cases, none converted")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert every fetched case of RCAEval suites (O-01 check).")
    parser.add_argument("suites", nargs="+", help="RCAEval suites, e.g. re2-ob re2-ss re2-tt")
    parser.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S)
    args = parser.parse_args(argv)
    failures = [line for suite in args.suites for line in check_suite(suite, args.budget_s)]
    for line in failures:
        print(f"FAIL {line}", file=sys.stderr)
    print("OK ingest" if not failures else f"FAIL ingest ({len(failures)} case(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
