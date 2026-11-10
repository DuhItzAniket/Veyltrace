# Lab validation floors, F14 reference time and the collection grid

- **Status:** Proposed
- **Date:** 2026-11-10
- **Author:** C Lakshanaa (cl)
- **Deciders:** the lead
- **Consulted:** Explain lane
- **Issue / CCR:** #44
- **Supersedes:** none · **Superseded by:** none

## Context

X-11 adds the 05 §8.2 validation rule, no-fault controls and the overnight plan. Three points needed a decision:

1. 05 §8.2 floors the MAD at 1% of the median. Every live baseline so far had error rate 0 in all buckets (nine captures, 2026-11-09/10), so median and MAD are 0 and one failed request in two buckets would count as a breach.
2. F14 has no injection, but the rule aligns buckets to `t_inject`, and the packager's `oracle_alert.json` needs a time.
3. 05 §6 sets the grid (5 services × fault types × 3 repetitions, ≈ 10% no-fault) but not the severity per repetition, and L1 is too weak for some faults: F02 (memory 256 MB) and F07 (one container kill) moved no user-facing SLI on the live run.

## Decision

- **Floors:** `max(MAD, 1% of median, absolute)` with absolute 1 ms for p95 and 0.005 (0.5 percentage points) for error rate; at least 6 baseline buckets (3 min). All a priori. On the nine live captures the rule keeps 7 (F01, F04, F05, F06, F08, F11, F13) and rejects F02 and F07 (`no_impact`), matching the informal check in [ADR 20261109-cl-lab-catalog-packager](20261109-cl-lab-catalog-packager.md).
- **F14:** the case runs every phase without injecting; its key has `is_no_fault = true`, null root columns, and `t_inject_ns` = the time a fault would have started (end of baseline). That time is the oracle hint and the rule's alignment point. It is validated only if no breach occurs.
- **Grid:** severities L1, L2, L1 per repetition; F02 and F07 always L2; the third repetition at 30 users. Five default targets (cart, checkout, currency, frontend, product catalog), F13 on redis-cart, ⌈10%⌉ controls; shuffled from the seed, dealt round-robin to laptops, 24 cases per night (05 §8.3). With today's catalog that is 136 cases, 45–46 per laptop.
- **Validation runs at export** and is recorded in the key (`validated`, `sli_impact_json`) and in `attempts.jsonl` (with `reason` and `t_ns`); `lab/report.py` turns that into the standup count.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Floor only at 1% of the median | literal 05 text | a single error validates any case with a clean baseline | floors keep the rule's intent |
| `t_inject_ns = null` for F14 | no pseudo time | packager and rule need a time; bench needs the oracle hint | reference time is explicit and documented |
| All repetitions at L1 | simplest | F02 and F07 never validate at L1 | measured, not guessed |

## Consequences

- **Positive:** every case has a recorded keep/drop reason; laptops cannot overlap; the standup count comes from the data.
- **Negative / costs:** the floors are untuned; a case with real but tiny impact (< 0.5 points of errors) is dropped.
- **Follow-ups:** the 05 §8.1 p95/error baseline check before capture (now HTTP 200 only); F15 multi-fault and F16 noise cases; decoys; tune the floors once ≈ 50 validated cases exist.

## Confirmation

`uv run python scripts/check.py --package lab` (synthetic SLI tests for breach, single spike, window end, error-only breach, zero-error floor, controls, short baseline) and `uv run python lab/validate.py` on the live captures (7 of 9 kept).

## Evidence

- [05 §6, §8.1–§8.3, §13](../05-fault-lab-and-dataset.md#82-validation-rule); live captures of 2026-11-09/10 (results table in ADR 20261109-cl-lab-catalog-packager).
