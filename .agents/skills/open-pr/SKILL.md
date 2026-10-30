---
name: open-pr
description: Finish a Veyltrace task and open a pull request - run the checks, add the towncrier fragment, commit with Conventional Commits, and fill the PR template with pasted command output, labels and a handoff. Use when the issue's acceptance criteria are met.
---

# Open a pull request

Rules: `AGENTS.md` §3 steps 5–9 and §4. Definition of Done: `docs/10-sdlc-and-quality.md` §3.
Template: `.github/pull_request_template.md`.

1. **Rebase:** `git fetch origin && git rebase origin/main`. Resolve conflicts only in your lane's
   paths; a conflict elsewhere means your branch touched another lane by mistake — revert that part.
   Lockfile conflict: `git checkout origin/main -- uv.lock && uv lock && git add uv.lock`.
2. **Run the checks and keep the output** (copy the last lines of each):
   - `uv run python scripts/check.py --package <name>`
   - `uv run python scripts/check.py --determinism` (engine changes)
   - `uv run scripts/check_lanes.py --lane <lane>`
   - `pnpm -C console check` (console changes)
   - `uv run --no-project python scripts/sync_agent_files.py --check` and
     `uv run --no-project python scripts/check_links.py`
     (if you changed `AGENTS.md`, `.agents/` or any `.md` file)
   If a check fails, fix the cause. Never weaken a test, skip a check or add an unexplained
   `# type: ignore`/`noqa`. Never claim a check passed without running it.
3. **Size:** `git diff --stat origin/main...HEAD`. Over 400 changed lines (excluding `fixtures/`
   and `contracts/generated/`): stop and propose a split.
4. **Fragment:** `changes/<N>.<feat|fix|doc|perf|chore|exp>.md`, one sentence, past tense,
   user-visible effect. Rules: `changes/README.md`.
5. **Commit:** `<type>(<package>): <summary> (#N)`, e.g. `feat(signalyth): add critical-path share (#14)`.
6. **Open the PR** (human approves the push if your tool asks):
   ```bash
   git push -u origin HEAD
   gh pr create --title "<commit subject>" --body-file <filled template> --label lane:<lane> --label type:<type> --label agent:<tool>
   ```
   In the body: `Closes #N`, the ticked Definition of Done, the **pasted** check output,
   and the 3-line handoff (done / next / risks).
7. **Stop.** Do not merge, do not start unrequested refactors.
