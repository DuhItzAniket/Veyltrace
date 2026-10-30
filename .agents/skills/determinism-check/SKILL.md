---
name: determinism-check
description: Run and debug the Veyltrace determinism gate (pipeline run twice, all output hashes must match). Use after any change to engines 1-7, 9 or the deterministic parts of 10, and whenever the determinism CI job fails.
---

# Determinism check

Rules: `AGENTS.md` §4.4 and `docs/02-architecture.md` §9. The gate runs the pipeline twice on
`synth-01` and one small real case; every output hash must match.

1. **Run it:** `uv run python scripts/check.py --determinism`. Paste the summary in the PR.
2. **If hashes differ**, find the first artifact that differs (pipeline order: infralume →
   core alert step (`alert.json`) → signalyth → anomara → causync → causalith → faultloom →
   causatrix → relentra → faultloom claim pass → causentra → causivra) and diff the two runs' files for that engine. Fix the earliest one first.
3. **Usual causes**, in the order to check:
   - iteration over a `set`, `dict` built from a set, `glob`/`os.listdir`/`Path.iterdir` without `sorted(...)`
   - output not sorted by the contract's declared key before writing (use the contract writers)
   - wall-clock reads (`time.time`, `datetime.now`, file mtimes) in analysis code
   - `random`/`numpy.random` not seeded through `veyltrace_core.rng(case_id, purpose)`
   - floats serialised by hand instead of `canonical_json` (rounding to 9 decimals, NaN → null)
   - multithreaded reductions (DuckDB threads, numpy/BLAS), parallel map with unordered results
   - environment leakage: hostnames, absolute paths, usernames, env vars in artifacts
4. **Fix the cause in your lane.** If the first differing artifact is produced by another lane,
   open an issue for that lane with the two hashes and the diff; do not patch their package.
5. **Never** make the gate pass by excluding a file from hashing, loosening tolerance, or
   re-running until it passes once. A flaky determinism result is a bug.
