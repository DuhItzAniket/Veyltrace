# 08 · Collaboration and git workflow

> **Status:** v1.0 · **Owner:** lead · **Last updated:** 2026-10-30
> Goal: three people, each driving a different AI coding agent, build one repo for a month with **zero merge conflicts on code** and no silent drift. The rules are structural (paths, contracts, generated files), not etiquette.

## 1. Why structure, not goodwill

2026 data on AI-agent pull requests: about 28% of agentic PRs hit merge conflicts; PR pairs from **different** agents that are open at the same time conflict **41.7%** of the time vs 19.8% for the same agent; 84% of conflicted files are source code and ~42% of conflicts are structural (add/add, modify/delete) `[multi_agent_dev_and_sdlc §Q3]`. Three people on three different agents is the highest-risk setup. Structural conflicts disappear when no two lanes ever create or edit the same path, so that is the core rule.

## 2. Lanes

| Lane | Person (proposed; confirm at kickoff) | Engines | Other areas |
|---|---|---|---|
| **Reason** (lead) | Aniket Kumar · `@DuhItzAniket` | FaultLoom, Causatrix, Causentra | `contracts/`, `packages/core`, `bench/`, shared docs, CI, `.github/`, `.agents/` |
| **Observe** | Annapurna S | Infralume, Signalyth, Anomara, Causync, Causalith | dataset fetchers (inside Infralume), `scripts/observe/` |
| **Explain** | C Lakshanaa | Relentra, Causivra | `packages/llm`, `packages/gateway`, `console/`, `lab/`, `scripts/explain/` |

The machine-readable path map is [.github/lanes.yml](../.github/lanes.yml). `.github/CODEOWNERS` is **generated** from it (`uv run scripts/check_lanes.py --write-codeowners`); CI fails if the two disagree. Swapping people between lanes is a one-line PR to `lanes.yml` (lead approves) — do it at kickoff, not mid-sprint.

**Load check (estimate, summed from [07-roadmap](07-roadmap.md) task estimates):** Reason ≈ 24.5 person-days (+ integration and review duty), Explain ≈ 23.5, Observe ≈ 20, plus ≈ 2 shared days each. To balance, the decoy generator (`bench/decoys/`) and the statistics module (`bench/stats/`) are Observe-owned even though they live under `bench/`. The cut list (07 §1.1) removes Observe and Explain items first. Re-check the balance at every Sunday review. AI agents raise throughput but not review capacity, so PR size limits (§4) matter more than raw hours.

## 3. Repository layout and who owns what

```
.
├── AGENTS.md  CLAUDE.md  README.md  LICENSE  CITATION.cff     lead
├── pyproject.toml  uv.lock  towncrier.toml  .pre-commit-config.yaml   lead (workspace members fixed at M0)
├── config/
│   ├── core.yaml                                               lead
│   └── <engine>.yaml                                           engine's lane
├── contracts/  (schemas/, generated/)                          lead
├── packages/
│   ├── core/                                                   Reason (lead)
│   ├── infralume/ signalyth/ anomara/ causync/ causalith/      Observe
│   ├── faultloom/ causatrix/ causentra/                        Reason
│   └── relentra/ causivra/ llm/ gateway/                       Explain
├── bench/                                                      Reason
│   └── decoys/  stats/                                         Observe
├── paper/            LaTeX sources                             lead
│   └── sections/observe-*  sections/explain-*                  that lane
├── lab/              (not a workspace package; `scripts/check.py --package lab` lints and tests it by path)   Explain
├── console/                                                    Explain
├── tests/            cross-package (isolation, determinism, e2e)  lead
│   └── integration/test_<lane>_*.py                            that lane
├── scripts/          portable commands                         lead
│   └── observe/  explain/                                      that lane
├── changes/          towncrier fragments, one per PR           PR author
├── docs/             shared docs                               lead
│   ├── engines/NN-<engine>.md                                  engine's lane
│   ├── adr/YYYYMMDD-<initials>-<slug>.md                       ADR author
│   └── team/<initials>.md                                      that person
├── .agents/skills/   shared agent skills (source)              lead
├── .claude/skills/   generated copy for Claude Code            lead (sync script)
└── .github/          lanes.yml, CODEOWNERS (generated), templates, workflows   lead
```

Inside every package:

```
packages/<name>/
├── AGENTS.md          lane rules for this package (adds to root AGENTS.md)
├── CLAUDE.md          "@AGENTS.md" so Claude Code also loads the nested file
├── README.md          purpose, inputs/outputs, how to run
├── pyproject.toml     name = "veyltrace-<name>", own dependencies, entry points
├── src/veyltrace_<name>/
│   ├── __init__.py    version only (no re-export lists)
│   └── api.py         run(ctx) -> EngineResult
├── tests/
└── fixtures/<case>/   golden outputs for synth-01…05
```

### 3.1 Hot spots removed by design

| Usual conflict hot spot | How we avoid it |
|---|---|
| Central registry (`ENGINES = {...}`, router tables, `__init__` re-exports) | Python entry points (`veyltrace.engines`, `veyltrace.adapters`, `veyltrace.fetchers`, `veyltrace.rankers`, `veyltrace.trials`, `veyltrace.predicates`) declared in each package's own `pyproject.toml` |
| Root `pyproject.toml` workspace members | all 15 Python packages (13 under `packages/`, plus `bench/` and `contracts/generated/python/`) registered at M0; nobody edits the list afterwards |
| One big config file | one `config/<engine>.yaml` per engine |
| `CHANGELOG.md` | towncrier fragments `changes/<issue>.<type>.md`, compiled at release |
| ADR numbers | `docs/adr/YYYYMMDD-<initials>-<slug>.md`, no sequence numbers |
| Shared test files | `tests/integration/test_<lane>_*.py` per lane |
| Docs index | only the lead edits `docs/README.md`; lanes edit their own engine docs |
| Generated code | `contracts/generated/` is regenerated by script; CI fails on drift; never hand-merged |
| Lockfiles | see §6 |

## 4. Branches, commits, PRs

- **Trunk-based.** `main` is always green and protected. Work happens on short-lived branches (≤ 2 days): `<lane>/<issue>-<slug>`, e.g. `observe/14-drain3-templates`. Cross-cutting lead branches use `lead/<issue>-<slug>`.
- **One agent, one worktree, one branch.** Never run two agents in the same folder.
  - Any tool: `git fetch origin && git worktree add ../vt-<issue> -b <lane>/<issue>-<slug> origin/main`
  - Claude Code: `claude --worktree <issue>-<slug>` (creates branch `worktree-<issue>-<slug>`; rename it with `git branch -m <lane>/<issue>-<slug>` before the first push)
  - Remove when merged: `git worktree remove ../vt-<issue>`
- **Rebase, don't merge:** `git fetch origin && git rebase origin/main` before starting each session and before opening the PR.
- **Conventional Commits**, scope = package or area: `feat(causatrix): add gated RRF (#31)`, `fix(infralume): …`, `docs(adr): …`, `exp(bench): …`, `chore(deps): …`.
- **PR rules:**
  1. one issue per PR; title = the main commit message
  2. ≤ 400 changed lines excluding `fixtures/` and `contracts/generated/`
  3. labels: `lane:<lane>`, `type:<type>`, `agent:<tool>` (or `agent:none`)
  4. a towncrier fragment
  5. the Definition of Done in the template ticked ([10-sdlc-and-quality §3](10-sdlc-and-quality.md))
  6. one approval from someone other than the author (CODEOWNERS requests the right person)
  7. **squash merge** only; delete the branch
- **Review SLA:** reviewers respond within 12 hours on weekdays. A PR waiting longer may be merged by the lead after a self-review checklist, noted in the PR.

### 4.1 GitHub settings (lead, task L-00)

The repo is public and owned by a personal account, so **merge queue is not available** `[multi_agent_dev_and_sdlc §Q3]`. Branch protection on `main`:

- require a PR, 1 approval, review from Code Owners
- required status checks: `lanes`, `agent-files`, `docs`, `lint`, `types`, `tests`, `isolation`, `determinism`, `contracts-in-sync`, `changelog`, `console` (jobs that do not apply yet are skipped by the `detect` job and count as passing; verify this once on the first PR)
- **require branches to be up to date before merging** (the merge-queue substitute)
- require linear history; require conversation resolution; block force pushes
- allow auto-merge (so an approved, up-to-date, green PR merges itself)

Until both teammates' logins are in `lanes.yml`, the generated CODEOWNERS lists only the lead, who cannot approve their own PRs. So L-00 fills the logins **before** enabling "review from Code Owners"; after regeneration every path has at least two owners.

## 5. Contracts: the only shared surface

Lanes depend on each other only through [contracts](03-contracts.md) and golden fixtures.

1. **Before M1:** contracts are `0.x`. The lead may change them; every change is announced in the CCR issue and the team chat with the PR link.
2. **M1 freeze (Sun 8 Nov):** contracts become `1.0`.
3. **After M1, to change a contract:**
   1. Open an issue with the **Contract change** form: what, why, which producer/consumers, additive or breaking.
   2. Write an ADR (`docs/adr/YYYYMMDD-<initials>-<slug>.md`).
   3. Lead implements in one PR: schema + generated code + `docs/03-contracts.md` + version bump. Additive (new optional field) = minor bump; breaking = major bump, needs approval from all three lanes.
   4. Producer updates its golden fixtures in a follow-up PR; consumers adopt when ready (additive changes don't break them).
4. **Never** work around a missing field with an ad-hoc file, column or JSON key. Agents are told to stop and draft a CCR instead ([AGENTS.md §4](../AGENTS.md)).

## 6. Lockfiles and dependencies

- Dependencies are declared only in the package that uses them (`packages/<name>/pyproject.toml`, `console/package.json`).
- A dependency change is its own small PR titled `chore(deps): …` with only the package's manifest and the lockfile.
- `uv.lock` conflict during rebase: `git checkout origin/main -- uv.lock && uv lock && git add uv.lock && git rebase --continue`. Never hand-edit it.
- `pnpm-lock.yaml` conflict: `pnpm -C console install`, then commit. Only the Explain lane touches it.
- Shared dev tools (ruff, pyright, pytest, hypothesis, towncrier, pre-commit) are pinned once by the lead in the root `pyproject.toml` dev group at M0.

## 7. Integration rhythm

| When | What | Who |
|---|---|---|
| Every working session | rebase on `main`; run your package checks; push small PRs | everyone |
| Daily, by 22:00 IST | 3-line async standup as a comment on the week's milestone tracking issue: done / next / blocked | everyone |
| Wednesday | **integration check**: lead runs the end-to-end pipeline on `synth-01…05` + 3 real cases at `main` HEAD, posts the scorecard and any breakage as issues | lead |
| Sunday | **milestone review** (video call, 45 min): demo of what merged, scorecard vs last week, risks, next week's issues assigned, tag `v0.N.0` | all |
| Any time a lane is blocked by another | open an issue with label `blocked`, link the blocking issue, @-mention the owner | blocked person |

## 8. Golden fixtures and stubs (how lanes start without waiting)

- **M0:** the lead's synthetic generator (`veyltrace_core.synth`) produces `synth-01…05`: a 6-service toy system with known faults (CPU hog, network delay, error injection, change-induced regression, no-fault). It writes canonical `telemetry.*` + `case_manifest` directly, plus answer keys for `bench`.
- **M0:** every engine lands a **stub** `run(ctx)` that reads its real inputs and writes schema-valid outputs (hard-coded but valid), so `veyltrace diagnose` runs end to end on day 2.
- From then on each producer replaces its stub with the real algorithm and refreshes its golden fixtures (`uv run python scripts/check.py --package <name> --update-golden`, reviewed like code). Consumers' tests use the producer's fixtures, so a consumer is never blocked by an unfinished producer.

## 9. When things go wrong

| Situation | Do this |
|---|---|
| Your PR conflicts | rebase on `origin/main`; if the conflict is in another lane's path, your branch touched it by mistake — revert that part |
| `main` is red | the person whose PR broke it reverts within 2 hours (`git revert`), then fixes forward |
| An agent edited files outside your lane | discard those changes (`git restore`/`git checkout`), re-run with the task narrowed; CI's `lanes` check will catch it otherwise |
| Two people need the same change | the owning lane does it; the other opens an issue and works against fixtures meanwhile |
| A contract is wrong after M1 | CCR (§5); keep building against the current version |
| Someone is unavailable for > 2 days | the lead re-assigns their open issues at the next standup |
