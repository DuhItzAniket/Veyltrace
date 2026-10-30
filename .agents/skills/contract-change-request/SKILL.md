---
name: contract-change-request
description: Draft a Contract Change Request (CCR) when a needed field, column or enum value is missing from a Veyltrace contract. Use instead of editing schemas or inventing fields; produces issue text for the human to file with the "Contract change" form.
---

# Draft a Contract Change Request

Rules: `AGENTS.md` §4.2 (never change a contract shape in code; never invent fields, columns or
enum values). Process: `docs/08-collaboration-and-git.md` §5. Field lists: `docs/03-contracts.md`.

1. **Stop coding.** Do not edit `contracts/`, `contracts/generated/`, `docs/03-contracts.md`, or add
   an ad-hoc file, column or JSON key as a workaround. Leave the current code building against
   the current contract version.
2. **Confirm the gap.** Search `docs/03-contracts.md` for the contract and quote the closest
   existing fields. If an existing field already carries the information, say so and stop.
3. **Draft the CCR** (the human files it with the issue form "Contract change"):
   - Contract: name and section in `docs/03-contracts.md` (e.g. `evidence`, §7)
   - Change: field name, type, unit, nullability, allowed values, sort-key impact
   - Kind: additive (new optional field → minor bump) or breaking (rename/remove/required →
     major bump, needs all three lanes)
   - Producer lane and consumer lanes affected
   - Why: the acceptance criterion or spec section that needs it; evidence, not preference
   - Proposed JSON Schema fragment
   - Fixture impact: which `packages/*/fixtures/` golden files the producer must refresh
4. **ADR stub.** After M1 (8 Nov) a CCR needs an ADR: draft
   `docs/adr/YYYYMMDD-<initials>-<slug>.md` using the template `docs/adr/_template.md`.
5. **Hand back** to the human: the CCR text, the ADR draft, and what you will do meanwhile
   (keep building against fixtures; the lead implements the schema change in one PR).
