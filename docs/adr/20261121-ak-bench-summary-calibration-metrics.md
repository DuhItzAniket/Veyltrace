# bench_summary 1.2 holds the calibration and RQ2 metric entries, and bench_manifest 1.1 the calibration files

- **Status:** Proposed (approved as drafted by the manager for the lead, 21 Nov 2026; the lead accepts on merge)
- **Date:** 2026-11-21
- **Author:** Aniket Kumar (AK)
- **Deciders:** the lead
- **Consulted:** Observe (FYI: O-14 `bench/stats` may add intervals for the proportions later), Explain (none)
- **Issue / CCR:** #404 (CCR), #405 (entries), #412 (manifest calibrations); #37 (R-12 acceptance), #45 (R-16 full matrix)
- **Supersedes:** none · **Superseded by:** none

## Context

The 04 §9 metric vocabulary has seven names with no `bench_summary` entry in 1.1 ([03 §13.3](../03-contracts.md)): `coverage`, `set_size`, `no_fault_rates`, `risk_coverage`, `selective_accuracy`, `decoy_top1_change` and `permutation_invariance`. The runner refuses an experiment that lists any of them (`experiment.METRIC_TASKS`).

Counts on main (3de19401): `coverage` and `set_size` are listed by 41 YAMLs, `no_fault_rates` by 6, `selective_accuracy` by 5, `risk_coverage` by 4, and the two proposal metrics by 1 each. So after the R-13 stack (#373–#376, #391, #393) the runner still refuses 41 pre-registered experiments on their metrics list alone. That covers RQ3, LOSO, onset shift, telemetry ablation, RCAEval-C, and planted and permuted proposals. R-16 (#45) runs the full matrix at the `results-code-v1` freeze (target Tue 24 Nov), so this change is on its critical path.

The per-case inputs already exist in `per_case.csv` (03 §13.2): `fold`, `variant`, `seed`, `status`, `in_set`, `set_size`, `pool_hit`, `hit_at_1` and `verdict_hash`. But [04 §10.2](../04-evaluation-protocol.md) and R-17 take every table number from `summary.json`. R-12's acceptance (#37) is today only the `bench.held_out` log line. `risk_coverage` also needs `verdict.confidence.margin` and the leader's fused score, which no per-case column holds.

The calibration files behind a result are recorded only per run: in `run_manifest.calibration_sha256` and in `config.lock.json`. The bench manifest reaches them only through `runs[].run_id`.

## Decision drivers

- Every RQ3 and RQ2 table number comes from the same validated `summary.json` as the accuracy metrics (04 §10.2).
- The change must be additive, so committed 1.1 summaries and 1.0 manifests keep reading (03 §1 older-minor rule).
- A value never depends on row order, as for every other summary entry.
- A method without the measured channel (no set, no verdict) must not read as 0 or 1.
- The definitions are the frozen 04 §7 ones; nothing new is chosen.

## Considered options

1. **Additive minors: `bench_summary` 1.2 with seven required, nullable entries, and `bench_manifest` 1.1 with a required, nullable `calibrations`.**
2. **Compute the entries in the R-17 table generator** from `per_case.csv`.
3. **A separate `bench_calibration` result file** next to `summary.json`.

## Decision

We choose **option 1**. It keeps one `summary.json` per experiment as the only table source, and a 1.1 file reads under 1.2 with the new entries null.

- **`bench_summary` 1.2.0.** `$id …/schemas/1.2/…`, with absolute references to the 1.0 `common`. Seven new `metrics` entries, each required and nullable (null = not listed):

  | Entry | Keys |
  |---|---|
  | `coverage` | `coverage`, `coverage_gap`, `pool_coverage`, `n_fault`, `by_fold[{fold, coverage, n_fault}]` |
  | `set_size` | `set_size_mean`, `set_size_median`, `singleton_share`, `n_set` |
  | `no_fault_rates` | `false_alarm_rate`, `n_normal`, `wrong_no_fault_rate`, `n_fault`, `no_fault_precision`, `no_fault_recall`, `by_fold[{fold, false_alarm_rate, n_normal}]` |
  | `risk_coverage` | `aurc_verdict`, `aurc_fused`, `n_fault` |
  | `selective_accuracy` | `ac_at_1_confirmed`, `answer_rate_confirmed`, `ac_at_1_likely_or_better`, `answer_rate_likely_or_better`, `n_fault` |
  | `decoy_top1_change` | `decoy_top1_change`, `n_pairs` |
  | `permutation_invariance` | `permutation_invariance`, `n_cases` |

  Definitions and sort keys are in 03 §13.3, following 04 §7. Fault rows are a group's rows with a truth, and normal rows those without. A rate is null when its denominator is 0. `by_fold` lists the folds of the group's rows sorted by `fold`. Rows with a null fold are not held out and are not listed there.
- **`bench_manifest` 1.1.0**: `calibrations` = `[{family_id, sha256, fitted}] | null`, sorted by `family_id`, then `sha256`.
  - It lists every calibration file a recorded run read: its `config.lock.json` `calibration`, read through core io.
  - `fitted` is true when this experiment wrote the file: `calibration.fit` is true and the file's `experiment_id` is the experiment's own.
  - The list is `[]` when no run read a file. It is null when bench did not record the files: in every 1.0 file read as an older minor, and from the schema PR's runner until #412.
- **Clarifications of the approved draft.** The lead delegates design choices; each one below only pins down what the draft left open.
  - *Channel nulls.* Coverage is null when no fault row has a set (baselines, `causatrix:*`). The status-based rates, both AURCs and selective accuracy are null when the group's method has no verdict. This is Retrieval@K's rule, "None for a channel that no row has". A failed veyltrace run keeps its channels, so it stays a miss.
  - *`set_size` is over fault rows* with a set size, not all rows. Normal windows declared NO_FAULT have an empty set by design, and including them would pull H3b's mean set size down. 04 §7 indexes C_i over F, as for coverage.
  - *`selective_accuracy` carries `n_fault`*, the denominator of its answer rates. The draft's own rule gives every flat entry one `n_*` count, but its key list had none.
  - *AURC ties count at their expectation over the tied orders.* Within a tie block of b rows with e errors, the t-th prefix of the block counts t·e/b errors. The value never depends on row order, and it gives no credit for a lucky order inside a tie. Margins and fused scores are compared at 9 decimals, as Causentra rounds them (09 §5).
  - *Top-1 changes and permutations.*
    - A (case, seed) counts for `decoy_top1_change` when it has its unplanted row and at least one `plant-<i>` row. It counts as changed when any planted top-1 (the coarse service of `ranks[0]`) differs; a planted run with no ranks counts as changed.
    - A (case, seed) counts for `permutation_invariance` when it has its unpermuted row and at least one `perm-<i>` row. It is invariant only when every row has a `verdict_hash` and all are equal.
  - *The leader's fused score* is the rank-1 entry of `verdict.ranked`, the verdict's top-1 and its leader whenever one exists (09 §3.6). Rows without one, and failed runs, order last.
  - The draft's `"x-order": "fold"` is written `"x-sort": [{"pointer": "fold", "order": "asc"}]`, because CONVENTIONS §3.4 allows only `"semantic"` for `x-order`.
- **The schema PR ships the schema only.** The runner writes the seven entries and `calibrations` as null. An experiment listing a new metric is still refused by `unsupported()` until the implementation PR.
- **The implementation PR (#405)** computes the entries in `veyltrace_bench.summary`. It adds them to `summary.METRIC_KEYS` and removes them from `experiment.METRIC_TASKS`. It reads the margin and the leader's fused score from each run's verdict. #412 then writes `calibrations` from the recorded runs.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| 2. Compute in the table generator | no contract change | the numbers are not in a validated, committed artefact; `risk_coverage` needs run directories the generator never reads | contradicts 04 §10.2 and R-17's single source |
| 3. A separate `bench_calibration` file | `bench_summary` untouched | a second table source; the manifest must list it; RQ2's proposal metrics would need yet another place | the same objection as for statistics in ADR [bench-summary-statistics](20261121-ak-bench-summary-statistics.md) |

## Consequences

- **Positive.**
  - RQ3 (coverage, set size, NO_FAULT rates, risk–coverage), H4b's selective accuracy and RQ2's H2b/H2c all come from `summary.json`.
  - R-12's acceptance is recorded per fold in a committed artefact.
  - The manifest names every calibration file behind a result.
  - The 41 refused pre-registered experiments become runnable once the implementation PR lands.
- **Negative / costs.**
  - `bench_summary` is at 1.2 and `bench_manifest` at 1.1 while every other contract stays at 1.0.
  - The pretty-printed summary schema grows by about 330 lines.
  - The proportions have no cluster-bootstrap interval yet. 04 §8 asks for one: an O-14 follow-up for `bench/stats`.
- **Follow-ups.**
  - #405 (the entries) and #412 (the manifest calibrations).
  - Intervals for coverage, false-alarm rate and decoy flips (Observe, O-14) need the `summary_case_metric` enum to grow: a later minor.
  - The runner that plants and permutes proposals must name its variants `plant-<i>` and `perm-<i>`, and must also write each case's unperturbed row (variant null) in the same experiment. Otherwise `n_pairs` and `n_cases` stay 0. re2-oracle-planted-v1 describes its baseline as the rows of re2-oracle-rq2-v1, so that runner copies or re-runs them.

## Confirmation

- `bench/tests/test_summary_calibration_contract.py` checks that:
  - a 1.1 summary reads under 1.2 with the seven entries null;
  - a 1.0 manifest reads under 1.1 with `calibrations` null;
  - filled entries and a calibration list validate;
  - out-of-range shares and unsorted folds or calibrations are refused.
- `gen_contracts.py --check` passes.
- After #405: R-16's RQ3 summaries carry a non-null `coverage` entry per group of a verdict method.

## Evidence

- [04 §2 (H2b, H2c, H3a–H3c, H4b), §7, §9, §10.2](../04-evaluation-protocol.md); [03 §1, §12, §13.2–§13.4](../03-contracts.md); [09 §3.6, §3.9](../engines/09-causentra.md).
- CCR #404; ADRs [bench-summary-statistics](20261121-ak-bench-summary-statistics.md), [bench-summary-cost](20261118-ak-bench-summary-cost.md) and [contracts-1-0-freeze](20261116-ak-contracts-1-0-freeze.md).
