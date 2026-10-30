# <Short decision title, as a statement>

- **Status:** Proposed <!-- Proposed | Accepted | Superseded -->
- **Date:** YYYY-MM-DD
- **Author:** <name> (<initials>)
- **Deciders:** <who accepts: the lead; plus all lanes for a breaking contract change>
- **Consulted:** <lanes or people asked>
- **Issue / CCR:** #<N>
- **Supersedes:** <file or "none"> · **Superseded by:** <file or "none">

## Context

What problem forces a decision now? State the constraints (laptop, month, determinism, isolation, frozen contracts) and the facts that matter, each with a citation or labelled *estimate*. Link the sections of [02](../02-architecture.md) or [03](../03-contracts.md) this touches.

## Decision drivers

- <driver, e.g. "verdict must stay replayable">
- <driver>

## Considered options

1. **<Option A>** — one or two sentences.
2. **<Option B>** — …
3. **<Option C>** — …

## Decision

We choose **<option>**, because <reasons tied to the drivers>.

State exactly what changes: files, config keys and defaults, contract fields, commands. Values are config keys with a source or "a priori", never magic numbers.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| <B> | | | |
| <C> | | | |

## Consequences

- **Positive:** …
- **Negative / costs:** …
- **Follow-ups:** issues to open, docs to update, experiments to run.

## Confirmation

How we will know the decision holds: a test, a CI check, a benchmark result, or a date to revisit.

## Evidence

- `[note §Q]` links to `research_notes/`, the report, or primary sources. Mark unverified sources as such.
