# Hack-day v1 materials are archived outside the repository

- **Status:** Accepted
- **Date:** 2026-10-30
- **Author:** Aniket Kumar (ak)
- **Deciders:** lead
- **Consulted:** all lanes
- **Issue / CCR:** kickoff
- **Supersedes:** none · **Superseded by:** none

## Context

Veyltrace started as a hackathon entry for the problem statement "Diagnose the Outage": the RCAEval benchmark, with the rule that AI may only explain, never decide. The entry was not selected. v2 drops the hackathon constraints and aims for a publishable research system with a working demo.

The v1 material is a design (`_hackday-v1/`, including its own `AGENTS.md` and architecture doc), research notes (`research_notes/Veyltrace outage diagnosis research/`) and a report (`reports/Veyltrace outage diagnosis research.md`). Two problems follow if it stays in the working tree that agents read:

- v1's binding rules contradict v2's. The v1 rule "AI may only explain" is replaced by propose–verify ([ADR propose-verify-trust-model](20261030-ak-propose-verify-trust-model.md)). An agent that reads both will mix them.
- The v1 `CLAUDE.md` pointed at `AGENTS.md` and `docs/02-architecture.md` files that existed only under `_hackday-v1/` ([report][rep], "One AGENTS.md, imported everywhere").

## Decision drivers

- Agents must see exactly one set of binding rules.
- v1 research stays available to the lead as background.
- No v1 number is ever presented as a v2 result.

## Considered options

1. **Keep v1 on the lead's disk, git-ignored; forbid agents from reading `_hackday-v1/`** (chosen).
2. Commit v1 into an `archive/` folder in the repository.
3. Delete v1.
4. Move v1 to a separate private repository.

## Decision

1. `_hackday-v1/`, `research_notes/Veyltrace outage diagnosis research/` and `reports/Veyltrace outage diagnosis research.md` are listed in `.gitignore` and never committed.
2. Agents must not read `_hackday-v1/` ([AGENTS.md §3.3](../../AGENTS.md)). The v2 research notes and report are the cited evidence base.
3. Where a v2 doc needs a fact that exists only in the v1 notes (for example the outage-cost survey figures in [01 §1](../01-vision-and-requirements.md)), it cites the **primary source URL** and says the source is in the team's local archive (verify before publication), so the claim stays checkable without the archive. RCAEval and baseline facts from the v1 notes are restated with their primary sources in the committed [rcaeval_facts](../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md) note.
4. Engine names are kept; their v2 roles are set by [02 §3](../02-architecture.md) and [ADR ten-engine-boundaries](20261030-ak-ten-engine-boundaries.md).

**What carried over from v1** (as described in the v2 research; v2 specs restate each item so nobody needs the v1 files):

| Item | Where it lives in v2 |
|---|---|
| PRISM-style internal-versus-external scoring | `klass` tags ([02 §6.2](../02-architecture.md)); `prism_m` ranker ([02 §6.7](../02-architecture.md)); trial T1 |
| Onset-anchored windows | `t_onset` and onset-anchored scoring windows ([02 §5.1, §6.3](../02-architecture.md)) |
| Multi-part scale floor for robust z | Anomara detectors ([02 §6.3](../02-architecture.md)) |
| Conformal candidate-set idea | [ADR conformal-abstention](20261030-ak-conformal-abstention.md) |
| Placeholders in narration (code fills every number and name) | Causivra claim checker ([02 §6.10](../02-architecture.md)) |
| Determinism rules: exact quantiles, DuckDB `threads=1` for final aggregates, total tie-breaks, canonical JSON, tests under two `PYTHONHASHSEED` values ([report][rep]) | [02 §9](../02-architecture.md); [ADR parquet-duckdb-storage](20261030-ak-parquet-duckdb-storage.md) |
| "A number exists only if a script wrote it to results" ([report][rep]) | [AGENTS.md §4.8](../../AGENTS.md); `bench/results/` |
| No AI or network in the decision path | Kept for engines 1–7 and 9 through import isolation ([02 §9](../02-architecture.md)) |

**What changed in v2:**

| v1 | v2 |
|---|---|
| AI may only explain | AI may propose candidates and request predicates; code decides ([02 §2](../02-architecture.md) P1–P2) |
| RCAEval only | RCAEval plus Nezha, the FSE'26 TrainTicket set (stretch), RCAEval-C decoy changes and the VeylLab lab dataset |
| Hackathon deliverable | Research system with a paper plan, replayable receipts and a DOI-archived release ([11](../11-research-paper-plan.md)) |
| No change events | Change-aware evidence channel (Causync) |
| Single answer | Conformal candidate set with `NO_FAULT` and `INCONCLUSIVE` |
| v1 engine roles | Ten roles reassigned for v2 in three lanes |
| No live system | Laptop lab (Online Boutique on kind with Chaos Mesh) and a live demo |

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Commit to `archive/` | History in one place | Agents read it and mix contradictory rules; enlarges the public repo with superseded material | Rule confusion is the main risk with three agents |
| Delete v1 | Clean | Loses research and provenance | No reason to destroy it |
| Separate private repo | Keeps it versioned and shareable | Extra setup during week 1 | Possible later; not needed now |

## Consequences

- **Positive:** One binding rule set for every agent; the public repository starts at v2.
- **Negative:** Teammates and reviewers cannot read the v1 notes; any fact taken from them must carry a primary-source URL. v2 docs that cite v1-only figures cannot link to the note itself.
- **Follow-ups:** if the v1 material is needed later (e.g. for a retrospective), move it to a private repository and record that in a superseding ADR.

## Confirmation

- `git check-ignore` reports all three paths as ignored on every laptop.
- No v2 doc links into `_hackday-v1/` or the v1 notes.

## Evidence

- [report][rep], "One AGENTS.md, imported everywhere" and "Replay re-verifies recorded proposals instead of re-generating them"; `.gitignore` (lead decision, 2026-10-30).

[rep]: ../../reports/Veyltrace%20v2%20SOTA%20root%20cause%20analysis.md
