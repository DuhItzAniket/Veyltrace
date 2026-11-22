# Relentra fills `proposals[].rank` from the reply order; nothing else in the file depends on it

- **Status:** Accepted (semantics agreed on CCR #409, 2026-11-22)
- **Date:** 2026-11-22
- **Author:** C Lakshanaa (CL)
- **Deciders:** Explain (producer), the lead (schema, Reason)
- **Consulted:** Reason (bench `agent_only`, #398)
- **Issue / CCR:** #409 (proposals 1.1 `rank?`); part of R-16 #45
- **Supersedes:** none · **Superseded by:** none

## Context

04 §4 ranks `agent-only:brief` by "the model's hypotheses in order", but `proposals.json` must depend only on the *set* the model proposed (08 §3.6; 03 §9.1 sorts `proposals[]` by service). The model's order existed only in the cassette, which bench may not read. Proposals 1.1 (#409) adds a nullable `rank` to each proposal. The producer still has to say how the order survives the 08 §3.6 drops, merge and cap.

## Decision drivers

- A reordered but equal reply must keep byte-identical ids, claims and file order (08 §3.6; #410).
- Ranks in one file are exactly 1..k (the core writer check from #409).
- Causentra never reads `rank`, so the verdict cannot depend on the model's order.

## Decision

1. **Position.** A proposal's position is its 1-based index in the checked reply that salvage keeps, after drops and before merging. If a repair ran, that is the last reply that parsed.
2. **Merge.** A proposal merged from several (service, fault_class) members ranks at the smallest position of its members.
3. **Cap.** The `budget.max_hypotheses` cap keeps the same proposals it did before: the canonically first. The kept ones are then renumbered 1..k in position order. Capping by rank would make the reply order decide which proposals survive, so the order would change content.
4. **Unchanged.** `proposal_id`, `claim_id`, the claim merge and the canonical sort of `proposals[]` do not include `rank`. The stub (`status = skipped`) writes no proposals. `mode = external` uses submission order, filled by whoever writes external proposals.

## Consequences

- **Positive:** agent-only measures the model's order, not the alphabet. A permuted reply permutes only `rank` (property test in `test_normalize.py`).
- **Negative:** when the cap drops a proposal the model put first, the kept ranks no longer start at the model's top choice. They stay 1..k in the model's relative order.
- **Neutral:** `proposals.json` outputs are stamped 1.1.0, and fixtures that contain them are refreshed. Verdict hashes do not change.
