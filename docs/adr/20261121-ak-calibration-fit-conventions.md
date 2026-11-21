# Bench's calibration fits score never-NO_FAULT windows and unranked roots as +∞, and check reused files

- **Status:** Accepted (manager decisions on the R-13 review, 2026-11-21; the lead delegated design)
- **Date:** 2026-11-21
- **Author:** Aniket Kumar (AK)
- **Deciders:** the lead (decisions relayed by the manager session)
- **Consulted:** Reason (R-12 Causentra v2 session); none outside the lane (no contract change)
- **Issue / CCR:** #38 (R-13), sub-issues #375, #391, #376, #393; R-12 acceptance #37
- **Supersedes:** none · **Superseded by:** none

## Context

Bench fits Causentra's conformal threshold q̂ and its `NO_FAULT` threshold τ_nf (R-13; [04 §5.4](../04-evaluation-protocol.md), [09 §3.7–§3.8](../engines/09-causentra.md)). 09 fixes the rank indexes but not what a calibration run that cannot produce a score contributes. The review of the R-13 stack (#382–#402) found that the first implementation dropped such windows from m: failed or timed-out runs, windows whose M is undefined (no robust_z atom), and it entered windows with a silent service at their M. At test time Causentra never declares any of the three `NO_FAULT` (09 §3.8: a silent service rules it out, and M must exist), so they are always false alarms; leaving them out of m, or in at a finite M, lets the held-out false-alarm rate exceed β + 0.05 (R-12's acceptance, #37) even when the fit is right. The same question exists for q̂ (an unranked run) and for experiments that reuse files fitted earlier (`calibration.fit: false`, 04 §5.4 item 4).

## Decision drivers

- The fit must match the decision rule it calibrates, so the finite-sample guarantee holds for the windows Causentra actually sees.
- No contract change: `calibration` 1.0 has no field for excluded runs ([03 §12.1](../03-contracts.md)).
- A held-out prediction must never use a file fitted on its own cluster, even when the file comes from another experiment.

## Considered options

1. **Drop runs without a score** (the first implementation).
2. **Score them +∞ and keep them in n and m** (as 09 §3.7 already does for a root outside the decision pool).
3. **Fail the experiment** when any calibration run lacks a score.

## Decision

We choose **option 2**:

- **τ_nf.** A normal window that Causentra could never declare `NO_FAULT` — a failed or timed-out run, M undefined, or any silent service — scores +∞ and stays in m (04 §5.4 item 6 counts m over the fold's normal windows). τ_nf is the ⌈(m + 1)(1 − β)⌉-th smallest; when that index exceeds m **or lands on +∞**, τ_nf = `no_fault.default_tau` (log1p(3.0)) and `calibrated = false`, the same fallback as below 9 windows. Bench logs the +∞ counts per fit (`n_failed`, `n_no_m`, `n_silent`) next to the fit and the held-out rates.
- **q̂.** A fault-case calibration run that failed, wrote no verdict, or is **unranked** (no ranker scored any candidate; a miss in every metric, 04 §7) scores +∞, like a root outside the pool.
- **Reused files.** With `fit: false` bench loads every file a held-out run needs and requires its `split.seed`, α and β to equal the experiment's, then loads the fitting experiment (`bench/experiments/<content.experiment_id>.yaml`), recomputes its fold plan and requires each test case's cluster to be in that plan and outside the file's fit. Any mismatch is a ConfigError before the first run.
- **Timeouts of held-out runs.** A held-out run restarts from Causentra on its calibration run. Each run is judged against `resources.timeout_s` on its own and the worse outcome is kept; the row's `wall_ms` is the sum of both runs, the cost of the held-out prediction. RQ5 cost numbers come from the solo `veyltrace:off` run of `re2-oracle-rq1-v1`, not from these rows.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Drop runs without a score | simple | biases τ_nf downward relative to the rule at test time; the reported false-alarm rate can exceed β + 0.05 with a correct fit | breaks R-12's acceptance by construction |
| Fail the experiment | no convention needed | one bad window stops a 20-hour run | not proportionate; +∞ is the conservative score |

## Consequences

- **Positive:** the fit and Causentra's rule agree, so held-out coverage and false-alarm rates measure the method, not a bookkeeping gap; reused files cannot leak a fold.
- **Negative / costs:** many windows without M or with silent services push τ_nf to the uncalibrated default (`calibrated = false`), which the results then report.
- **Follow-ups:** a one-line pointer in [09 §3.8](../engines/09-causentra.md); 04 is frozen and unchanged.

## Confirmation

`bench/tests/test_calibration_fit.py` (+∞ windows in m, the +∞ index fallback, unranked roots), `bench/tests/test_calibrated_runs.py` (a reused file whose fitting plan lacks a cluster is refused), and R-12's acceptance numbers from `bench.held_out` on RE2.

## Evidence

- [04 §5.4](../04-evaluation-protocol.md) items 4–6; [09 §3.7–§3.8](../engines/09-causentra.md); `veyltrace_causentra.outcome.no_fault` (the decision rule).
