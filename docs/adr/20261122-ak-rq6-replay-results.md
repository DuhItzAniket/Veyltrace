# RQ6 replay rates are committed as per-site bench replay results

- **Status:** Accepted
- **Date:** 2026-11-22
- **Author:** Aniket Kumar (AK)
- **Deciders:** the lead
- **Consulted:** Explain (Causivra owns `veyltrace replay`, 10 §3.9; the paper's §5.6 reads Table 9)
- **Issue / CCR:** #440 (CCR); design note on #46
- **Supersedes:** none · **Superseded by:** none

## Context

RQ6 ([04 §2](../04-evaluation-protocol.md)) has two hypotheses:
- **H6a / SC-6:** Tier 1 replay reproduces `verdict_hash` on 100% of recorded cases, on a second laptop and in CI.
- **H6b:** the Tier 2 regeneration match rate is reported, with no target.

Both are proportions with exact binomial CIs (04 §7 "Replay", §8). 04 §6 schedules Tier 2 on 50 recorded cases at M4.

`veyltrace replay` exists ([10 §3.9](../engines/10-causivra.md), #434), but no bench contract holds its outcomes:
- `bench_summary` 1.2 ([03 §13.3](../03-contracts.md)) has no replay entry, and 04 §9's metric vocabulary has no replay name;
- `bench_result` has no exit-code column;
- the gateway's `replay_report` (03 §14) is one run's API response.

So R-17 Table 9 printed "not run" (#439). The second-laptop and CI replays happen on other machines, after `bench run` wrote `summary.json`. 04 and `bench/experiments/*.yaml` are frozen at `prereg-v1`.

## Decision drivers

- Every paper number traces to a committed file and a code commit (04 §10.2).
- No frozen file changes, except as §12 rows.
- Bench never imports `veyltrace_llm`, and does not import Causivra internals (AGENTS §4.3).
- Per-run outcomes are released (04 §10.1); raw benchmark telemetry is not.

## Considered options

1. **A `replay` entry in `bench_summary` 1.3.**
2. **A new replay experiment YAML.**
3. **Per-site replay results** under `bench/results/replay/<role>/`, produced by a bench subcommand from the committed manifests.

## Decision

We choose **option 3**. Two new evaluation-only contracts, at 1.0.0 ([03 §13.5–§13.6](../03-contracts.md), CCR #440):
- `bench_replay`: `replay.csv`, one row per (tier, run);
- `bench_replay_summary`: `replay_summary.json`, written last.

`role` ∈ {`recording`, `second-laptop`, `ci`} names the directory. A re-run replaces the directory, and git keeps the history.

**Command.** `veyltrace bench replay --role <role> --runs-root R [--tier 1|2] [--dry-run]`. It reads the committed `manifest.json` and `per_case.csv` of the R-16 experiments at `results-code-v1`.
- `--dry-run` prints the run count and the total bytes of the run directories, and replays nothing.
- It refuses, before the first replay:
  - a checkout whose commit differs from a source manifest's `code.commit`, or that is dirty;
  - `second-laptop` with the `recording` result's `host_id`;
  - `ci` without `GITHUB_ACTIONS`.

**Tier 1 (H6a / SC-6).**
- **What is replayed:** every distinct `run_id` of an AI-arm row with `run_outcome = ok`. Non-`ok` AI-arm rows are counted in `excluded`.
- **How:** bench runs `python -m veyltrace_core.cli replay <receipt> --report <tmp>` as a subprocess, strict: no `--allow-env-drift`, no `--full`. The subprocess keeps `veyltrace_llm` and Causivra out of bench's interpreter.
- **Reading the result:** the report's exit code, hashes, `first_divergence` and `env_drift` fill the row. A run without a report is `no_report`, because core's CLI also uses exit 2 for usage errors.
- **The rate:** the primary rate is the share of exits 0 (04 §7). `k_verdict` counts the rows whose recomputed `verdict_hash` equals the recorded one (H6a's wording).

**Tier 2 (H6b).**
- **The sample:** 50 runs of `re2-oracle-rq2-v1` / `veyltrace:brief` / seed 1, drawn with `veyltrace_core.rng` (seed 20261108, the experiment's split seed, a priori).
  - This fills a detail 04 §6 leaves open, and it is fixed here, before any regeneration.
  - The sample is recorded in `tier2.selection`.
- **The regeneration:** each sampled run is regenerated in `record` mode through bench's child runner, with the kept run's resolved config, into a scratch runs root outside the repo. The regenerated run id must equal the kept one; otherwise the row is `regen_failed`.
- **The comparison:** a match means the `proposals.json` bytes are identical to the kept run's. `verdict_hash` is compared alongside.
- **The runtime:** regeneration uses the recording's own provider (Ollama `qwen3.5:9b`, same config hash). 04 §7 names `llama-server -np 1`, so this is a §12 deviation row (lead-approved, 22 Nov).

**Intervals.** Clopper–Pearson at 0.95 (04 §8), from `veyltrace_stats.exact.clopper_pearson`, stored in the summary. Tables never recompute them.

**Table 9.** `tables/rq56.replay` reads the three `replay_summary.json` files: Tier 1 per role, then Tier 2. A missing role stays "not run". This reading is covered by 04 §9's committed-summaries rule, with a one-line §12 row for clarity.

**The run archive.** The second laptop and CI need the kept `bench-ai` run directories. Replay re-hashes their `telemetry/*` (R6), and 04 §10.1 doesn't redistribute raw telemetry. So the archive is **private only**: a GitHub Actions artifact or a private release asset. It is never on Zenodo and never committed, until the dataset licences are checked.

**CI.** A `workflow_dispatch` job downloads that archive and runs `--role ci`.
- **Decision point (lead, after R-16):** if `--dry-run` reports more bytes than the Actions artifact limit allows, the lead decides how CI gets the runs. No size is assumed here.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| `bench_summary` 1.3 `replay` entry | one file per experiment | changes the frozen 04 §9 vocabulary; only the recording machine writes `summary.json` | can't hold the other sites' results |
| replay experiment YAML | reuses the runner | a new prereg file (§12 deviation); still no exit-code column | needs a new contract anyway |

## Consequences

- **Positive:** Table 9 and SC-6 trace to committed files. A failed replay is a row with a reason, not a missing number. Bench's isolation is unchanged.
- **Negative / costs:**
  - two new contracts;
  - a private archive has to be moved between machines;
  - Tier 2 measures regeneration on Ollama, not on llama.cpp.
- **Follow-ups:**
  - the implementation PR (`veyltrace_bench.replay`, the `bench replay` subcommand, `rq56.replay`), tested first on synth runs with AI off and a fake record arm;
  - the `workflow_dispatch` CI job (`.github/`, lead-approved for #46);
  - running the three roles after `results-code-v1`.

## Confirmation

- **Bench tests on synth:**
  - a fake record run replays to exit 0;
  - a changed cassette gives exit 3;
  - a missing receipt gives `no_receipt`;
  - `--dry-run` writes nothing;
  - the summary validates.
- **The result:** the three replay summaries committed after R-16.

## Evidence

- 04 §2, §6, §7 "Replay", §8, §9, §10.1, §10.7;
- 10 §3.9 (exit codes and the report);
- `bench/src/veyltrace_bench/ai_arms.py` (kept record runs);
- [verified_agents §Q3](../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/verified_agents_local_llms.md#q3-determinism-and-replay-with-llms-what-is-achievable-on-cpu-vs-gpu) (replay tiers; bit-exact regeneration is not portable).
