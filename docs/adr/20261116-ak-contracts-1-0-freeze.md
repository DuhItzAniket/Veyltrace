# Contracts freeze at 1.0 after the open engine stacks merge, after prereg-v1 and before R-11

- **Status:** Proposed
- **Date:** 2026-11-16
- **Author:** Aniket Kumar (AK)
- **Deciders:** the lead; all three lanes (the freeze binds every producer and consumer, [03 §1](../03-contracts.md))
- **Consulted:** Observe (Annapurna S), Explain (C Lakshanaa)
- **Issue / CCR:** #17 (R-07), #301
- **Supersedes:** none · **Superseded by:** none

## Context

R-07 ([07](../07-roadmap.md), M1, due Sun 8 Nov) freezes the data contracts at `1.0` and tags `contracts-1.0`. It has not happened: every contract is still `0.1.0`, and no tag exists in the repository (checked 16 Nov). Since 8 Nov contracts kept changing through CCRs under the `0.x` rule (e.g. `bench_summary` and `bench_manifest`, ADR bench-summary-manifest-contracts, #69).

What the version is and where it lives ([03 §1](../03-contracts.md)):

- every schema's `$id` is `https://veyltrace.dev/schemas/<major>.<minor>/<name>.schema.json`; JSON artifacts carry `"schema_version": "<major>.<minor>.<patch>"`; Parquet files carry `veyltrace.schema = <name>/<major>.<minor>.<patch>`;
- core's writers stamp the registry version and refuse a different one; readers accept the same major only, and before M1 only the exact minor (`veyltrace_core.io.ALLOW_OLDER_MINOR = False`, which its comment says the lead flips at M1). A bump changes every artifact's bytes, and a major bump makes older files unreadable;
- `verdict_hash`, `card_hash` and the receipt are hashes of canonical JSON that includes `schema_version` ([03 §10](../03-contracts.md), [09 §3.13](../engines/09-causentra.md)), so a bump changes them too.

A version bump therefore rewrites every golden fixture: 149 JSON files under `packages/*/fixtures/` and `contracts/examples/` carry `schema_version`, and 195 Parquet fixtures carry the metadata key (counted on main, 16 Nov). The open stacks regenerate the same fixtures: Causatrix/Causentra v1 (#164, #171, #200–#207, #290) and Causivra (#174–#178). None of them changes a schema (checked with `gh pr diff --name-only`), but a bump landing under them would conflict on every fixture they touch and force each stack to re-run `check.py --update-golden --cascade`.

The pre-registration tag `prereg-v1` ([04 §1](../04-evaluation-protocol.md)) freezes 04, `config/{core,faultloom,causatrix,causentra}.yaml` and the `prereg: true` experiment YAMLs. It does not freeze 03 or the schemas, so a contract bump after `prereg-v1` is not a deviation (04 §12). It must precede any Veyltrace test-split run (R-11, #28).

### Contracts and their current versions

All 32 contracts of the registry (`veyltrace_contracts.registry.CONTRACTS`, plus the shared `$defs` file `common.schema.json`) are at **0.1.0**:

| Group | Contracts (kind) |
|---|---|
| Ingest (Infralume) | `case_manifest` (json), `telemetry.metrics`, `telemetry.logs`, `telemetry.spans`, `telemetry.events` (parquet) |
| Core | `alert`, `config_lock`, `run_manifest` (json) |
| Signals (Signalyth) | `signal_cube.series`, `signal_cube.edges`, `signal_cube.templates`, `signal_cube.critical_path` (parquet) |
| Anomara | `anomalies` (parquet), `onsets` (json) |
| Causync | `alignment` (json), `changes` (parquet) |
| Causalith | `graph.nodes`, `graph.edges`, `graph.paths` (parquet) |
| FaultLoom | `evidence` (parquet), `predicates` (json; also `contracts/predicates.json`) |
| Causatrix | `slate` (json) |
| Relentra | `proposals` (json), `agent_trace` (jsonl) |
| Causentra | `verdict`, `calibration` (json) |
| Causivra | `card`, `receipt` (json) |
| Bench | `answer_key` (parquet), `bench_result` (csv), `bench_summary`, `bench_manifest` (json) |

## Decision drivers

- R-11's released outputs (`per_case.csv` with `verdict_hash`, receipts) must never need regenerating, and Tier 1 replay (RQ6, H6a) must reproduce their hashes.
- `prereg-v1` should be pushed as early as possible: the tag time is the evidence (04 §1).
- A bump should not land under open stacks and cost every lane a fixture regeneration.
- After the freeze, changes follow one written process that every lane can check.

## Considered options

1. **Bump now**, under the open stacks.
2. **Bump after the open stacks merge, after `prereg-v1`, before R-11** (recommended).
3. **Bump before `prereg-v1`**, after all stacks merge.
4. **Bump after R-11**, at M3.

## Decision

We choose **option 2**: freeze at `1.0` once the open engine stacks are on main, after `prereg-v1` is pushed and before R-11's first test-split run, because it keeps the released R-11 outputs on frozen contracts without delaying the pre-registration tag or rebasing open stacks.

**Order (each step after the previous one is on main):**

1. The Causatrix/Causentra v1 stack merges (#164, #171, #200–#207, #290).
2. The prereg stack merges (#298 dev cases, #299 M2 YAMLs, #300, #302, #303, #305, #304); the lead tags `prereg-v1` on that main commit and pushes it (checklist in #304's PR).
3. The Causivra stack merges (#174–#178), and any other open PR that writes fixtures.
4. One `chore(contracts)` PR by the Reason lane: every schema's `$id` to `…/schemas/1.0/…` and version to `1.0.0` (`predicates` included), `uv run python scripts/gen_contracts.py` (generated Python and TypeScript, contracts package version `1.0.0`, then `uv lock` for the lock entry), `ALLOW_OLDER_MINOR = True` in `veyltrace_core.io` (with its tests), `uv run python scripts/check.py --update-golden --cascade` for all producers, 03 §1's examples and status line. No field changes in that PR. Gate: full `check.py` and `--determinism --require-synth --ai-fake` green, `gen_contracts.py --check` clean.
5. The lead tags `contracts-1.0` on that merge commit and pushes it.
6. R-11 runs from a clean commit at or after `contracts-1.0`.

If step 3 slips so far that R-11 would wait, the lead may take step 4 before it; the Causivra stack then regenerates its fixtures with `--update-golden --cascade` on its bottom PR. This is the lead's call on the day.

**What 1.0 means (03 §1 "After M1"):**

- Additive changes only, as a **minor** bump (`1.1`), through a Contract Change Request issue (form "Contract change", skill `contract-change-request`) + an ADR + lead approval.
- Removing or renaming a field, changing a type, unit, key or sort order, or narrowing an enum is a **major** bump and needs all three lanes' approval.
- With `ALLOW_OLDER_MINOR` on, a `1.x` reader reads every older `1.y` file: absent nullable (`?`) fields and columns read as null and the self-hash stays the writer's; an absent non-null field is refused. So an additive field must be `?`, or it is a breaking change. A minor bump still rewrites the goldens' `schema_version` (writers stamp the current version); the CCR states that cost.
- `contracts/generated/` is never edited by hand (unchanged).

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| 1. Bump now | earliest freeze | conflicts on the fixtures of the 15 open stack PRs; two lanes regenerate goldens mid-review | cost without benefit: nothing has been released yet |
| 3. Before `prereg-v1` | one ordered freeze | delays `prereg-v1` until the Causivra stack merges, although 04 §1 does not depend on contract versions | the tag time is the pre-registration evidence; delay weakens it |
| 4. After R-11 | no rush before M2 | R-11's run directories would be 0.1 artifacts, which 1.0 readers refuse (different major), and their `verdict_hash` values differ from a 1.0 re-run, so the M2 table would be re-run | breaks the "released numbers are never regenerated" driver |

## Consequences

- **Positive:** the first released results (R-11) are on frozen contracts; `prereg-v1` is not blocked by the Explain stack; one mechanical PR does the bump.
- **Negative / costs:** the bump PR regenerates every fixture (excluded from the 400-line limit as fixtures and generated code, AGENTS.md §3.7); M1's freeze lands about two weeks late, which the paper does not need to report (03 is not part of the pre-registration).
- **Follow-ups:** the step 4 PR (new issue under #17 when step 3 is done); FSE'26 go/no-go, the other R-07 item (04 §13 Q3, 07 O-08), stays at its default "stretch" until someone checks size, format and licence; update 10 §2 and 07 dates when the tags exist.

## Confirmation

`git tag -l` shows `prereg-v1` before `contracts-1.0`, and the R-11 results' `manifest.json` records a code commit that contains `contracts-1.0`. After the freeze, CI's `--contracts-in-sync` job fails on any schema edit without regenerated code, and the "Contract change" issue form labels each CCR `frozen-contract`; every later schema change has a CCR and an ADR.

## Evidence

- [03 §1](../03-contracts.md) (versioning, before/after M1 rules), [03 §10](../03-contracts.md) (self-hash rule), [09 §3.13](../engines/09-causentra.md) (`verdict_hash`).
- [04 §1](../04-evaluation-protocol.md) (frozen set, what may run before the tag), [04 §12](../04-evaluation-protocol.md) (deviations).
- [07](../07-roadmap.md) R-07, R-11; [10 §2](../10-sdlc-and-quality.md) (`contracts-1.0` at M1).
- Counts and versions: `veyltrace_contracts.registry.CONTRACTS` and `git grep -l '"schema_version"'` on main, 16 Nov 2026.
