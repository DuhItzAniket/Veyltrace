# Slate-scored causatrix:<ranker> methods reuse veyltrace:off's upstream steps

- **Status:** Accepted (lead, R-16 plan on #45 §2 decision 4, relayed by the manager session, 2026-11-21)
- **Date:** 2026-11-21
- **Author:** Aniket Kumar (AK)
- **Deciders:** the lead
- **Consulted:** Reason (R-16 manager session); no other lane (bench only, no contract change)
- **Issue / CCR:** #413 (B5, part of #45); 04 §12 deviation row of 2026-11-21
- **Supersedes:** none · **Superseded by:** none

## Context

The pre-registered RQ1 experiments run each Causatrix ranker alone (`causatrix:<ranker>`, [04 §4](../04-evaluation-protocol.md), §9): six slate-scored methods next to `veyltrace:off`. Each one re-ran the whole pipeline, about **25 s per RE2 case**, although Causatrix, Causentra and Causivra together take about 2 s of that (**measured**, R-11 log, R-16 plan §1). An 11-method RE2 experiment takes about 13 h without reuse and about 5 h with it (*estimate*, plan §4); P0–P2 need about 280 CPU slot-hours without reuse against about 275 available (*estimate*), so the R-16 schedule does not fit without it.

A `causatrix:<ranker>` method differs from `veyltrace:off` only in `causatrix.*` keys, and no step before Causatrix reads that section (no engine up to FaultLoom calls `with_config("causatrix")`). So its run of a case equals `veyltrace:off`'s up to and including Causalith, and a slate-scored method is scored on the slate alone (04 §9: no pool, set or fault type). Core already restarts a run at a later step on another run's outputs (`from_step` + `reuse_dir`, with hash checks, [02 §4](../02-architecture.md)). FaultLoom's claim pass rewrites `evidence.parquet` in every finished run, AI off included (T8 intervention atoms, #368), and core refuses that version as FaultLoom's main output, so the restart is at FaultLoom: FaultLoom and Causatrix re-run (a few seconds), everything before them is reused.

## Decision drivers

- The reported ranking must not change: same inputs, same code, same slate bytes.
- The RQ1 compute must fit the R-16 window (Tue 24 → Sat 28 Nov).
- The cost numbers of RQ5 (H5) must stay honest.

## Considered options

1. **Reuse upstream** for `causatrix:<ranker>`: restart at FaultLoom on the `veyltrace:off` run of the same case and experiment, stop after Causatrix.
2. **Run every method in full** (the status quo).
3. **Score the rankers from `veyltrace:off`'s slate** (re-rank its `all_scores`): not the same computation, since the fusion and the K differ per ranker.

## Decision

We choose **option 1** (`veyltrace_bench.upstream`, wired in `runner._reused`):

- It applies to a `kind: causatrix` method with AI off whose overrides are all `causatrix.*` keys (every `causatrix:<ranker>`). `causatrix:rrf` has none and keeps sharing `veyltrace:off`'s whole run (#172). The source is the experiment's AI-off `veyltrace` method without non-`causatrix` overrides, for the same case, its first run (same calibration choice).
- **Reuse only if nothing differs:** the source run finished `ok`; its `config.lock.json` sections `core`, `infralume`, `signalyth`, `anomara`, `causync`, `causalith` equal the method's resolved ones; its code commit equals this run's; and every file the reused sub-steps wrote still holds the hash its `run_manifest.steps` recorded (core re-checks this too). Otherwise the method runs in full, and the reason is logged (`bench.upstream_reuse`).
- The reusing run is a partial run (`<run_id>~causatrix`, core's naming) of the method's own config, so its `run_id` and `slate.json` equal those of a full run.
- **Cost:** a reused row's `wall_ms` and `peak_rss_mb` cover the FaultLoom and Causatrix steps only, and the summary `cost` entry of every `kind: causatrix` group is null. Its timeout is `resources.timeout_s` minus the source run's elapsed time, so a row times out exactly when the full run would (results unchanged by construction). RQ5 cost numbers come only from `veyltrace:off` runs (the solo `re2-oracle-rq1-v1` run, plan §2 decision 3). [04 §12](../04-evaluation-protocol.md) records this as a deviation, and `bench/README.md` says it.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Run every method in full | `wall_ms` means the same for every row | ~2.5× the CPU for RQ1-style experiments; R-16 does not fit | the compute budget |
| Re-rank `veyltrace:off`'s slate | no extra run at all | not what `causatrix:<ranker>` is (fusion over one ranker, its own K and `all_scores`) | changes results |

## Consequences

- **Positive:** about 25 s → about 3 s per case per ranker method (*estimate*); identical slates and ranks.
- **Negative / costs:** `wall_ms` of `causatrix:<ranker>` rows is no longer an end-to-end time; tables must not read cost from them. A reused method has no receipt of its own (a partial run); its slate is reproducible by re-running the method in full, which gives the same bytes.
- **Follow-ups:** none required; none.

## Confirmation

`bench/tests/test_upstream_reuse.py`: slates of `causatrix:baro_rs`, `:graph_walk` and `:prism_m` are byte-identical to full runs on synth-01…05, with identical ranks and hits; a changed upstream config section, an edited reused output, or a forced mismatch falls back to a full run.

## Evidence

- R-16 plan on #45 (§1 measured step times; §2 decision 4; §4 sizes, *estimates*).
- `packages/core/src/veyltrace_core/pipeline.py` `_check_prior` (reuse hash checks); 02 §4 step order.
