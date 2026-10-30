# Architecture decision records

An ADR records one decision that is hard to reverse or that other lanes depend on: what we decided, what else we considered, what it costs us, and the evidence. ADRs are short (one to two pages) and are never rewritten after acceptance; a changed decision gets a new ADR that supersedes the old one.

[02-architecture](../02-architecture.md) is the master spec. An accepted ADR that changes 02 must be merged together with the edit to 02, so the two never disagree.

## When to write one

- Changing anything in [02](../02-architecture.md) (an engine boundary, algorithm, default parameter, stack pin or principle).
- Any contract change after M1, together with its Contract Change Request ([08 §5](../08-collaboration-and-git.md)).
- Resolving an open decision in [02 §12](../02-architecture.md) (e.g. DuckDB pin, default local model, calibration family split).
- Each cut from the cut list in [07 §1.1](../07-roadmap.md) (one short ADR, so the paper reports the cut honestly).
- Adding a dependency that affects licence, determinism or the AI/network isolation rules.
- Venue, authorship and post-month plan (task L-07).

Not needed for: bug fixes, refactors inside one package, test changes, docs that do not change a decision.

## Naming

`docs/adr/YYYYMMDD-<initials>-<slug>.md`, for example `20261030-ak-conformal-abstention.md`.

- `YYYYMMDD` is the date the ADR was proposed.
- `<initials>` are the author's: `ak` Aniket Kumar, `as` Annapurna S, `cl` C Lakshanaa.
- `<slug>` is 2–5 lowercase words joined by hyphens.

Date plus initials means two people can never pick the same file name, so parallel branches do not conflict. There are no sequence numbers and no hand-maintained index: this directory sorted by name is the log. Refer to an ADR by its slug, e.g. "ADR conformal-abstention".

Anyone may create their own ADR file ([AGENTS.md §2](../../AGENTS.md)); only its author edits it while it is Proposed.

## Statuses

| Status | Meaning | Set by |
|---|---|---|
| **Proposed** | Open for comment in a PR. Not binding. | Author |
| **Accepted** | Binding. Merged by the lead, together with any change to 02 or 03. | Lead |
| **Superseded** | Replaced by a later ADR; the header links to it (`Superseded by: <file>`). The text is otherwise left unchanged. | Lead, in the PR that accepts the new ADR |

A proposal the team declines is closed without merging; record the reason in the PR so the discussion is findable.

## Process

1. **Open an issue.** For a contract change after M1, use the "Contract change" form (CCR). For anything else, a normal issue labelled `type:adr`.
2. **Write the ADR** from [`_template.md`](_template.md) with status Proposed, and open a PR titled `docs(adr): <slug> (#N)` with a towncrier fragment.
3. **Discuss in the PR.** Reviews from the lanes the decision affects. Contract changes: additive needs the lead; breaking needs all three lanes ([03 §1](../03-contracts.md)).
4. **Accept.** The lead sets status Accepted and merges. If the decision changes 02 or 03, the same PR (or a linked PR merged first) updates them; for contracts, the lead's implementing PR updates schema, generated code, 03 and the version ([08 §5](../08-collaboration-and-git.md)).
5. **Supersede** an earlier ADR by naming it in the new ADR's header and changing the old one's status line in the same PR.

## Index of initial decisions (30 Oct 2026)

| ADR | Decision |
|---|---|
| [20261030-ak-propose-verify-trust-model](20261030-ak-propose-verify-trust-model.md) | AI proposes, code decides; symmetric claim evaluation |
| [20261030-ak-ten-engine-boundaries](20261030-ak-ten-engine-boundaries.md) | Roles of the ten engines and their lanes |
| [20261030-ak-local-first-llm](20261030-ak-local-first-llm.md) | Local open-weight model by default; cassette replay tiers |
| [20261030-ak-parquet-duckdb-storage](20261030-ak-parquet-duckdb-storage.md) | Parquet as the durable format, DuckDB as the query engine |
| [20261030-ak-monorepo-lanes-contracts](20261030-ak-monorepo-lanes-contracts.md) | uv + pnpm monorepo, lanes, frozen contracts, no shared registries |
| [20261030-ak-conformal-abstention](20261030-ak-conformal-abstention.md) | Split-conformal candidate sets, statuses and `NO_FAULT` |
| [20261030-ak-hackday-v1-archived](20261030-ak-hackday-v1-archived.md) | v1 materials kept out of the repo; what carried over |

This table lists the founding set only. Later ADRs are found by listing the directory.
