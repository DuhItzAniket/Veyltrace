# bench_summary gets the cost metric as an additive 0.2, before the contracts-1.0 bump

- **Status:** Proposed
- **Date:** 2026-11-18
- **Author:** Aniket Kumar (AK)
- **Deciders:** the lead (decision relayed by the manager session, 18 Nov 2026)
- **Consulted:** Observe (O-14 `bench/stats` reads `summary.json`), Explain (none)
- **Issue / CCR:** #316 (CCR), #319 (per-contract series); ADR contracts-1-0-freeze (#306) step 3
- **Supersedes:** none · **Superseded by:** none

## Context

04 §9 lists `cost` among the experiment metrics, and 04 §2 RQ5 / H5 reports p50 and p95 of wall time and peak RSS per case (deterministic p95 ≤ 30 s and ≤ 3 GB; the AI-path budgets of 02 §9). 04 §10.2 requires every paper number to come from `summary.json`. All 55 pre-registered experiments list `cost` (frozen at `prereg-v1`). Until now `bench_summary` had no `cost` entry (`metrics` is `additionalProperties: false`), so the runner skipped it with a logged note. `per_case.csv` has the per-row values (`wall_ms`, `peak_rss_mb`, `tokens_in`, `tokens_out`, 03 §13.2) but no aggregate.

ADR contracts-1-0-freeze orders this change as its own `0.x` PR (step 3), before the mechanical 1.0 bump (step 4) and before R-11. `bench_summary`'s schema and code are not in the `prereg-v1` frozen set; 04 is, and it needs no edit.

## Decision drivers

- R-11's `summary.json` must hold the RQ5 numbers 04 pre-registered.
- The change must be additive, so the committed R-05 `summary.json` (written at 0.1.0, released with the paper) stays valid and readable.
- Percentiles must not depend on row order (bench's determinism rule for summaries).

## Considered options

1. **Additive minor bump of `bench_summary` alone (0.1 → 0.2)**, which needs a per-contract series in the generator (#319) and the older-minor reader rule (`ALLOW_OLDER_MINOR`).
2. **Patch-level change at 0.1.x:** the reader accepts the same minor, but the old file lacks the new required entry, so the R-05 summary no longer validates.
3. **Wait for contracts-1.0:** R-11 would run without the cost entry, and step 4 would carry a field change.

## Decision

We choose **option 1**, because it is additive, keeps the committed 0.1 summary readable (with `cost` null), and leaves step 4 mechanical.

- `bench_summary` 0.2.0: `summary_group.metrics.cost` is required and nullable (null when the experiment does not list `cost`). When listed it holds exactly `wall_ms_p50`, `wall_ms_p95`, `peak_rss_mb_p50`, `peak_rss_mb_p95`, `tokens_in_p50`, `tokens_in_p95`, `tokens_out_p50`, `tokens_out_p95` (each nullable: null when no row of the group has that value) and `n_cost` (rows with a `wall_ms`). Its references to `common` are absolute 0.1 `$id`s (CONVENTIONS §1, #319).
- Percentiles are nearest-rank: the ⌈p·n/100⌉-th smallest of n values (03 §13.3). The result is one of the observed values and order-free. p50 and p95 because H5 and the 02 §9 budgets are p95s, and p50 is the typical case (*a priori*).
- `veyltrace_bench.summary` computes the entry from the run's cost columns, which the runner copies onto each case score. The `bench.metric_skipped` path is removed.
- The committed `bench/results/re2-oracle-baselines-r05/summary.json` is not regenerated. It reads under 0.2 as an older minor (`ALLOW_OLDER_MINOR`, on since #319) with `cost` null, and a test checks that.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| 2. Patch at 0.1.x | no generator change | the committed R-05 summary stops validating; it cannot be rebuilt from `per_case.csv` (Chance@k needs the run directories' service lists) | breaks a released result |
| 3. Wait for 1.0 | one bump | R-11 has no RQ5 numbers in `summary.json`; step 4 is no longer mechanical | contradicts ADR contracts-1-0-freeze steps 3–4 |

## Consequences

- **Positive:** RQ5 numbers come from `summary.json` like every other metric. The per-contract series (#319) also serves every one-contract minor bump after 1.0.
- **Negative / costs:** `bench_summary` is at 0.2 while every other contract is at 0.1 until step 4. Per-stage times (04 §7 "per stage") stay in the run directories, because `per_case.csv` has no per-stage column.
- **Follow-ups:** step 4 moves `bench_summary` to 1.0 with the rest. O-14 reads `metrics.cost` like any other entry.

## Confirmation

`bench/tests/test_cost.py` covers nearest-rank values on a handmade group, the all-null case, `n_cost`, order invariance (hypothesis) and the R-05 0.1 summary reading with `cost` null. `gen_contracts.py --check` passes, and the R-11 `summary.json` has non-null `wall_ms_p95` per group.

## Evidence

- [04 §2 RQ5, §7 Cost, §9](../04-evaluation-protocol.md); [03 §13.2–13.3](../03-contracts.md); [02 §9](../02-architecture.md) budgets.
- CCR #316; ADR [contracts-1-0-freeze](20261116-ak-contracts-1-0-freeze.md); #319.
