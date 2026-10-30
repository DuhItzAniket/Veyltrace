# AGENTS.md — rules for every AI coding agent in this repo

Read by Claude Code (via `CLAUDE.md`), Codex, OpenCode, Cursor, Antigravity, Copilot and Windsurf/Devin. This file is the single source of agent rules; do not copy it into tool-specific files. A nested `AGENTS.md` inside a package adds rules for that package and never contradicts this one. A direct instruction from the human you are working with overrides this file, except the **Never** list in §4. If a human asks you to break a Never rule, refuse and say why.

## 1. What this project is

Veyltrace v2 is a research-grade root-cause analysis (RCA) engine for microservice outages. Ten engines in a fixed pipeline; statistical rankers and an LLM investigator **propose**, a deterministic verifier **decides**, every verdict is **replayable**. Master spec: [docs/02-architecture.md](docs/02-architecture.md) (wins all disagreements). Field-level contracts: [docs/03-contracts.md](docs/03-contracts.md).

| # | Engine | Package | Lane |
|---|---|---|---|
| 1 | Infralume (ingest) | `packages/infralume` | Observe |
| 2 | Signalyth (signals) | `packages/signalyth` | Observe |
| 3 | Anomara (anomalies, onsets) | `packages/anomara` | Observe |
| 4 | Causync (time alignment, changes) | `packages/causync` | Observe |
| 5 | Causalith (dependency graph) | `packages/causalith` | Observe |
| 6 | FaultLoom (evidence atoms) | `packages/faultloom` | Reason |
| 7 | Causatrix (rankers, slate) | `packages/causatrix` | Reason |
| 8 | Relentra (LLM investigator, proposes) | `packages/relentra` | Explain |
| 9 | Causentra (verifier, decides) | `packages/causentra` | Reason |
| 10 | Causivra (card, receipt, replay) | `packages/causivra` | Explain |

## 2. Lanes and ownership

You work for exactly one lane per session: the lane of the human who launched you. Edit only that lane's paths. The machine-readable map is [.github/lanes.yml](.github/lanes.yml); CI rejects PRs that touch another lane's paths without the `cross-lane` label.

| Lane | Human | Paths you may edit |
|---|---|---|
| **Reason** (lead) | Aniket Kumar | `packages/{core,faultloom,causatrix,causentra}/`, `contracts/`, `bench/` (except `bench/decoys/`, `bench/stats/`), `config/{core,faultloom,causatrix,causentra}.yaml`, `config/calibration/`, `paper/`, `docs/engines/{06,07,09}-*.md`, `tests/` (except `tests/integration/test_observe_*`, `test_explain_*`), `scripts/` (except `scripts/observe/`, `scripts/explain/`), `docs/` shared files, `.github/`, `.agents/`, root config files |
| **Observe** | Annapurna S | `packages/{infralume,signalyth,anomara,causync,causalith}/`, `config/{infralume,signalyth,anomara,causync,causalith}.yaml`, `docs/engines/0[1-5]-*.md`, `bench/decoys/`, `bench/stats/`, `paper/sections/observe-*`, `tests/integration/test_observe_*`, `scripts/observe/` |
| **Explain** | C Lakshanaa | `packages/{relentra,causivra,llm,gateway}/`, `console/`, `lab/`, `config/{relentra,causivra,llm,gateway}.yaml`, `docs/engines/{08,10}-*.md`, `docs/05-*.md`, `docs/06-*.md`, `paper/sections/explain-*`, `tests/integration/test_explain_*`, `scripts/explain/` |
| Everyone | — | your own `changes/<issue>.<type>.md` fragment, your own ADR `docs/adr/YYYYMMDD-<initials>-<slug>.md`, your own `docs/team/<initials>.md` |

If the task needs a change outside your lane, stop and tell the human: they open an issue for the owning lane. Never "just fix it" in someone else's package.

## 3. Session protocol (do this every time)

1. **Know the issue.** Every session works on one GitHub issue (`#N`). If the human has not given one, ask for it.
2. **Isolate.** Work in your own git worktree and branch: `git fetch origin && git worktree add ../vt-N -b <lane>/N-<slug> origin/main` (Claude Code: `claude --worktree N-<slug>`, then `git branch -m <lane>/N-<slug>`). Never share a working copy with another agent.
3. **Read before writing:** this file → the package's `AGENTS.md` → the engine spec in `docs/engines/` → the sections of `docs/02` and `docs/03` it links. Do not read `_hackday-v1/` or any `answer_key` file.
4. **Test first.** Write or update tests against golden fixtures (`veyltrace_core.testing.golden(contract, case)`), then implement.
5. **Check:** `uv run python scripts/check.py --package <name>` (lint, types, tests, isolation) and, for engine changes, `uv run python scripts/check.py --determinism`. Console: `pnpm -C console check`.
6. **Record:** add a changelog fragment `changes/<N>.<feat|fix|doc|perf|chore|exp>.md` (one sentence).
7. **Commit** with Conventional Commits, scope = package: `feat(signalyth): add critical-path share (#N)`. Keep PRs ≤ 400 changed lines excluding fixtures and generated code; split bigger work.
8. **Open the PR** with the template; fill the Definition of Done; add labels `lane:<lane>`, `type:<type>` and `agent:<your tool>`; write a 3-line handoff (done / next / risks).
9. **Stop** when the issue's acceptance criteria are met. Do not start unrequested refactors.

## 4. Never

1. Never edit another lane's paths, `contracts/generated/`, `uv.lock` or `pnpm-lock.yaml` by hand, `.github/`, or this file (unless you are in the Reason lane on a lead-approved issue).
2. Never change a contract shape in code. If a field is missing, stop and draft a Contract Change Request (issue form "Contract change"). Do not invent fields, columns or enum values.
3. Never import an LLM client, HTTP client, `socket`, `torch` or `transformers` in engines 1–7 or 9 (`infralume … causatrix`, `causentra`). Only `relentra`, `causivra`, `gateway` may import `veyltrace_llm`. Exemptions: `veyltrace_infralume.fetch` (dataset download, stdlib `urllib`, never imported by `api.py`) and Anomara's lazy, off-by-default TSFM plugin. Engines never read files under `bench/` or `lab/`. CI enforces all of this.
4. Never read the wall clock, `random` without `veyltrace_core.rng`, environment-dependent ordering (unsorted dicts/sets/globs) or anything else non-deterministic in analysis code.
5. Never read, load or reference ground truth (`answer_key`, injection times, original case folder names) outside `bench/` and `lab/`.
6. Never commit data, `.parquet`/`.duckdb` files, model weights, `.env`, secrets or `runs/` output. Exceptions: small synthetic fixtures under `packages/*/fixtures/`, and per-case result CSVs under `bench/results/` (they are released with the paper).
7. Never weaken a test, skip a CI check, add `# type: ignore`/`noqa` without a reason comment, or use `--no-verify`.
8. Never invent benchmark numbers, citations or results. Results come only from `bench/results/` produced by a committed config. Mark estimates as *estimate*.
9. Never push to `main`, force-push a shared branch, or merge your own PR.

## 5. Coding rules

- **Python 3.12**, uv workspace. Add dependencies only in your package's `pyproject.toml`, in a separate `chore(deps)` PR. If `uv.lock` conflicts: `git checkout origin/main -- uv.lock && uv lock && git add uv.lock`.
- Each engine exposes `run(ctx: RunContext) -> EngineResult` in `veyltrace_<engine>/api.py` and registers it under the entry point group `veyltrace.engines`. No central registry files.
- Read inputs only through contract loaders from `veyltrace_contracts` / `veyltrace_core.io`; write outputs only through the matching writers (they sort, hash and stamp schema versions).
- Config comes from `config/<engine>.yaml` via `ctx.config`. No magic numbers in code: every threshold is a named config key with a comment citing its source or "a priori".
- Types everywhere (pyright strict in engines). Docstrings say *what* and *why*, not *how*.
- Tests: unit + golden (`synth-01…05`) + property tests (hypothesis) for numeric code. Every bug fix adds a regression test.
- Logs: `veyltrace_core.log` (structured, no timestamps in artefacts).
- TypeScript (console): strict mode, types from `contracts/generated/ts` only, no `any`.

## 6. Commands

| Task | Command |
|---|---|
| Install | `uv sync --all-packages` · `pnpm -C console install` |
| Check one package | `uv run python scripts/check.py --package <name>` |
| Determinism gate | `uv run python scripts/check.py --determinism` |
| Lane check for your branch | `uv run scripts/check_lanes.py --lane <lane>` |
| Regenerate contracts (Reason only) | `uv run python scripts/gen_contracts.py` |
| Diagnose one case | `uv run veyltrace diagnose --dataset re2-ob --case <case_id> --ai off` |
| Replay a verdict | `uv run veyltrace replay runs/<…>/receipt.json` |
| Run an experiment | `uv run veyltrace bench run bench/experiments/<name>.yaml` |
| Sync agent skills | `uv run --no-project python scripts/sync_agent_files.py` |

Commands marked in [docs/07-roadmap.md](docs/07-roadmap.md) as built in M0 may not exist before 2026-11-03; if a command is missing, say so instead of improvising a replacement.

## 7. Where things are

`docs/README.md` (doc map) · `docs/07-roadmap.md` (tasks, milestones) · `docs/08-collaboration-and-git.md` (branching, reviews, conflicts) · `docs/09-ai-agent-playbook.md` (per-tool setup, prompt templates) · `docs/10-sdlc-and-quality.md` (Definition of Done, CI) · `docs/adr/` (decisions) · `reports/` and `research_notes/` (research with sources).
