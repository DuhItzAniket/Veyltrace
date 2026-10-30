# 04 · Causync — align clocks across sources, build the change timeline, score change–onset proximity and changed-vs-peer contrast

> Status: v0.1-draft · Lane: Observe · Master: [docs/02-architecture.md §6.4](../02-architecture.md) · Contracts: [docs/03-contracts.md §5](../03-contracts.md) (reads §2, §2.6, §3.1, §4) · Roadmap: O-06, O-13 · Last updated: 2026-10-30

## 1. Purpose and scope

Causync does two things. It puts every source on one clock (or says how far apart the clocks are), and it turns change events into change evidence: which change came last before each service's onset, how close it was, and whether changed replicas behave worse than unchanged peers. Changes trigger most outages in industrial data (Google 2010–2017: binary pushes 37% + config pushes 31% = 68%), but public RCA benchmarks contain no change events ([novel_building_blocks §Q5][nbb]).

**In scope**: per-source and per-service clock offsets; the tolerance for onset comparisons; the change timeline from `telemetry.events`; proximity, `latest_before_onset`, peer contrast.

**Out of scope**: deciding whether a change is the root cause (FaultLoom atoms, Causatrix `change_prox`, Causentra T6/T7); rewriting telemetry timestamps (outputs carry offsets; consumers apply them). The RCAEval-C decoy generator is Observe-owned (O-13) but is bench code in `bench/decoys/`, not part of this engine (§3.7).

## 2. Inputs and outputs

**Reads**

| Contract | Fields used |
|---|---|
| `case_manifest` | `sources`, `services` |
| `alert` | `t_alert_ns`, `windows.*` |
| `telemetry.events` | all columns |
| `telemetry.spans` | `trace_id, span_id, parent_span_id, service, kind, start_ns, end_ns` (clock pairs) |
| `telemetry.logs` | `t_ns, service, trace_id, span_id` (log–span join) |
| `signal_cube.series` | `service, component, signal, source, t_ns, value` (steps, co-movement, replica first-seen) |
| `anomalies` | `series_id, service, component, klass, source, detector, score_norm, onset_ns, above_threshold` |
| `onsets` | `t_onset_ns`, `entry_services`, `per_service` |

**Writes**

| Contract | Fields |
|---|---|
| `alignment.json` | `schema_version`, `reference` (`traces` if present, else `metrics`), `offsets[{source, service?, offset_ns, method, confidence}]`, `tolerance_ns` |
| `changes` | `change_id, t_ns, entity, kind, scope, detail_json, latest_before_onset, delta_to_onset_ms?, proximity, peer_contrast?` |

`offset_ns` is **added** to a source's times to put them on the reference clock (03 §5.1). `method` values (03 §5.1): `reference | trace_pairs | log_span_join | comovement | none`. `offsets` is sorted by (`source`, `service` with null first).

## 3. Algorithm

### 3.1 Steps and tolerance

Step per present source, derived from data (no other engine's config is read):

- metrics: median over metric series of the effective step (median duration of runs of equal consecutive values, at least the observation spacing; same definition as [03-anomara §3.1](03-anomara.md));
- logs, traces: median spacing of consecutive bucket timestamps in their count series (zero-filled, so this equals the Signalyth bucket).

`tolerance_ns` = the largest step among present metric/log/trace sources ([02 §6.4](../02-architecture.md)). On RCAEval RE2 this should come out near 15 s (15 s Prometheus scrapes held on a 1 s grid, [rcaeval_facts §Metric step and windows][rf-step]); measured at O-06.

### 3.2 Trace clock offsets per service (`trace_pairs`)

1. **Pairs.** Parent `p` and child `c` in different services where `p` is client-like (explicit `client`, or inferred as in [02-signalyth §3.3](02-signalyth.md)) and `c` is its only child.
2. **Per-pair offset**, the NTP on-wire estimate with `t1 = p.start, t2 = c.start, t3 = c.end, t4 = p.end`:

   `θ = ((t2 − t1) + (t3 − t4)) / 2` — callee clock minus caller clock, assuming symmetric network delay (RFC 5905).
3. Per caller→callee service pair: `θ_AB` = median `θ`, `n_AB` = number of pairs, and the share of pairs where the child sticks out of the parent (`c.start < p.start` or `c.end > p.end`).
4. **Propagation.** Root = first entry service A→Z from `onsets.entry_services`, else the service with the most spans. Breadth-first over pairs with `n ≥ align.min_pairs`, neighbours visited by (`n` desc, name asc). Along A→B (A calls B): `offset(B) = offset(A) − θ_AB`; along B→A reversed: `offset(A) = offset(B) + θ_AB`.
5. **Publish** `offset_ns` only if `|offset| ≥ align.trace_min_offset_ms` and the service's containment-violation share ≥ `align.min_violation_share`; otherwise write 0. Client-side overhead biases `θ` by small amounts, so offsets are only applied where the data shows skew. `confidence = n/(n + align.min_pairs) × (share of pairs whose θ has the sign of the median)`; 0 for unreachable services (offset 0, method `none`).

Micro-example: `p = [1000, 1050]` ms on A, `c = [1030, 1046]` on B (B starts after A's call and ends before A's return; no skew visible). `θ = ((1030 − 1000) + (1046 − 1050))/2 = 13 ms`. With 40 such pairs and no containment violations, the violation share is 0, so the published offset is 0. If B's clock ran 200 ms ahead, `c = [1230, 1246]`, `θ = 213 ms`, the child sticks out of the parent in every pair, and `offset(B) = −213 ms`.

### 3.3 Logs and metrics to the reference clock

**Logs, `log_span_join`** (when logs carry `span_id` matching spans): for each joined log line `i`, the offsets that would put it inside its span form `I_i = [span.start − t_i, span.end − t_i]`. If `0 ∈ I_i` for ≥ `align.log_inside_share` of lines, offset 0. Otherwise offset = median over `i` of the projection of 0 onto `I_i`. `confidence` = share of lines inside their span after correction.

**Co-movement, `comovement`** (fallback for logs without span IDs, and for metrics when the reference is traces), per service:

1. Pair the source's traffic-like series (`log_rate`; metric `workload`/`rps`) with the reference series (traces `rps`).
2. Resample both to `Δ` = the larger of the two steps (sum for counts, last value for gauges); take first differences.
3. For lags `ℓ ∈ [−align.max_lag_s, +align.max_lag_s]` in steps of `Δ`: Pearson correlation of `Δsource(t + ℓ)` with `Δref(t)`.
4. Best `ℓ*` = argmax correlation (ties: smaller `|ℓ|`, then negative first). Accept if correlation ≥ `align.min_corr`, `|ℓ*| < max_lag`, and ≥ `align.min_points` overlapping points. A positive `ℓ*` means the source shows changes `ℓ*` later, so its offset is `−ℓ*`.
5. Source-level offset (`service` omitted) = median of accepted per-service offsets if at least 2 services agree within one step `Δ`; else 0 with method `none`.

Co-movement resolution is one step, so it only catches gross misalignment; finer differences are inside `tolerance_ns` by construction.

**Events**: no estimator; offset 0, method `none`, confidence 0 (when `sources.events`). **Reference source**: offset 0, method `reference`, confidence 1.

### 3.4 Aligned entity onsets

For each service, `O(s)` = min of `per_service.external_onset_ns` and `internal_onset_ns`, each converted to the reference clock by adding the offset of the source recorded in `per_service.external_onset_source` / `internal_onset_source` ([03 §4.2](../03-contracts.md)); the per-service offset is used when one exists for that (source, service), else the source-level one, and a null source means offset 0. A service without an onset uses `t_onset_ns`.

### 3.5 Change timeline

1. Take `telemetry.events` rows whose `kind` is in `changes.kinds` (`deploy, config, flag, scale, restart, commit`). `restart` means a deliberate restart (`kubectl rollout restart`); crash restarts arrive as `k8s_event` (OOMKilled, BackOff, Killing), which, like `other`, are symptoms and are excluded ([05 §7](../05-fault-lab-and-dataset.md)).
2. `t_ns` = event time + events offset (normally 0).
3. `scope`: `service` if `entity` ∈ `case_manifest.services`; `component` if `entity` is a component in `signal_cube.series`; else `cluster`.
4. `change_id = "C" + sha256(canonical_json({t_ns, entity, kind, source_system, detail_json, actor}))[:10]` over the original event fields; duplicate IDs are collapsed.
5. `detail_json` is copied unchanged (already scrubbed by Infralume).

### 3.6 Change evidence

For each change, target onset `O` = `O(entity)` for service scope, `O(service of the component)` for component scope, `t_onset_ns` for cluster scope.

- `delta_to_onset_ms = (t_change − O) / 10⁶` (negative = before onset).
- `proximity = exp(−max(0, O − t_change) / τ_change)` if `t_change ≤ O + tolerance_ns`, else 0. This is the temporal term of technique card N5 with `δ = tolerance` ([novel_building_blocks §Q5][nbb]); a change recorded slightly after onset because of clock error still counts.
- `τ_change = 300 s` (a priori). Reasoning: bench's RCAEval-C places true changes within 120 s before injection ([novel_building_blocks §Q5][nbb]); with τ = 300 s such a change scores ≥ e^−0.4 = 0.67, and the O-06 criterion (proximity > 0.5) holds for Δt < 208 s; a change at the start of the 20-minute baseline scores e^−4 ≈ 0.018. τ is reported at 60/300/900 s as a sensitivity analysis, never tuned on test data.
- `latest_before_onset`: DuckDB ASOF join per entity ([stack_and_market §A2][sm]):

  ```sql
  SELECT o.entity, c.t_ns
  FROM entity_onsets o
  ASOF JOIN changes c
    ON o.entity = c.entity AND o.onset_ns + $tol >= c.t_ns
  ```
  Every change of that entity with the matched `t_ns` is flagged (equal timestamps are all "latest").
- `peer_contrast` (changed-vs-control cohort, Meta Service Health Checks / Gandalf, [novel_building_blocks §Q5][nbb]):
  1. Replicas of service S = distinct `component` values of S in `signal_cube.series`, excluding `component = S`. Need ≥ `peer.min_replicas` (2).
  2. Changed set: component scope → `{entity}`; service scope with kind `deploy | config | restart | scale` → replicas first observed at or after `t_change` (new pods of a rollout).
  3. Peers: replicas observed before `t_change` and after `O`, not in the changed set.
  4. Replica score `a(k)` = max `score` (raw robust z, unit z) over `anomalies` rows with `component = k`, `detector = robust_z`, `klass ∈ {internal, external}`. Raw z, not `score_norm`, so the value is in the same units as FaultLoom's anomalies-based `peer_contrast` atom ([06-faultloom §11 Q7](06-faultloom.md)).
  5. `peer_contrast = mean_{changed} a − median_{peers} a` (unit z); null if either set is empty or scope is cluster.

**Decoys.** Causync scores every change by time, entity, kind and anomalies only; `source_system` and `actor` never enter any rule or score. Infralume gives every overlay row `source_system = synthetic` and `actor = null` ([01-infralume §3.10](01-infralume.md)), so true and decoy changes are indistinguishable here, as [02 §6.4](../02-architecture.md) requires. Real lab decoys (benign `kubectl set env` rollouts on non-root services, [05 §7](../05-fault-lab-and-dataset.md)) arrive as ordinary `k8s` events and are treated the same way.

**No events.** RCAEval has none ([novel_building_blocks §Q5][nbb]): `changes` has zero rows, and the change channel abstains downstream.

### 3.7 RCAEval-C decoy generator (O-13, `bench/decoys/`)

Observe owns this bench module to balance load ([08 §2](../08-collaboration-and-git.md)). It is bench code: it may read answer keys and injection times, and the engines never import it.

1. Inputs per RE2 case: `case_id`, the answer key (root service, `t_inject_ns`), the experiment's `protocol.decoys` (`pi`, `rate_per_h`, `window_s`), `case_manifest.services`.
2. Randomness only from `veyltrace_core.rng(case_id, "rcaeval-c")`, so the same seed gives the same overlay.
3. With probability π, one **true change** on the root service at `t_inject − U(0, 120 s)`; Poisson **decoys** on non-root services at rate λ per hour in `[t_inject − 30 min, t_inject + 5 min]`; kinds drawn from {`deploy`, `config`, `flag`}; grid in [04 §5.2](../04-evaluation-protocol.md), mechanism from card N5 ([novel_building_blocks §Q5][nbb]).
4. All rows use one schema: `source_system = synthetic`, `actor = null`, neutral `detail_json` (no "decoy" or "true" token). Output: `${VEYLTRACE_DATA}/overlays/<experiment_id>/<case_id>/events.parquet`, merged by Infralume through `events.overlay_path` (O-09; Infralume never reads `bench/`, 02 §9 rule 3). Which row is true goes only to `answer_key.decoy_changes_json`.
5. Test: two runs give byte-identical overlays; a property test checks that true and decoy rows differ in no column except `t_ns`, `entity` and `kind`.

## 4. Configuration — `config/causync.yaml`

| Key | Default | Unit | Rationale / source |
|---|---|---|---|
| `align.min_pairs` | `30` | pairs | a priori |
| `align.trace_min_offset_ms` | `5` | ms | a priori; below this, client overhead dominates |
| `align.min_violation_share` | `0.05` | ratio | a priori |
| `align.log_inside_share` | `0.95` | ratio | a priori |
| `align.max_lag_s` | `120` | s | a priori |
| `align.min_corr` | `0.5` | Pearson r | a priori |
| `align.min_points` | `20` | points | a priori |
| `changes.kinds` | `[deploy, config, flag, scale, restart, commit]` | — | [02 §6.4](../02-architecture.md); `k8s_event` excluded as symptoms |
| `changes.tau_s` | `300` | s | a priori, §3.6 |
| `peer.min_replicas` | `2` | count | a priori |
| `duckdb.threads` | `1` | — | determinism |

## 5. Determinism and isolation

- Service order A→Z; BFS neighbour order fixed (§3.2); argmax ties fixed (§3.3); ASOF ties handled explicitly.
- Medians exact; no RNG; DuckDB single-threaded.
- Allowed imports: `duckdb`, `pyarrow`, `numpy`, `scipy`, stdlib. Banned per AGENTS §4.3.

## 6. Missing data and failure behaviour

| Situation | Behaviour |
|---|---|
| No traces | reference `metrics`; no `trace_pairs`; logs/metrics via co-movement against metrics traffic where possible |
| Neither traces nor metrics (logs only) | reference `metrics` (contract wording), all offsets 0 with `none` (open question 3) |
| No client spans (RCAEval may lack them) | inferred client spans; if none, every trace offset 0 with `none` |
| No events, or no change-kind events | zero-row `changes` |
| Change entity unknown | scope `cluster`, target onset `t_onset_ns`, `peer_contrast` null |
| No anomalies for a service | `O = t_onset_ns`; replica scores 0 |
| No replicas (RCAEval: component = service) | `peer_contrast` null |

## 7. Tests

**Unit**: NTP formula and sign; BFS propagation over a 3-service chain; publish gate (violation share); log projection; co-movement recovers a planted lag of 2 steps and rejects low correlation; scope assignment; `change_id` stability; proximity at Δt = 0, τ, after onset within and beyond tolerance; ASOF ties; cohort construction for a rolling deploy.

**Golden (synth-01…05)**: synth-04's change has `proximity > 0.5` and `latest_before_onset = true` (O-06; synth-04 contains one change, so no answer key is needed); synth-01…03 and 05: `changes` as in the fixture (zero rows if the generator writes no events); `alignment` offsets 0 unless the generator plants skew.

**Property (hypothesis)**: shift all spans of one service by δ (|δ| ≥ 50 ms) → its published offset is −δ within 1 ms; `proximity ∈ [0, 1]` and non-increasing in `O − t_change`; relabelling `source_system`/`actor` on any row leaves every score unchanged; adding a change on another entity leaves existing rows unchanged; shuffled inputs → identical outputs.

**Real-case smoke**: RE2-OB/SS/TT: `changes` empty, `reference` correct (SS → `metrics`), `tolerance_ns` reported; one lab capture with a real `kubectl rollout` (after X-06): the rollout appears with scope `service` and a non-null `peer_contrast` when replicas ≥ 2.

## 8. Performance budget

Per RE2 case: ≤ 2 s and ≤ 0.5 GB (*estimate*, allocation of the 30 s / 3 GB budget). Trace pairs are a single grouped pass over spans in DuckDB; co-movement is a few hundred short correlations.

## 9. Evaluation hooks and ablations

| Arm | Bench measures |
|---|---|
| change channel on/off (`sources.drop: [events]`) | accuracy on lab and RCAEval-C cases |
| RCAEval-C grid (O-13): π ∈ {0, 0.5, 1.0}, decoy rate λ ∈ {0, 2, 6} per hour ([04 §5.2](../04-evaluation-protocol.md)) | accuracy and set size vs π and λ; `naive-change` baseline as comparison |
| `changes.tau_s` ∈ {60, 300, 900} | sensitivity, reported not tuned |
| planted clock skew (needs an Infralume hook, open question 5) | accuracy vs skew ([novel_building_blocks §Q6][nbb]) |

## 10. Tasks and milestones

| ID | When | Scope | Acceptance (summary) |
|---|---|---|---|
| O-00 | by M0, Tue 3 Nov | stub, synth fixtures | e2e on `synth-01` |
| O-06 | Phase 2, by M2 Sun 15 Nov (after O-04) | alignment, change timeline, change evidence, peer contrast | synth-04 change found with proximity > 0.5 |
| O-13 | Phase 3, by M3 Sun 22 Nov (after R-11, O-06) | RCAEval-C generator in `bench/decoys/` + experiment configs (§3.7) | decoys reproducible from seed; Causync treats them like real changes |
| O-11 | Phase 3 | performance pass | ≤ 30 s, ≤ 3 GB end to end |
| O-12 | Phase 4 | docs, fixtures | reviewed by lead |

## 11. Open questions

| # | Question | Default if unresolved |
|---|---|---|
| 1 | ~~02 §3 reads omit `telemetry.spans`, `telemetry.logs`, `anomalies`.~~ Resolved in 02/03 (2026-10-30): [02 §3](../02-architecture.md) now lists them. | — |
| 2 | ~~**CCR**: `alignment.offsets[].method` vocabulary and sort order.~~ Resolved in 02/03 (2026-10-30): [03 §5.1](../03-contracts.md) fixes both as in §2. | — |
| 3 | Reference when neither traces nor metrics exist. | `metrics`, offsets 0 |
| 4 | ~~The overlay path between O-13 and Infralume is not in O-09's text.~~ Resolved in 07 (2026-10-30): O-09 provides `events.overlay_path`; overlays are written under `${VEYLTRACE_DATA}/overlays/`. | — |
| 5 | The clock-skew robustness arm ([novel_building_blocks §Q6][nbb]) needs an Infralume hook (`skew.inject`), not in O-09. | add to O-09 if time allows; else not run |

## 12. References

- Master and contracts: [02 §6.4, §9](../02-architecture.md); [03 §5](../03-contracts.md); [07](../07-roadmap.md)
- Change-induced outages, Gandalf, Meta cohorts, ChangeRCA, card N5 and RCAEval-C: [novel_building_blocks §Q5][nbb]
- Missing telemetry and skew noise protocol: [novel_building_blocks §Q6][nbb]
- ASOF JOIN for change-before-onset: [stack_and_market §A2][sm]; change-event capture: [stack_and_market §A4][sm]
- Client/server timing and skew: [rcaeval_facts §Traces][rf-traces]
- RCAEval sampling: [rcaeval_facts §Metric step and windows][rf-step]
- RFC 5905 (NTPv4) on-wire offset · Google SRE Workbook, Appendix C

[nbb]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/novel_building_blocks.md
[sm]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/stack_and_market.md
[rf-step]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#metric-step-and-windows
[rf-traces]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#traces-spectrum-and-timing

