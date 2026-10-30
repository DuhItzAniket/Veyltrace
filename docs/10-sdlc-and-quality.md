# 10 · SDLC and quality

> **Status:** v1.0 · **Owner:** lead · **Last updated:** 2026-10-30
> Goal: one way of moving work from an idea to a release, with quality gates a machine can check. Lanes, branching and PR rules are in [08](08-collaboration-and-git.md); tasks and dates in [07](07-roadmap.md); agent setup in [09](09-ai-agent-playbook.md). Where this doc and [02](02-architecture.md) disagree, 02 wins.
> GitHub Free is enough for a team of three: issue forms, labels, milestones, one Projects board, a PR template with the Definition of Done, required CI checks, SemVer tags and towncrier release notes ([multi_agent_dev_and_sdlc §Q4][q4]).

## 1. SDLC phases mapped to the roadmap

| SDLC phase | Roadmap | Dates (2026) | Main outputs | Gate (milestone, tag) |
|---|---|---|---|---|
| Plan and requirements | P0 Ground: L-00, L-02 | Sat 31 Oct – Tue 3 Nov | issues on the board, questions answered, laptops benchmarked | M0, `v0.0.1` |
| Design | P0–P1: R-01, R-07, ADRs | 31 Oct – Sun 8 Nov | contracts `0.1` → `1.0`, ADRs for stack pins | M1, `v0.1.0`, `contracts-1.0` |
| Build | P1–P3 engine tasks | 4 Nov – 22 Nov | engines, bench, console, lab | M2 `v0.2.0`, M3 `v0.3.0` |
| Verify | continuous (CI, Wednesday integration checks) | every PR, every Wednesday | green `main`, scorecard | every merge |
| Evaluate | P4: R-16, R-17, L-04 | Mon 23 – Sun 29 Nov | experiment matrix, frozen tables, paper draft | M4, `v0.9.0` |
| Release | L-05, L-06, L-07 | Mon 30 Nov – Tue 1 Dec | release notes, DOI, verified `REPRODUCE.md`, retrospective | M5, `v1.0.0` |
| Maintain | after the month | December 2026 → | preprint, v1.1 scope | ADR from L-07 |

Exit criteria for each milestone are in [07 §1](07-roadmap.md#1-phases-and-milestones). A milestone that slips by more than a day triggers the cut list ([07 §1.1](07-roadmap.md#11-cut-list-if-a-milestone-slips-by--1-day)).

## 2. Work item lifecycle

```text
issue ──► branch + worktree ──► PR ──► review ──► squash merge ──► release (tag + notes)
Backlog     In progress          In review          Done             (fragment compiled)
```

| Step | Who | What happens | Board status |
|---|---|---|---|
| 1. Issue | anyone (roadmap tasks: `scripts/create_issues.py`) | filed with an issue form; `lane:*` and `type:*` labels; milestone set | Backlog |
| 2. Ready | lane owner, confirmed by lead at the Sunday review | Definition of Ready (§3.1) holds; assignee set | Ready |
| 3. Branch | assignee | `git worktree add ../vt-<N> -b <lane>/<N>-<slug> origin/main` ([09 §4](09-ai-agent-playbook.md#4-session-protocol)) | In progress |
| 4. PR | assignee + agent | PR from the template; `Closes #N`; labels `lane:*`, `type:*`, `agent:*`; draft until checks pass | In review (when marked ready) |
| 5. Review | code owner (CODEOWNERS requests them) | checklist §6; 1 approval; conversations resolved; branch up to date; required checks green | In review |
| 6. Merge | author enables auto-merge; GitHub merges | squash merge; branch deleted; issue closed by `Closes #N` | Done |
| 7. Release | lead, Sunday | fragment compiled into `CHANGELOG.md`; tag `v0.N.0` | Done |

Rules from [08 §4](08-collaboration-and-git.md#4-branches-commits-prs): one issue per PR, branches live ≤ 2 days, ≤ 400 changed lines (excluding `fixtures/` and `contracts/generated/`), reviewers respond within 12 hours on weekdays, nobody merges their own PR without approval.

## 3. Definition of Ready and Definition of Done

### 3.1 Definition of Ready (an issue may move to Ready when)

- [ ] It has one `lane:*` label (or all three for team tasks such as L-01), one `type:*` label and a milestone.
- [ ] Acceptance criteria are checkable: each is a test, a command output or a file that exists.
- [ ] The docs to read are listed (engine spec section, contract sections).
- [ ] Dependencies are merged, or golden fixtures exist so the work can start against them ([08 §8](08-collaboration-and-git.md#8-golden-fixtures-and-stubs-how-lanes-start-without-waiting)).
- [ ] Every contract field it needs exists in [03](03-contracts.md); if not, a CCR is filed first.
- [ ] It fits one PR: ≤ 2 days and ≤ 400 changed lines (*estimate*); otherwise split.

### 3.2 Definition of Done (a PR may merge when)

The same list is in [.github/pull_request_template.md](../.github/pull_request_template.md). "How checked" says whether a machine or the reviewer enforces it.

| # | Item | How checked |
|---|---|---|
| 1 | Acceptance criteria of the linked issue are met | reviewer |
| 2 | Tests written or updated first; every bug fix has a regression test | reviewer reads tests first |
| 3 | Package checks pass: lint, types, tests, isolation (`uv run python scripts/check.py --package <name>`) | CI `lint`, `types`, `tests`, `isolation` |
| 4 | **Determinism:** engine changes pass `uv run python scripts/check.py --determinism` (pipeline twice, identical hashes) | CI `determinism` |
| 5 | **Isolation:** no LLM/HTTP/`socket`/`torch`/`transformers` imports in engines 1–7, 9; no wall clock, unseeded randomness or unsorted iteration in analysis code | CI `isolation` + reviewer |
| 6 | **Lane:** every changed file is in the author's lane or shared paths, or the `cross-lane` label is approved | CI `lanes` |
| 7 | No contract shape changed in code; no invented fields, columns or enum values; generated code in sync | CI `contracts-in-sync` + reviewer |
| 8 | **Fragment:** `changes/<issue>.<type>.md` added | CI `changelog` |
| 9 | **Docs:** specs, config docs and commands updated in the same PR when behaviour changes (§13); links valid | reviewer + CI `docs` |
| 10 | Agent files in sync (`AGENTS.md` changes, skills) | CI `agent-files` |
| 11 | **Pasted output:** the PR body contains the real output of the check commands that were run | reviewer |
| 12 | ≤ 400 changed lines excluding fixtures and generated code | reviewer |
| 13 | No data, `.parquet`/`.duckdb`, weights, `.env`, secrets or `runs/` output committed | reviewer (+ `.gitignore`) |
| 14 | Labels `lane:*`, `type:*`, `agent:*`; Conventional Commit title; rebased on `main` | reviewer + branch protection (up to date) |
| 15 | Console changes: `pnpm -C console check` passes | CI `console` |

### 3.3 Definition of Done for a milestone

All exit criteria in [07 §1](07-roadmap.md#1-phases-and-milestones) hold on `main` at the Sunday review, the scorecard is posted, open issues are moved or cut with an ADR line, and the tag is pushed (§8).

## 4. Testing strategy

Most tests are fast and deterministic and run on every PR; real-data tests run on laptops because benchmark data is never committed.

| Level | What it proves | Where | Tool | Runs |
|---|---|---|---|---|
| Unit | functions do what the docstring says | `packages/<name>/tests/` | pytest | CI `tests` |
| Golden / snapshot | outputs on `synth-01…05` equal the reviewed fixtures | `packages/<name>/tests/`, fixtures in `packages/<name>/fixtures/<case>/` | pytest + `veyltrace_core.testing.golden(contract, case)` | CI `tests` |
| Property-based | numeric code holds invariants (row-order invariance, monotonicity, NaN handling) | `packages/<name>/tests/` | hypothesis (CI profile with `derandomize=True` so runs repeat) | CI `tests` |
| Contract round-trip | JSON Schema → generated Pydantic/TS → JSON → schema validates; generated code matches schemas | `contracts/`, `tests/` | pytest, `scripts/gen_contracts.py` | CI `contracts-in-sync` |
| Determinism | two pipeline runs give identical output hashes on `synth-01` + one small real case ([02 §9](02-architecture.md#9-cross-cutting-rules)) | `tests/` | `scripts/check.py --determinism` | CI `determinism` |
| Isolation / import ban | engines 1–7, 9 import no LLM, HTTP, `socket`, `torch`, `transformers` (single exemption: `veyltrace_infralume.fetch`, stdlib `urllib` only, never imported by `api.py`; [02 §9](02-architecture.md#9-cross-cutting-rules)): fresh-interpreter `sys.modules` check + AST scan | `tests/test_isolation.py` | pytest | CI `isolation` |
| Integration per lane | a lane's engines work together on fixtures | `tests/integration/test_<lane>_*.py` | pytest | CI `tests` |
| End-to-end, synthetic | `veyltrace diagnose --dataset synth --case synth-0N --ai off` writes every artifact of [02 §4.1](02-architecture.md#41-run-directory), schema-valid | `tests/` | pytest | CI `tests` |
| Real-case smoke | 3 RE2 cases run end to end within the performance budget | laptop | `veyltrace diagnose`, `veyltrace bench run` | Wednesday integration check |
| Replay | `veyltrace replay` reproduces `verdict_hash`; strict cassette mode fails on unrecorded LLM calls; replay exit codes | `packages/causivra/tests/`, `packages/llm/tests/` | pytest + recorded cassettes | CI `tests` |
| Console | components and types | `console/` | vitest, `tsc --noEmit`, eslint via `pnpm -C console check` | CI `console` |

Rules:

- Test first; every acceptance criterion maps to at least one test or command output. No coverage-percentage gate: it rewards the wrong tests.
- No network in tests. LLM calls use `FakeProvider` or recorded cassettes in strict mode ([verified_agents_local_llms §Q3][llm3]).
- Fixture changes are produced only by `--update-golden` and reviewed like code; a PR that changes fixtures says why for each file.
- Never weaken a test to make it pass ([AGENTS.md §4.7](../AGENTS.md#4-never)). A flaky test is a P0 bug.

## 5. CI gates

Workflow: [.github/workflows/ci.yml](../.github/workflows/ci.yml). Runs on every PR and every push to `main`, on `ubuntu-latest` only.

### 5.1 Jobs

| Job (= required check name) | Runs when | Command | Checks |
|---|---|---|---|
| `lanes` | PRs (also on label changes) | `uv run scripts/check_lanes.py --author <login> --labels "<labels>" --base origin/<base>` and `--verify-codeowners` | changed files inside the author's lane or `cross-lane` label; `CODEOWNERS` generated from `lanes.yml` |
| `agent-files` | always | `uv run --no-project python scripts/sync_agent_files.py --check` | `.claude/skills` = `.agents/skills`; nested `CLAUDE.md` beside every nested `AGENTS.md`; no duplicate rule files; size limits |
| `docs` | always | `uv run --no-project python scripts/check_links.py` | relative links and `#anchors` in every `*.md` |
| `lint` | workspace exists and non-doc files changed | `uv run python scripts/check.py --lint` | ruff check + ruff format check |
| `types` | same | `uv run python scripts/check.py --types` | pyright (strict in engines) |
| `tests` | same | `uv run python scripts/check.py --tests` | pytest: unit, golden, property, integration, e2e synth, replay |
| `isolation` | same | `uv run python scripts/check.py --isolation` | import ban (§4) |
| `determinism` | same | `uv run python scripts/check.py --determinism` | two runs, identical hashes |
| `contracts-in-sync` | same | `uv run python scripts/check.py --contracts-in-sync` | regenerate contracts; fail on any diff |
| `changelog` | PRs, workspace exists | `uv run python scripts/check.py --changelog --base origin/<base>` | a valid fragment for this PR |
| `console` | `console/package.json` exists and `console/` or `contracts/` changed | `pnpm -C console install --frozen-lockfile` then `pnpm -C console check` | tsc, eslint, vitest |

"Workspace exists" means `pyproject.toml` is at the repo root (lands in R-02). Until then the code jobs are skipped, which lets the CI file merge before the code it checks.

### 5.2 `scripts/check.py` (written by the lead in R-02)

CI and humans call the same script, so a green local run predicts a green CI run. It must support:

| Flag | Does | Notes |
|---|---|---|
| `--package <name>` | lint + types + tests + isolation for one package | the default local check ([AGENTS.md §6](../AGENTS.md#6-commands)) |
| `--lint` | `ruff check` and `ruff format --check` on all Python | no auto-fix in CI |
| `--types` | pyright over the workspace (strict in engine packages) | |
| `--tests` | pytest over all packages and `tests/`, hypothesis CI profile | `-x` off; print a summary line |
| `--isolation` | `tests/test_isolation.py` | deny-list from [02 §9](02-architecture.md#9-cross-cutting-rules) |
| `--determinism` | run the pipeline twice on `synth-01` and one small real case (or its committed fixture form), compare all artifact hashes, print the first differing artifact | AI off |
| `--contracts-in-sync` | run `scripts/gen_contracts.py` into a temp dir, diff against `contracts/generated/` | exit 1 on any difference |
| `--changelog [--base <ref>]` | the PR adds exactly one `changes/<issue>.<type>.md` with a known type and one sentence; a release PR that modifies `CHANGELOG.md` is exempt | issue number matches `Closes #N` if it can read the PR body (optional) |
| `--update-golden` (with `--package`) | regenerate that package's fixtures from the current code | never in CI |

Conventions: exit 0 = pass, 1 = check failed, 2 = usage error; one summary line per check (`OK lint`, `FAIL tests (3 failed)`), so the tail is easy to paste into a PR; stdlib plus workspace dev tools only.

### 5.3 Platform, path filters, caching, cost

- **Linux only.** Windows runners cost more and are not needed; line endings are normalised by `.gitattributes`, so Linux CI sees the same bytes ([stack_and_market §A6][a6]).
- **Public repo → standard runners are free.** If the repo ever turns private, the Free plan includes $12 of compute a month (about 2,000 Linux minutes); path filters and caching then matter ([§Q4][q4]).
- **Path filters per job, not per workflow.** A workflow skipped by `on: paths:` never reports its checks, so required checks would wait forever. Instead a `detect` job decides, and jobs skip with `if:`. Docs-only PRs (`docs/`, `changes/`, `research_notes/`, `reports/`, `paper/`, `*.md`) skip the Python jobs; the console job runs only for `console/` or `contracts/` changes. Pushes to `main` run everything. GitHub reports a job skipped by `if:` as passing for branch protection (**verify** once on the repo).
- **Caching.** `astral-sh/setup-uv` with `enable-cache: true` (keyed on `uv.lock`); pnpm store via `actions/setup-node` `cache: pnpm`. Cache limit 10 GB per repo ([§A6][a6]).
- **Concurrency.** One run per PR; a new push cancels the old run.
- **Action versions** are pinned to major tags (`actions/checkout@v5`, `astral-sh/setup-uv@v6`, `actions/setup-node@v4`, `pnpm/action-setup@v4`). The lead checks for newer majors at M0 (**verify** they are current).

### 5.4 Branch protection

Required checks per [08 §4.1](08-collaboration-and-git.md#41-github-settings-lead-task-l-00): `lanes`, `agent-files`, `docs`, `lint`, `types`, `tests`, `isolation`, `determinism`, `contracts-in-sync`, `changelog`, `console` (jobs skipped by the `detect` job count as passing; verify once on the first PR). Plus: 1 approval, review from Code Owners, branch up to date before merging (the substitute for merge queue, which personal-account repos do not have), linear history, conversation resolution, no force pushes, auto-merge allowed.

### 5.5 Local hooks

The lead adds `.pre-commit-config.yaml` in R-02 (ruff, ruff-format, end-of-file and trailing-whitespace fixers, a guard against edits under `contracts/generated/`). Install once per worktree with `uv run pre-commit install`. Never bypass with `--no-verify` ([AGENTS.md §4.7](../AGENTS.md#4-never)).

## 6. Code review checklist

The reviewer is a human, even when an agent wrote the code. Read in this order: issue → tests → code → docs.

- [ ] **Scope:** the PR does what the issue asks and nothing else; no drive-by refactors.
- [ ] **Lane:** files are in the author's lane; `cross-lane` only with the lead's approval and the owning lane reviewing.
- [ ] **Contracts:** every field, column, key and enum value written exists in [03](03-contracts.md); reads and writes go through contract loaders and writers.
- [ ] **Determinism:** no wall clock, unseeded randomness, unsorted set/dict/glob iteration, unordered parallel results, environment-dependent values in artifacts.
- [ ] **Isolation:** no LLM/HTTP/`socket`/`torch`/`transformers` imports in engines 1–7, 9; ground truth only in `bench/` and `lab/`.
- [ ] **Config:** every threshold is a named key in `config/<engine>.yaml` with a source or "a priori".
- [ ] **Tests:** the tests would fail without the change; each acceptance criterion is covered; fixture diffs are explained; nothing skipped, loosened or `# type: ignore`d without a reason.
- [ ] **Evidence:** the pasted check output is real and matches CI; re-run at least one command for agent-written PRs.
- [ ] **Docs:** spec and README updated if behaviour, outputs, config keys or commands changed.
- [ ] **Hygiene:** fragment present; ≤ 400 lines; no data, weights, secrets or `runs/`; labels set; commit title follows Conventional Commits.
- [ ] **Numbers:** any result quoted comes from `bench/results/` produced by a committed config; estimates marked *estimate*.

Comment style: say what must change and why, citing the rule or spec section. Mark optional suggestions "nit:". Approve when the blocking points are fixed; do not hold a PR for nits.

## 7. Versioning

| Thing | Scheme | When it changes |
|---|---|---|
| Repository (code, CLI) | SemVer tags `vMAJOR.MINOR.PATCH` | `v0.0.1` M0, `v0.1.0` M1, `v0.2.0` M2, `v0.3.0` M3, `v0.9.0` M4, `v1.0.0` M5 ([07 §1](07-roadmap.md#1-phases-and-milestones)); `v0.N.1` for a fix release between milestones |
| Workspace packages | same version as the repository, bumped in the release PR (proposal; lead confirms in the R-02 ADR) | each release |
| Contracts | separate: schema `$id …/<name>/<major>.<minor>`, artifacts carry `schema_version`; `0.x` until M1, `1.0` at M1 (tag `contracts-1.0`, R-07); additive = minor, breaking = major and all three lanes ([03 §1](03-contracts.md#1-how-contracts-work)) | via CCR + ADR only |
| Results | `bench/results/<experiment>/` (`per_case.csv`, `summary.json`, manifest with git SHA, config hash, seeds); the M4 freeze tag is defined in R-17 | each experiment run |
| Models and runtimes | GGUF SHA-256, llama.cpp or Ollama build, recorded in receipts | when a model is pinned or changed (ADR) |

Breaking changes before 1.0 are allowed but are named in the release notes under the fragment type that fits.

## 8. Release process

Weekly tags at the Sunday review; the full process (DOI, citation) at `v1.0.0` (L-05). Only the lead tags.

1. **Freeze.** All PRs for the milestone merged or moved; `main` green; the Wednesday integration check done; milestone exit criteria checked.
2. **Release PR** on branch `lead/<issue>-release-v0.N.0`, title `chore(release): v0.N.0`:

   ```bash
   uv run towncrier build --draft --version 0.N.0
   ```

   ```bash
   uv run towncrier build --yes --version 0.N.0
   ```

   The second command writes `CHANGELOG.md` and deletes the compiled fragments ([towncrier.toml](../towncrier.toml)). Also bump the package versions and, from `v0.9.0`, `version` and `date-released` in `CITATION.cff`. The `changelog` check exempts a PR that modifies `CHANGELOG.md`.
3. **Merge**, then tag the merge commit on `main` and push the tag:

   ```bash
   git fetch origin && git tag -a v0.N.0 origin/main -m "Veyltrace v0.N.0"
   ```

   ```bash
   git push origin v0.N.0
   ```

4. **GitHub Release** with the new `CHANGELOG.md` section as notes:

   ```bash
   gh release create v0.N.0 --verify-tag --title "Veyltrace v0.N.0" --notes-file <file with this version's section>
   ```

5. **Zenodo DOI.** One-time setup: log in to Zenodo with GitHub and switch the repository **On**; the repo must be public; each new GitHub release then gets a DOI ([§Q5][q5]). Turn it on before `v0.9.0` so the M4 release tests the flow; `v1.0.0` is the DOI the paper cites.
6. **Citation.** `CITATION.cff` at the repo root makes GitHub show "Cite this repository". Minimal fields: `cff-version: 1.2.0`, `message`, `authors`, `title`, `version`, `date-released` ([§Q5][q5]). After `v1.0.0`, a follow-up PR `docs(release): add DOI` writes the DOI into `CITATION.cff` and `README.md`.
7. **M5 extras.** `REPRODUCE.md` verified on a clean clone by a teammate who did not write it (L-06); demo video attached to the release (X-13); retrospective ADR (L-07).

## 9. Tracking

### 9.1 Projects board

One GitHub Projects board for the repo; every issue and PR is on it.

| Field | Values | Set by |
|---|---|---|
| Status | Backlog, Ready, In progress, In review, Done | owner; closing an issue moves it to Done (built-in workflow, **verify** availability) |
| Lane | Reason, Observe, Explain | mirrors the `lane:*` label |
| Milestone | M0 … M5 (repository milestones) | issue milestone |
| Size | S (≤ 0.5 day), M (≤ 1 day), L (≤ 2 days) | owner at Ready |
| Agent | Claude Code, Codex, OpenCode, Antigravity, Cursor, Copilot, Windsurf/Devin, none | PR author; mirrors the `agent:*` label |

Views: **Board** grouped by Status (daily use); **Table** grouped by Lane, filtered to the current milestone (Sunday review); **Roadmap** by Milestone (planning). Projects free-tier limits were not verified ([§Q4 gaps][q4]).

### 9.2 Labels

Source of truth: [.github/labels.yml](../.github/labels.yml). Apply with `uv run scripts/sync_labels.py --apply` (lead, L-00; dry run without `--apply`). We sync labels with a script, not a workflow, because it runs once with the lead's own `gh` login and needs no workflow permissions.

| Group | Labels | Rule |
|---|---|---|
| Lane | `lane:reason`, `lane:observe`, `lane:explain` | one per issue and PR (team tasks: all three) |
| Type | `type:feat`, `type:fix`, `type:bug`, `type:chore`, `type:exp`, `type:paper`, `type:adr`, `type:docs`, `type:question` | one per issue and PR; `type:bug` = defect report, `type:fix` = PR fixing it |
| Agent | `agent:claude`, `agent:codex`, `agent:opencode`, `agent:antigravity`, `agent:cursor`, `agent:copilot`, `agent:windsurf`, `agent:none` | one per PR |
| Priority | `priority:P0`, `priority:P1`, `priority:P2` | bugs and at-risk tasks |
| Flow | `cross-lane`, `blocked`, `frozen-contract`, `good-first-task`, `risk`, `post-v1` | as needed; `cross-lane` only with lead approval; `risk` for a fired risk ([12](12-risks.md)); `post-v1` for ideas outside [07](07-roadmap.md) |

Roadmap issues and milestones are created by `python scripts/create_issues.py --apply` after the labels exist (the default is a dry run).

### 9.3 Milestones

| Milestone | Due | Tag |
|---|---|---|
| M0 Ground ready | Tue 3 Nov | `v0.0.1` |
| M1 Contracts frozen | Sun 8 Nov | `v0.1.0` |
| M2 AI-off scored | Sun 15 Nov | `v0.2.0` |
| M3 AI-on, live | Sun 22 Nov | `v0.3.0` |
| M4 Results frozen | Sun 29 Nov | `v0.9.0` |
| M5 v1.0.0 | Tue 1 Dec | `v1.0.0` |

### 9.4 Weekly metrics

Posted by the lead at the Sunday review as a comment on the week's tracking issue. Each number comes from a command, not from memory.

| Metric | Definition | Source |
|---|---|---|
| PRs merged | count, per lane and per agent | `gh pr list --state merged --search "merged:>=<monday>" --json number,labels` |
| Cycle time | median hours from PR opened to merged | same export, `createdAt` → `mergedAt` |
| CI pass rate | share of PR runs green on first push; share of `main` runs green | `gh run list --workflow ci.yml --json conclusion,event,headBranch` |
| Conflicts | rebase conflicts reported in PR Risks lines (`conflict:`), structural vs textual | PR bodies |
| Open P0/P1 | count at the review | `gh issue list --label priority:P0 --state open` |
| Milestone progress | closed / total issues in the current milestone | milestone page |
| Scorecard | AC@1/3/5, Avg@5, Retrieval@5 on synth + 3 real cases, vs last week | Wednesday integration check, `bench/results/` |

These numbers also feed the paper's methods and threats-to-validity sections ([09 §7.1](09-ai-agent-playbook.md#71-recording-agent-usage-for-the-paper)).

## 10. Meetings

| When | What | Format |
|---|---|---|
| Daily, by 22:00 IST | async standup | comment on the week's tracking issue (below) |
| Wednesday | integration check (lead) | e2e on `synth-01…05` + 3 real cases at `main` HEAD; scorecard + breakage issues |
| Sunday | milestone review, 45 min video call | agenda below; tag `v0.N.0` |
| Sunday (last 10 min) and L-07 | retrospective | Keep / Change / Try |

**Tracking issue.** Each Sunday the lead opens `Week <n> tracking (<milestone>)`, pins it, and closes last week's.

**Standup comment** (three lines, no prose):

```text
Done: #14 merged (Drain3 templates); #15 PR open, waiting review.
Next: #16 error rates per template.
Blocked: none | blocked by #9 (needs anomalies fixture for synth-04)
```

**Wednesday integration check** (lead): pull `main`; `uv sync --all-packages`; run `veyltrace diagnose` on `synth-01…05` and the 3 agreed RE2 cases; run the determinism gate; compare the scorecard with last week; re-check the critical path ([07 §1.2](07-roadmap.md#12-critical-path)); open a `type:bug` issue per breakage with the owning lane's label; post a summary on the tracking issue.

**Sunday review agenda (45 min):** demo of what merged (15) · scorecard and metrics vs last week (10) · risks, slips, cut-list decisions (10) · next week's issues assigned and moved to Ready (10). Then the lead tags the release (§8).

**Retrospective** (10 min weekly; 45 min at L-07): each person writes up to three items under Keep, Change, Try, plus one answer to "What did the agent get wrong this week, and which rule or template would have prevented it?". Each Change/Try item becomes an issue with an owner, or is dropped explicitly. L-07 records the final retro and the post-month plan as an ADR.

## 11. Decision records (ADR)

**When to write one:** a choice between technologies or designs; any contract change after M1; a cut-list item; a deviation from [02](02-architecture.md); pinning a version listed as an open decision ([02 §12](02-architecture.md#12-open-decisions-tracked-as-adrs)).

**Where:** `docs/adr/YYYYMMDD-<initials>-<slug>.md` (initials `ak`, `as`, `cl`). Date-prefixed names, not sequence numbers, so two branches never pick the same number ([§Q3][q3]). ADR files are author-owned shared paths in `lanes.yml`.

**Process:** draft with status `Proposed` in a PR labelled `type:adr` (fragment type `doc`) → discuss in the PR → the lead approves (breaking contract changes: all three lanes) → status `Accepted` on merge. An accepted ADR is never rewritten: a later ADR supersedes it, and the old one gets a single "Superseded by" line. Prompt for agents: [09 §5.7](09-ai-agent-playbook.md#57-write-an-adr).

**Template:** copy [docs/adr/_template.md](adr/_template.md) into the new file; statuses, naming and the supersede rule are in [docs/adr/README.md](adr/README.md). Every ADR lists at least two options, including "do nothing", and marks estimates as *estimate*.

## 12. When `main` is red

A failing CI run on `main` blocks everyone, because "branch up to date" forces every PR to include the breakage.

1. **Notice.** Anyone who sees a red `main` run posts the run link on the week's tracking issue and opens a `type:bug`, `priority:P0` issue.
2. **Revert within 2 hours** ([08 §9](08-collaboration-and-git.md#9-when-things-go-wrong)). The author of the breaking PR uses the **Revert** button on the merged PR (or `git revert <sha>` on a branch `<lane>/<issue>-revert`) and opens the revert PR; any teammate approves it as soon as checks pass. If the author is unreachable, the lead reverts.
3. **No other merges** until `main` is green again.
4. **Fix forward** in a new PR with a regression test.
5. **Write down why CI did not catch it** in the bug issue, one paragraph: cause, why the PR was green (not up to date, job skipped by a path filter, flaky test, laptop-only data), and the prevention (new test, filter change, check in `scripts/check.py`).

A flaky test is treated the same way: it is a P0 bug in the test or the code, never skipped.

## 13. Documentation upkeep

- **Spec changes go in the same PR as the code.** If a PR changes behaviour, outputs, config keys, CLI flags or commands, it updates the engine spec in `docs/engines/`, the package README and, for commands, asks the lead to update AGENTS.md §6. Contract changes go through a CCR (they touch [03](03-contracts.md), which the lead owns).
- **Ownership follows lanes.** Lanes edit their own engine docs (`docs/engines/NN-*.md`) and `docs/05`/`docs/06` (Explain); shared docs and `docs/README.md` belong to the lead. Others propose changes with a `type:question` or `type:docs` issue. `paper/` (LaTeX) belongs to the lead, except `paper/sections/observe-*` and `paper/sections/explain-*`, which those lanes own and edit without the `cross-lane` label ([08 §3](08-collaboration-and-git.md#3-repository-layout-and-who-owns-what)).
- **[02](02-architecture.md) wins disagreements.** Anyone who finds two docs disagreeing files a `type:question` issue; the losing doc is fixed in a PR.
- **Headers.** Each doc keeps its `Status · Owner · Last updated` line current.
- **Links** are relative within the repo and checked in CI (`docs` job, `scripts/check_links.py`).
- **Agent instruction files.** `AGENTS.md` changes need the lead's approval; after one merges, everyone restarts their agent sessions (Codex, for example, builds its instruction chain once per session).
- **Bug bash and docs review** on Thu 26 Nov (L-04): every doc is read against the code; mismatches become issues.

[q3]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/multi_agent_dev_and_sdlc.md#q3-how-do-we-avoid-merge-conflicts-and-drift-with-three-different-ai-agents-working-in-parallel
[q4]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/multi_agent_dev_and_sdlc.md#q4-how-should-a-tiny-team-track-the-sdlc-on-github-free
[q5]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/multi_agent_dev_and_sdlc.md#q5-what-does-research-paper-readiness-require-reproducibility-artifacts-citation-licences-venues-and-arxiv
[a6]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/stack_and_market.md#a6-packaging-reproducibility-and-ci-on-the-github-actions-free-tier
[llm3]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/verified_agents_local_llms.md#q3-determinism-and-replay-with-llms-what-is-achievable-on-cpu-vs-gpu
