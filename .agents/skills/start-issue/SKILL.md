---
name: start-issue
description: Start work on one Veyltrace GitHub issue - confirm the issue and lane, create an isolated git worktree and branch, and read the required docs before writing code. Use at the beginning of every coding session.
---

# Start an issue

Rules: `AGENTS.md` §2–§4 (binding). Full protocol with examples: `docs/09-ai-agent-playbook.md` §4.

1. **Get the issue number and lane.** If the human has not given `#N`, ask. Read it:
   `gh issue view N --comments`. Note its acceptance criteria, `lane:*` label and milestone.
   If the issue's lane is not the human's lane, stop and say so.
2. **Isolate.** From the main clone (not from another worktree):
   ```bash
   git fetch origin
   git worktree add ../vt-N -b <lane>/N-<slug> origin/main
   ```
   `<slug>` is 2–4 lowercase words joined by hyphens. Then work only inside `../vt-N`.
   Claude Code may use `claude --worktree N-<slug>` instead, then rename the branch:
   `git branch -m <lane>/N-<slug>`.
3. **Read before writing**, in this order: `AGENTS.md` → `packages/<name>/AGENTS.md` (if any)
   → the engine spec `docs/engines/NN-<engine>.md` → only the sections of
   `docs/02-architecture.md` and `docs/03-contracts.md` it links. Do not open `_hackday-v1/`
   or any `answer_key` file.
4. **List your edit set.** Write down the paths you expect to change and check each is in your
   lane (`.github/lanes.yml`). Anything outside: stop and tell the human.
5. **Restate the plan** to the human in ≤ 5 lines: acceptance criteria, files, tests you will
   write first, the check commands you will run. Wait for a go-ahead if anything is unclear.
6. **Missing command?** Commands built in M0 (`scripts/check.py`, `veyltrace ...`) may not exist
   before 2026-11-03. Say so; do not improvise a replacement.
