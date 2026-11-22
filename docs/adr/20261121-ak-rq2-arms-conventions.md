# RQ2 arms: planted proposals rank first and claim against the slate, agent-only falls back to the slate

- **Status:** Accepted (manager decisions on the review of #417–#408, 2026-11-22; the lead delegated design)
- **Date:** 2026-11-21
- **Author:** Aniket Kumar (AK)
- **Deciders:** the lead (decisions relayed by the manager session)
- **Consulted:** Explain (CCR #409, `proposals[].rank`; @C-LAKSHANAA)
- **Issue / CCR:** #398 (agent_only), #399 (planted proposals), #409 (proposals 1.1 `rank?`); part of R-16 #45
- **Supersedes:** none · **Superseded by:** none

## Context

Two RQ2 arms depend on choices [04](../04-evaluation-protocol.md) leaves open. `agent-only:brief` ranks "the model's hypotheses in order, then the remaining slate order" (04 §4), but `proposals.json` is canonically sorted by service (03 §9.1), so only a new `rank` field (#409) carries the model's order. The planted-decoy protocol (04 §5.2, H2b) adds "one fabricated proposal per case for a healthy service with false claims", without saying where it ranks, which claims it makes, or what the summary compares.

## Decision drivers

- No ground truth may enter a pipeline input (bench/AGENTS.md; 02 §2 P7).
- An arm must never be silently scored on an artefact of the file format (A→Z order).
- H2b should measure the verifier against a strong adversary, not a convenient one.

## Decision

1. **Agent-only order.** Hypotheses are ranked by `proposals[].rank`. A proposal with a null rank makes the case unranked (a miss, 04 §7, logged). With **no hypotheses at all**, for any status, the ranking is the slate's, as 04 §4 reads; the verifier arm also falls back to the slate. Bench counts those rows per group in its log (`bench.agent_only_slate_fallback`). Until the contract has `rank`, bench refuses `agent_only` experiments ("needs proposals 1.1 rank (#409)").
2. **Planted rank (a priori, worst case).** Once proposals carry `rank`, the planted proposal is **rank 1** and the recorded ones are renumbered 2..k+1, keeping their order. The threat model is an adversary who controls the proposal channel. Agent-only's planted result follows from this choice, and the paper says so.
3. **Planted claims.** The answer key only picks the decoy: a healthy service, any service but the root. No claim names the root. The decoy claims (a) `onset_before` the source run's slate top-1 (the next service if the top-1 is the decoy), a pipeline-derived service, and (b) a CPU robust z of at least 3. FaultLoom evaluates both like any claim. The derived `proposals.json` keeps the source run's `status` and has a zero `budget_used`, since no model is called.
4. **What the summary holds.** In an `inject_proposals` experiment, summary groups and statistics contain only the planted rows, one per (case, seed). The unplanted comparison is the rq2 experiment's rows, as the YAML says. `decoy_top1_change` pairs each planted row with its source run's row, which stays in `per_case.csv`.

## Consequences

- **Positive:** no ground truth reaches a pipeline input; agent-only can never be scored on the alphabet; H2b's verifier result is a worst case.
- **Negative / costs:** agent-only cannot run before #409 and Relentra brief mode (#354–#356). With the planted proposal at rank 1, agent-only's H2b top-1 change is near 1 by construction; that is the point of comparing it with the verifier.
- **Follow-ups:** #409 (Explain) and #410 (normaliser permutation test).

## Confirmation

`bench/tests/test_agent_only.py` (rank order, null → unranked, refusal until #409, slate fallback logged) and `bench/tests/test_planted.py` (claims from the slate, the source's status, zero budget, rank 1 under the field, summary `n_fault` = cases).
