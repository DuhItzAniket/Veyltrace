# changes/ — changelog fragments

Every PR adds exactly one fragment here. Nobody edits `CHANGELOG.md` by hand: at release the lead runs `towncrier build`, which compiles the fragments into `CHANGELOG.md` and deletes them ([towncrier.toml](../towncrier.toml), [10-sdlc-and-quality §8](../docs/10-sdlc-and-quality.md#8-release-process)). One file per PR means two PRs never edit the same line, so the changelog never conflicts ([08 §3.1](../docs/08-collaboration-and-git.md#31-hot-spots-removed-by-design)).

## File name

`changes/<issue>.<type>.md` — `<issue>` is the GitHub issue number the PR closes; `<type>` is one of:

| Type | Use for | PR label | Commit type |
|---|---|---|---|
| `feat` | new capability a user or another lane can see | `type:feat` | `feat` |
| `fix` | a bug fix (link the bug issue) | `type:fix` | `fix` |
| `perf` | faster or smaller with the same output | `type:feat` or `type:fix` | `perf` |
| `exp` | an experiment run or result table from a committed config | `type:exp` | `exp` |
| `doc` | docs, ADRs, paper text | `type:docs`, `type:adr`, `type:paper` | `docs` |
| `chore` | CI, tooling, dependencies, repo setup | `type:chore` | `chore` |

Examples: `changes/14.feat.md`, `changes/31.fix.md`, `changes/52.exp.md`.

## Content

One sentence, past tense, saying what changed for the reader of the release notes. No issue number (towncrier adds the link), no file lists, no "this PR".

```text
Signalyth now writes the critical-path share per service and window.
```

```text
Fixed Anomara onsets shifting by one step when a series starts with missing values.
```

## Rules

- One fragment per PR. A PR that closes two issues is two PRs.
- The fragment's issue number matches `Closes #N` in the PR body. The CI `changelog` job checks that a fragment exists.
- Fragments are author-owned shared paths (`.github/lanes.yml` `shared`), so any lane may add one.
- Preview what the release notes will look like: `uv run towncrier build --draft --version 0.0.0`.
