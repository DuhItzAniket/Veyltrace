"""Convert every fetched case of RCAEval suites through the `rcaeval` adapter (O-01 acceptance).

Usage: `uv run python scripts/observe/ingest_check.py re2-ob re2-ss re2-tt [--expect-cases 90]
[--budget-s 10]`

For each case of each suite's private index under `${VEYLTRACE_DATA}`: resolve and convert it (no
cache), encode the tables against their contracts, and record the time, row counts and sources.
The time covers resolve, convert and encode, so it is an upper bound on the 01 §3.1 convert time.
Prints one line per suite and every failure; exits 1 if any case fails or exceeds the budget, if a
suite has no fetched case, or if `--expect-cases` is given and a suite has another number (O-01:
"all RE2 cases ingest; ≤ 10 s/case"; RE2 has 90 cases per system). Case ids only: the canonical
names stay inside the adapter.
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


def check_suite(suite: str, budget_s: float, expect: int | None = None) -> list[str]:
    """Convert every case of `suite`; returns the failure lines (empty when all pass). A suite
    with no fetched case fails, so the check never passes on missing data."""
    cfg = resolve_config({}, ai_mode="off").engine("infralume")
    adapter, root = RcaevalAdapter(), data_root()
    ids = adapter.list_cases(suite, root)
    if not ids:
        print(f"{suite}: 0 cases")
        return [f"{suite}: no fetched case (run `veyltrace data fetch rcaeval --suite {suite}` first)"]
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
    if expect is not None and len(ids) != expect:
        failures.append(f"{suite}: {len(ids)} cases fetched, expected {expect}")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert every fetched case of RCAEval suites (O-01 check).")
    parser.add_argument("suites", nargs="+", help="RCAEval suites, e.g. re2-ob re2-ss re2-tt")
    parser.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S)
    parser.add_argument("--expect-cases", type=int, default=None, help="cases each suite must have (RE2: 90)")
    args = parser.parse_args(argv)
    failures = [
        line for suite in args.suites for line in check_suite(suite, args.budget_s, args.expect_cases)
    ]
    for line in failures:
        print(f"FAIL {line}", file=sys.stderr)
    print("OK ingest" if not failures else f"FAIL ingest ({len(failures)} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
