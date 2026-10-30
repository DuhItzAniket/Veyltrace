<!--
Title = the main commit message, e.g. feat(signalyth): add critical-path share (#14)
Labels: one lane:*, one type:*, one agent:* (agent:none if no AI agent).
Rules: AGENTS.md, docs/08-collaboration-and-git.md §4, Definition of Done in docs/10-sdlc-and-quality.md §3.
-->

## Summary

<!-- 1–3 sentences: what changed and why. -->

Closes #

| | |
|---|---|
| **Lane** | reason / observe / explain |
| **Type** | feat / fix / chore / exp / docs / adr / paper |
| **Agent used** | tool + model (e.g. Claude Code, Opus 4.x; Codex CLI, GPT-5.x; none) |
| **Contract / ADR** | none, or link to CCR issue / `docs/adr/...` |

## Definition of Done

- [ ] Acceptance criteria of the linked issue are met (quote any that are not, and why)
- [ ] Tests written or updated first; every bug fix has a regression test
- [ ] `scripts/check.py --package <name>` passes (lint, types, tests, isolation); output pasted below
- [ ] Engine change: `scripts/check.py --determinism` passes; output pasted below (or N/A)
- [ ] Console change: `pnpm -C console check` passes; output pasted below (or N/A)
- [ ] No banned imports in engines 1–7, 9; no wall clock, unseeded randomness or unsorted iteration in analysis code
- [ ] All edits inside my lane (`uv run scripts/check_lanes.py --lane <lane>` output pasted), or `cross-lane` label approved by the lead
- [ ] No contract shape changed in code; no invented fields, columns or enum values
- [ ] No data, `.parquet`/`.duckdb`, weights, `.env`, secrets or `runs/` output committed
- [ ] Fragment added: `changes/<issue>.<type>.md`
- [ ] Docs/specs changed in this PR if behaviour, config keys or commands changed
- [ ] Changed `AGENTS.md`, `.agents/` or Markdown: `uv run --no-project python scripts/sync_agent_files.py --check` and `uv run --no-project python scripts/check_links.py` pass (or N/A)
- [ ] ≤ 400 changed lines excluding `fixtures/` and `contracts/generated/` (or split agreed)
- [ ] Rebased on `origin/main`; Conventional Commit title

## Check output

<!-- Paste the real tail of each command you ran. A reviewer may re-run them. "Tests pass" without output is not accepted. -->

```text
$ uv run python scripts/check.py --package <name>

```

```text
$ uv run python scripts/check.py --determinism

```

```text
$ uv run scripts/check_lanes.py --lane <lane>

```

## Handoff

- **Done:**
- **Next:**
- **Risks:**
