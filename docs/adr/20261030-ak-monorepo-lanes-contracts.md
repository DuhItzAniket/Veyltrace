# One monorepo with lanes, frozen contracts and no shared registries

- **Status:** Accepted
- **Date:** 2026-10-30
- **Author:** Aniket Kumar (ak)
- **Deciders:** lead
- **Consulted:** all lanes (kickoff)
- **Issue / CCR:** kickoff; tasks L-00, R-01, R-02, L-03
- **Supersedes:** none · **Superseded by:** none

## Context

Three people, each with a different AI coding agent, build one repository in one month. 2026 data on agentic pull requests: a 27.67% merge-conflict rate across 107K simulated PRs; different-agent pairs open at the same time conflict 41.7% of the time against 19.8% for same-agent pairs; 84.4% of conflicted files are source code and about 42% of conflicts are structural (add/add, modify/delete) ([multi_agent_dev §Q3][md]). The repository is public and owned by a personal account, so GitHub's merge queue is not available ([multi_agent_dev §Q3][md]). Git for Windows disables symlinks by default ([multi_agent_dev §Q1][md]). Sequential ADR numbers collide on parallel branches; date-prefixed names avoid that ([multi_agent_dev §Q3][md]).

## Decision drivers

- No two lanes ever create or edit the same path.
- The only shared surface between lanes is versioned contracts plus golden fixtures.
- Generated files are regenerated, never merged by hand.
- Works the same for Claude Code, Codex, Cursor, Antigravity, Copilot and others.

## Considered options

1. **Monorepo: uv workspace + pnpm, lanes in `lanes.yml`, JSON Schema contracts frozen at M1, entry points, towncrier, date-named ADRs** (chosen).
2. Polyrepo (one repo per lane or engine).
3. Monorepo with conventional hot spots (central registries, hand-edited CHANGELOG, numbered ADRs).
4. Pydantic models as the contract source of truth, with JSON Schema and TypeScript generated from them.

## Decision

1. **Packaging.** One uv workspace with a single root `uv.lock`; all 15 Python members (13 under `packages/`, plus `bench/` and `contracts/generated/python/`) are registered at M0 and the list is not edited afterwards. pnpm for `console/` only. Lockfiles are regenerated on conflict, never hand-merged, and only in `chore(deps)` PRs ([08 §3.1, §6](../08-collaboration-and-git.md)).
2. **Lanes.** `.github/lanes.yml` is the single source of path ownership; `.github/CODEOWNERS` is generated from it by `scripts/check_lanes.py --write-codeowners`, and CI fails if they disagree or if a PR touches another lane's paths without the `cross-lane` label ([08 §2](../08-collaboration-and-git.md)). Author-owned shared files (`changes/*.md`, `docs/adr/2*-*.md`, `docs/team/*.md`) are open to everyone. Inside Reason-owned folders, `bench/decoys/`, `bench/stats/` and `paper/sections/observe-*` are Observe's and `paper/sections/explain-*` is Explain's ([08 §3](../08-collaboration-and-git.md)).
3. **Contracts.** JSON Schema 2020-12 in `contracts/schemas/` is the source of truth; Pydantic v2 and TypeScript types are generated into `contracts/generated/` and CI fails on drift; gateway API types are generated from `packages/gateway/openapi.json` into `contracts/generated/ts/api/` by the same script ([03 §14](../03-contracts.md)). Versions `0.x` until M1 (Sun 8 Nov), frozen at `1.0` on M1; afterwards only additive optional fields via a Contract Change Request issue, an ADR and lead approval; removing or renaming a field needs all three lanes and a major bump ([03 §1](../03-contracts.md); [08 §5](../08-collaboration-and-git.md)).
4. **No shared registries.** Python entry points (`veyltrace.engines`, `.adapters`, `.fetchers`, `.rankers`, `.trials`, `.predicates`) declared in each package's own `pyproject.toml`; one `config/<engine>.yaml` per engine; towncrier fragments `changes/<issue>.<type>.md` instead of a CHANGELOG; ADRs named `YYYYMMDD-<initials>-<slug>.md` with no numbers and no index file ([08 §3.1](../08-collaboration-and-git.md); [adr/README](README.md)).
5. **Work isolation.** One agent, one worktree, one short-lived branch (`<lane>/<issue>-<slug>`, ≤ 2 days); rebase, never merge; squash merge; PRs ≤ 400 changed lines excluding fixtures and generated code ([08 §4](../08-collaboration-and-git.md)).
6. **Merge-queue substitute.** Branch protection with required checks (`lanes`, `agent-files`, `docs`, `lint`, `types`, `tests`, `isolation`, `determinism`, `contracts-in-sync`, `changelog`, `console`), "require branches to be up to date", linear history and auto-merge ([08 §4.1](../08-collaboration-and-git.md)).
7. **Agent instructions.** One root `AGENTS.md`; `CLAUDE.md` is the one-line import `@AGENTS.md`; nested `AGENTS.md` per package only adds rules; no tool-specific copies or symlinks ([multi_agent_dev §Q1][md]).

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Polyrepo | Hard isolation | Cross-repo version pinning and CI for every contract change; one month is too short | Too much coordination overhead |
| Conventional hot spots | Familiar | Every new engine, ranker or changelog line edits a shared file: the structural-conflict class the data warns about | Avoidable conflicts |
| Pydantic-first contracts (suggested in the research) | One language for the lead | Python-centric; TypeScript and Parquet column schemas are second-class; 02 fixes JSON Schema as the source ([02 §7](../02-architecture.md)) | JSON Schema is language-neutral and also describes Parquet rows |
| Per-person ADR number ranges | Short references | Still a convention to police; numbers carry no date | Date + initials is collision-free by construction |
| Merge queue in a free organization | Serialised merges | Requires moving the repo; not needed at three people | Required checks + up-to-date branches suffice |

## Consequences

- **Positive:** Structural conflicts between lanes are impossible unless a PR crosses lanes, which CI flags. Consumers build against golden fixtures from M0, so no lane waits for another ([08 §8](../08-collaboration-and-git.md)).
- **Negative / costs:** Contract changes after M1 cost an issue, an ADR and a regeneration PR. The lead owns every shared file and becomes a review bottleneck. **CODEOWNERS must list two owners per path**: an author cannot satisfy their own code-owner review ([multi_agent_dev §Q3][md]), and the current generated file lists only the lead for every path, so the lead's own PRs would be blocked. `check_lanes.py --write-codeowners` should emit lane owner + lead, and lead + one teammate for Reason paths ([12-risks](../12-risks.md) RK-25).
- **Follow-ups:** L-00 fills real GitHub logins in `lanes.yml` and regenerates CODEOWNERS with two owners; L-03 adds the CI jobs; R-01 writes the schemas; R-07 freezes them at M1.

## Confirmation

- `contracts-in-sync` and `lanes` CI jobs green on `main`.
- Conflict counts and `agent:` labels are collected from PRs and reported as a process note in the paper ([11 §6](../11-research-paper-plan.md)).

## Evidence

- [multi_agent_dev §Q1–Q4][md]; [report][rep], "Three coding agents need structure, not etiquette, to share one repo"; [08](../08-collaboration-and-git.md).

[rep]: ../../reports/Veyltrace%20v2%20SOTA%20root%20cause%20analysis.md
[md]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/multi_agent_dev_and_sdlc.md
