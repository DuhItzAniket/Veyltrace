# bench_summary 1.1 holds the 04 §8 statistics and the decoy_ranked_first entry

- **Status:** Accepted (lead, on #357, 2026-11-21)
- **Date:** 2026-11-21
- **Author:** Aniket Kumar (AK)
- **Deciders:** the lead (decisions relayed by the manager session, 21 Nov 2026)
- **Consulted:** Observe (O-14 `bench/stats` computes the values; review requested), Explain (none)
- **Issue / CCR:** #357; #350 (`bench/stats`), #331 review (the decoy entry deferred to the first post-1.0 minor)
- **Supersedes:** none · **Superseded by:** none

## Context

[04 §8](../04-evaluation-protocol.md) pre-registers the statistics of every table:
- a 95% percentile cluster-bootstrap interval for every metric and every paired difference, with clusters (system, root service, fault), 2,000 resamples, seeded;
- the cluster sign-flip test as the primary test, and exact McNemar as the secondary;
- Holm within the families `rq1` and `rq2`, and non-inferiority by the unadjusted CI.

04 §10.2 requires every paper number to come from `summary.json`. In 1.0, `bench_summary.statistics` is a string, "not run: …" ([03 §13.3](../03-contracts.md)), so none of these numbers has a place. `bench/stats` (`veyltrace_stats`, #350) now computes them.

The RCAEval-C experiments list `decoy_ranked_first` (H4c). `per_case.csv` has `decoy_present` and `decoy_ranked_first` since #326, but `summary.json` has no aggregate. The lead deferred this entry from the #331 review to the first minor after the freeze.

R-11's M2 table must come from one runner invocation at one commit, so that its manifest is the whole provenance (lead, 21 Nov). Rewriting `summary.json` later from `per_case.csv` is ruled out, and the shape must exist before R-11 runs.

## Decision drivers

- Every 04 §8 number for R-11 comes from the same `summary.json` as the metrics.
- The change must be additive, so the 1.0 files on main keep reading (older-minor rule, 03 §1).
- Families, margins and seeds must come from the frozen experiment YAMLs and 04, with nothing new chosen.
- Results must not depend on row order (bench's summary rule).

## Considered options

1. **One additive minor, `bench_summary` 1.0 → 1.1.** `statistics` widens to `object | "not run: …"`, and `metrics.decoy_ranked_first` is added as required and nullable.
2. **A separate `bench_statistics` contract** (`statistics.json` next to `summary.json`).
3. **Keep the string and compute statistics in the table generator** from `per_case.csv`.

## Decision

We choose **option 1**. It is additive: a 1.0 file reads with its string kept and `decoy_ranked_first` null. It also keeps one `summary.json` per experiment as the only table source.

- **`bench_summary` 1.1.0**, its own series (#319). `$id …/schemas/1.1/…`, with absolute references to the 1.0 `common`. All other contracts stay at 1.0.
- **`statistics`** is `summary_statistics` or a string matching `^not run: `. The object holds:
  - `params`: `level`, `resamples`, `bootstrap_seed`, `flips` and `permutation_seed`, from the experiment's `statistics.bootstrap` / `.permutation`; and `cluster_by` = `system/root_service/fault`.
  - `intervals[]`, one per (dataset, system or pooled, method, case-mean metric).
  - `comparisons[]`, one per paired difference, with `kind` ∈ {noninferiority, superiority, exploratory}, `family`, `margin`, `n_pairs`, `n_clusters`, the difference with its interval, `sign_flip_p`, the McNemar counts and p, and `holm_p`.
  - `not_run[]` of `{scope, reason}`.

  Field semantics and sort keys are in 03 §13.3.
- **Case-mean metrics only get intervals:** the enum `summary_case_metric`. Ratios (`lift_at_k`, `rerank_at_1`) are not means over cases, so the cluster bootstrap of a mean does not apply; cost percentiles and onset medians don't either. None of the three is listed.
- **Families and margins** come from the frozen YAMLs, and they agree with 04 §2 / §8:
  - `re2-oracle-rq1-v1`: `holm_family: rq1`, with non-inferiority vs the best of `rcaeval:nsigma`, `rcaeval:baro`, `simplerca`.
  - `re2-oracle-rq2-v1`: `holm_family: rq2`, with non-inferiority vs `veyltrace:off`.
  - Every other experiment: `holm_family: null`.
  - No YAML has a margin key. 04 §2 states H1a and H2a as "CI not entirely below 0", so `margin` is 0 for both.
- **`decoy_ranked_first`** is `{decoy_ranked_first, n_decoy}`: the share of the group's rows with `decoy_present` whose `decoy_ranked_first` is true (04 §7 Decoy metrics), null when there are none.
- **This PR ships the schema only.** The runner writes `decoy_ranked_first: null` and keeps the "not run" string. An experiment that lists `decoy_ranked_first` is still refused by `unsupported()`. The wiring PR computes both, and adds `stats/veyltrace_stats` to the bench wheel.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| 2. `bench_statistics` contract | 1.0 `bench_summary` untouched | a second table source, and `bench_manifest` would need to list it | 04 §10.2 and R-17 name `summary.json` as the one source |
| 3. Statistics in the table generator | no contract change | the numbers are not in a validated, committed artifact, and R-11's provenance splits across two invocations | contradicts the lead's one-invocation rule |

## Consequences

- **Positive:** R-11 and every later table carry their CIs and tests in the same validated file as the metrics. The 1.0 files stay valid.
- **Negative / costs:** `bench_summary` is the only contract at 1.1. The pretty-printed schema grows by about 430 lines.
- **Follow-ups:**
  - the wiring PR (statistics in the runner, the decoy entry, the wheel);
  - the system-stratified pooled bootstrap and the exact binomial CI (Observe, O-14 follow-ups). Until they land, the pooled intervals are listed in `not_run`, and unstratified pooling is never used.

## Confirmation

- `bench/tests/test_summary_statistics_contract.py` covers:
  - a 1.0 file reading under 1.1, with its string kept and `decoy_ranked_first` null;
  - a statistics object with a comparison and a decoy entry validating;
  - bad comparisons being refused: an unknown kind, a ratio metric, or a p > 1;
  - a string that doesn't say "not run" being refused.
- `gen_contracts.py --check` passes.
- R-11's `summary.json` has a non-empty `intervals` list per RE2 system.

## Evidence

- [04 §2, §7, §8, §10.2](../04-evaluation-protocol.md); [03 §1, §13.3](../03-contracts.md).
- CCR #357; #350; #331 review; ADRs [bench-summary-cost](20261118-ak-bench-summary-cost.md) and [contracts-1-0-freeze](20261116-ak-contracts-1-0-freeze.md).
