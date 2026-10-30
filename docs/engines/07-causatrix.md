# 07 · Causatrix — rank candidates with six deterministic rankers and fuse them into a hypothesis slate

> Status: v0.1-draft · Lane: Reason · Master: [docs/02-architecture.md §6.7](../02-architecture.md) · Contracts: [docs/03-contracts.md §8](../03-contracts.md) (output), §7, §6, §2.1 (inputs) · Last updated: 2026-10-30

## 1. Purpose and scope

Causatrix orders every service in the case by how likely it is to be the root cause, using six rankers that each read one evidence channel, fuses them with gated reciprocal rank fusion (RRF), classifies each top candidate's fault mode, class and indicator, and writes the **slate**: the top-K candidates plus a fused score for every service.

Design constraints that follow from the evidence:

- **Recall first.** The verifier can only confirm candidates that are in its decision pool, so Retrieval@K caps everything downstream. On RCAEval, deviation ranking already holds the root in the top 15 for 98–100% of faults, and the open problem is re-ranking (DecompRCA); a too-narrow first stage capped one hybrid at 57.8% candidate recall (RCAtlas) [sota_methods §Q1, §Q3][sm].
- **No learned weights.** Fusion weights are fixed a priori (all 1.0) and the fusion rule is an ablation, never tuned on test data ([02 §6.7](../02-architecture.md)).
- **Each ranker is also a baseline.** Every ranker is reported alone in bench (R-09 acceptance).

Out of scope: deciding (Causentra), creating evidence (FaultLoom), reading Observe tables directly. Causatrix is a pure function of `evidence`, `graph` and `case_manifest`.

## 2. Inputs and outputs (exact fields)

### 2.1 Inputs

| Contract | Fields read |
|---|---|
| `evidence` ([03 §7](../03-contracts.md)), rows with `origin = engine` | `candidate`, `component`, `kind`, `args_json`, `value`, `refs` |
| `graph.nodes` / `graph.edges` (§6) | `node`, `kind`; `src`, `dst`, `weight`, `provenance` |
| `case_manifest` (§2.1) | `case_id`, `services`, `sources` |

`claim_check` atoms do not exist yet at step 6 and are ignored if present (Causentra calls the same functions for trial T9 with engine atoms only).

Shared values (`config/core.yaml`): `k_anom = thresholds.anomaly_z` (3.0), universe **U** as defined in [06 §2.1](06-faultloom.md).

Per-service quantities derived from atoms (0 when no atom exists):

| Symbol | Definition |
|---|---|
| `I(s)` | max `value` over `internal_anomaly` atoms with `detector = robust_z` (all families, sources) |
| `E(s)` | same over `external_anomaly` |
| `NS(s)` | max over `internal_anomaly` ∪ `external_anomaly` atoms with `detector = nsigma` |
| `Sil(s)` | `silence` atom value (0 or 1) |
| `SP(s)` | `spectrum` atom value |
| `CH(s)` | max `change_proximity` value |
| `onset_ms(s)` | `onset_precedence{scope: self}` value; +∞ if absent |
| `topI(s)` | the `internal_anomaly` robust_z atom with the largest value (ties: `atom_id`) |
| `topE(s)` | same for `external_anomaly` |

### 2.2 Output: `slate.json` ([03 §8](../03-contracts.md))

| Field | Value |
|---|---|
| `schema_version`, `case_id` | contract version; from `case_manifest` |
| `k` | `slate.k` (default 5) |
| `rankers_active` | sorted names of rankers that voted |
| `fusion` | `{method: "rrf", k: 60, weights: {ranker: 1.0, …}}` for every enabled ranker |
| `candidates[]` | top-K, sorted by `rank`: `rank` (1-based), `service`, `component` (from `topI`, else `topE`, null if equal to `service`), `indicator`, `mode`, `fault_class`, `fused_score`, `ranker_ranks` (every enabled ranker; null if it abstained), `ranker_scores` (same) |
| `all_scores[]` | every service in U: `{service, fused_score}`, sorted by `round(fused_score, 9)` desc, then service A→Z (03 rule) |

Public pure functions (importable, used by Causentra):

```python
def rank(ev: EvidenceView, graph: GraphView, sources: Sources, cfg: CausatrixConfig) -> RankResult
    # RankResult: active rankers, per-ranker scores and ranks over U, fused F over U, ordered list
def classify(service: str, ev: EvidenceView, graph: GraphView, cfg: CausatrixConfig) -> Classification
    # Classification: mode, fault_class, indicator, component
```

## 3. Algorithm

### 3.1 Steps

1. Build U, the derived quantities of §2.1 and the call graph G = (U, `graph.edges` restricted to U).
2. For each enabled ranker (sorted by name): decide whether it votes (§3.3); if it votes, compute a score for every service in U.
3. Quantise scores with `q(x) = round(x, 12)` and convert to **competition ranks**: `rank_r(s) = 1 + |{t ∈ U : q(score_r(t)) > q(score_r(s))}|`. Tied services share a rank; nothing about the order of names leaks into a ranker's vote.
4. Fuse: `F(s) = Σ_{r ∈ active} w_r / (k_rrf + rank_r(s))`, `k_rrf = 60`, `w_r = 1.0` (Cormack et al.'s k = 60, fixed in a pilot and not tuned afterwards, earlier design notes; GALA+'s STRIX also fuses with RRF k = 60 [sota_methods §Q3][sm]).
5. Order U by the tie-break key `(−round(F(s), 9), 0 if I(s) ≥ k_anom else 1, onset_ms(s), s)`: fused score, then services with an internal anomaly first, then earliest onset, then name. This is the same key Causentra uses with V in place of F ([02 §6.9](../02-architecture.md) step 6).
6. Take the first `k` as the slate; run `classify()` on each (§3.5–§3.6).
7. Write `slate.json`.

If no ranker votes, `candidates = []`, `rankers_active = []`, and every `all_scores` entry has `fused_score = 0.0`; Causentra then returns `INCONCLUSIVE` with a telemetry ask.

### 3.2 The six rankers

| Ranker | Score for service *s* | Abstains when | Source |
|---|---|---|---|
| `prism_m` | `M = I' + E − ln(1 + I' + E)`, with `I' = max(I(s), prism_m.silence_z · Sil(s))` | no `robust_z` anomaly atom in the case | PRISM additive combination [rcaeval_facts §Anomaly scoring methods][rf-methods] |
| `baro_rs` | `max(I(s), E(s))` | no `robust_z` anomaly atom | BARO's robust (median/IQR-scaled) max deviation [rcaeval_facts §Anomaly scoring methods][rf-methods] |
| `nsigma` | `NS(s)` | no `nsigma` anomaly atom | RCAEval N-Sigma baseline |
| `cp_sbfl` | `SP(s)` (critical-path-weighted Ochiai, [06 §3.4](06-faultloom.md)) | `sources.traces` false or no `spectrum` atom | Ochiai/TraceRCA + CRISP [novel_building_blocks §Q3][nbb] |
| `change_prox` | `CH(s) · 1[max(I(s), E(s)) ≥ k_anom or Sil(s) = 1]` | `sources.events` false or no `change_proximity` atom | Causync channel; change-cohort idea [novel_building_blocks §Q5][nbb] |
| `graph_walk` | personalised PageRank score (§3.4) | G has no edge, or `max_s A(s) = 0` | MicroRank family |

Every ranker also abstains when its quantised scores are **constant over U** (`abstain_on_constant`): a constant vote adds the same 1/(60 + 1) to every service, which carries no information but compresses the normalised scores Causentra works with.

Notes:

- `prism_m` uses raw robust z, as PRISM's scorer is `|x − c|/s` with max pooling; `prism_m.combine: conj` (`min(I', E)`) is PRISM's alternative form and an ablation. PRISM reported 0.68 / 0.91 / 0.87 (Top-1 / Top-3 / Avg@5) over 735 RCAEval cases, preprint without code [rcaeval_facts §Published baselines][rf-baselines]; our `prism_m` is a re-implementation inside a different pipeline and is reported as such.
- `baro_rs` and `nsigma` here are **two-sided** (scores are absolute deviations). RCAtlas found the reference BARO and N-Sigma score only upward deviations, so a root whose traffic drops ranks last [sota_methods §Q1][sm]. The faithful RCAEval BARO and N-Sigma baselines are run separately by bench from RCAEval's own code ([04 §4](../04-evaluation-protocol.md)).
- Context-klass series (traffic) are not atomised ([06 §11 Q4](06-faultloom.md)), so `baro_rs` differs from RCAEval BARO, which also scores `_workload` columns.

### 3.3 Gating rule (gated RRF)

A ranker votes only if its channel exists for the case and its scores are not constant. Channels: `prism_m`, `baro_rs` → robust_z atoms (any source); `nsigma` → nsigma atoms; `cp_sbfl` → traces; `change_prox` → events; `graph_walk` → graph edges plus at least one anomaly. With no traces (all of Sock Shop in RCAEval [rcaeval_facts §Datasets and telemetry][rf-data]) `cp_sbfl` abstains; with no change events (all public benchmarks) `change_prox` abstains. Missing channels therefore never inject a vote ([02 §9](../02-architecture.md)).

### 3.4 `graph_walk`: personalised PageRank

The walker starts at anomalous services and moves from a caller to the callees it depends on, i.e. **against** the direction in which anomalies propagate (callee → caller), as [02 §6.7](../02-architecture.md) fixes it. Mass accumulates at services that are anomalous themselves and whose callees are not.

Definitions over U (sorted A→Z):

- `A(s) = max(I(s), E(s), prism_m.silence_z · Sil(s))`; `a(s) = A(s) / max_t A(t)`; `aI(s) = I(s) / max_t A(t)`.
- Personalisation `p(s) = A(s) / Σ_t A(t)`.
- Edge share `ŵ(u, v) = weight(u→v) / Σ_{v'} weight(u→v')` over u's callees in G (`graph.edges.weight`, 1.0 if unknown).
- Row of the transition matrix for node *u*:
  - to callee *v*: `f(u, v) = ŵ(u, v) · a(v)`, and `F_u = Σ_v f(u, v)` (≤ 1);
  - stay at *u*: `(1 − F_u) · aI(u)` if `graph_walk.self_loop` (default true), else 0;
  - restart (jump according to `p`): the remainder, `(1 − F_u) · (1 − aI(u))` (or `1 − F_u` without the self-loop).
  Every row sums to 1, so no node is absorbing and leaves do not collect mass merely for being leaves.
- Iterate `π ← (1 − d) · p + d · πP` from `π₀ = p` for exactly `graph_walk.iterations` = 200 steps, `d = 0.85` (the standard damping; 0.85²⁰⁰ ≈ 7.5e-15, below the 1e-12 quantisation). Restart mass is computed once per step as `R = fsum(π(u) · restart(u))` and added as `d · R · p(s)`.
- Score = `π(s)`.

A fixed iteration count (no convergence test) makes the result independent of floating-point stopping decisions.

### 3.5 Mode and fault-class rule table

`classify(s)` evaluates rules in order; the first match wins. Thresholds are `k_anom` and the config keys shown. The rules encode the evidence patterns in the notes; none of them has been measured on RCAEval yet, so their accuracy is an output of the evaluation (fault-type accuracy, [04 §7](../04-evaluation-protocol.md)), not an assumption.

| # | Condition on *s* | `mode` | `fault_class` |
|---|---|---|---|
| R1 | `CH(s) ≥ mode.change_min_proximity` (e⁻¹, i.e. the change is within one τ_change of onset) and (`max(I, E) ≥ k_anom` or `Sil = 1`) | `change` | `config` if the strongest change atom has `event_kind` ∈ {config, flag}; otherwise the `fault_class` of the first matching rule among R2–R5, else `unknown` |
| R2 | `I(s) ≥ k_anom` and family of `topI(s)` ∈ {cpu, mem, disk, net} | `resource` | cpu→`cpu`, mem→`mem`, disk→`disk`, net→`socket` |
| R3 | (`I(s) ≥ k_anom` and family of `topI(s)` ∈ {logs, self_time, other}) or `log_new_template{error_level_only: true}` ≥ 1 | `code` | `exception` if that new-template atom ≥ 1; else `error` if any `external_anomaly{family: errors, robust_z}` ≥ k_anom; else `unknown` |
| R4 | graph node kind of *s* ∈ {db, cache, queue, external} and (`Sil(s) = 1` or `E(s) ≥ k_anom`) | `dependency` | `dependency` |
| R5 | `I(s) < k_anom` and (`E(s) ≥ k_anom` or `edge_gap{in, p50} ≥ mode.edge_gap_min_ms`) | `network` | `loss` if any `external_anomaly{family: errors}` ≥ k_anom or tail ratio `edge_gap{in,p50} / edge_gap{in,p99} ≤ mode.tail_ratio` (0.5); else `delay` |
| R6 | otherwise | `unknown` | `unknown` |

R5 follows two observations: for DELAY and LOSS the root's internal metrics barely move and its external symptoms appear after other services' (internal-first in only 27.4% and 41.3% of cases [rcaeval_facts §Anomaly scoring methods][rf-methods], [§Onset and precedence][rf-onset]); a delay shifts the whole latency distribution while loss mostly inflates the tail through retransmission timeouts (earlier design notes; untested on RCAEval). The classification answers "if *s* were the root, which fault would it be"; a victim classified as `network` is expected and harmless because it is not the answer.

### 3.6 Indicator

1. If `mode = network`: `latency` (RCAEval scores both DELAY and LOSS against the latency indicator [rcaeval_facts §Ground truth and scoring][rf-scoring]).
2. Else if `I(s) ≥ k_anom`: the family of `topI(s)`.
3. Else if `E(s) > 0`: the family of `topE(s)`.
4. Else `other`.

The family is mapped to the RCAEval indicator string with `indicator_map`: cpu→`cpu`, mem→`mem`, disk→`diskio`, net→`socket`, latency→`latency`, **self_time→`latency`**, errors→`error`, logs→`logs`, traffic→`workload`, other→`unknown`. RE1 has no disk metric and RCAEval scores RE1 disk cases against `latency`; that dataset-specific rule lives in bench's scorer, not here [rcaeval_facts §Ground truth and scoring][rf-scoring], [§Data quirks][rf-quirks]. Ranks for RCAEval are written as `"{service}_{indicator}"` by Causentra (`ranks_rcaeval`).

### 3.7 Worked micro-example (numbers computed for this doc)

Four services, edges `frontend→checkout`, `frontend→currency`, `checkout→payment`, `checkout→currency` (weights 1.0), no change events. Atoms (robust z unless stated):

| Service | I | E | NS (nsigma) | SP (spectrum) |
|---|---|---|---|---|
| checkout | 9.0 (cpu) | 11.0 | 10.5 | 0.683 |
| currency | 2.0 | 4.5 | 5.0 | 0.210 |
| frontend | 1.2 | 14.0 | 16.0 | 0.258 |
| payment | 0.8 | 1.0 | 1.1 | 0.165 |

Ranker scores and ranks:

- `prism_m`: checkout 20 − ln 21 = 16.955; frontend 15.2 − ln 16.2 = 12.415; currency 4.485; payment 0.770 → ranks 1, 2, 3, 4.
- `baro_rs`: frontend 14.0, checkout 11.0, currency 4.5, payment 1.0 → frontend first: the classic max-deviation failure where the entry service accumulates the largest symptom [rcaeval_facts §Anomaly scoring methods][rf-methods].
- `nsigma`: frontend 16.0 first, checkout second.
- `cp_sbfl`: checkout 1, frontend 2, currency 3, payment 4.
- `graph_walk`: `a` = checkout 0.786, currency 0.321, frontend 1.0, payment 0.071; `aI` = 0.643, 0.143, 0.086, 0.057. Rows: frontend → checkout 0.393, → currency 0.161, stay 0.038, restart 0.408; checkout → currency 0.161, → payment 0.036, stay 0.517, restart 0.287; leaves stay `aI` and restart the rest. After 200 steps: checkout 0.5004, frontend 0.2565, currency 0.2085, payment 0.0346 → ranks 1, 2, 3, 4.
- `change_prox` abstains (no events).

Fusion (5 active rankers):

| Service | Ranks (prism_m, baro_rs, nsigma, cp_sbfl, graph_walk) | F |
|---|---|---|
| checkout | 1, 2, 2, 1, 1 | 3/61 + 2/62 = 0.081438392 |
| frontend | 2, 1, 1, 2, 2 | 2/61 + 3/62 = 0.081173982 |
| currency | 3, 3, 3, 3, 3 | 5/63 = 0.079365079 |
| payment | 4, 4, 4, 4, 4 | 5/64 = 0.078125000 |

With K = 2 the slate is [checkout, frontend]. `classify(checkout)`: R1 no (no change atoms); R2 yes (I = 9.0, family cpu) → `resource`/`cpu`, indicator `cpu`. `classify(frontend)`: I = 1.2 < 3, E = 14 ≥ 3 → R5 `network`, indicator `latency`. The margin between the two fused scores is small (RRF compresses differences); separating them is Causentra's job.

### 3.8 Edge cases

| Case | Behaviour |
|---|---|
| U has fewer than K services | slate has \|U\| candidates; `k` still records the configured K |
| All rankers tie two services on every vote | same F; order falls to internal-first, onset, name |
| Service in `case_manifest.services` with no atoms at all | stays in U with all scores 0; it can still appear in `all_scores` |
| `-db` services (e.g. Sock Shop `carts-db`) | separate services here; bench's coarse scorer strips `-db` like RCAEval [rcaeval_facts §Ground truth and scoring][rf-scoring] |
| `max_s A(s) = 0` | `graph_walk` abstains (no prior) |
| Self-edges in `graph.edges` | ignored |
| R5 tail ratio with `edge_gap{in,p99}` ≤ 0 or either atom absent | ratio test is false; `loss` only via the errors condition |

## 4. Configuration — `config/causatrix.yaml`

| Key | Default | Unit | Rationale / source |
|---|---|---|---|
| `slate.k` | 5 | candidates | 02 default; ablation {5, 10, 15} because DecompRCA retrieved 98–100% at top-15 on RCAEval [sota_methods §Q1][sm] |
| `rankers.enabled` | `[baro_rs, change_prox, cp_sbfl, graph_walk, nsigma, prism_m]` | — | 02 §6.7 |
| `rrf.k` | 60 | — | Cormack et al. 2009 (earlier notes); 02 |
| `rrf.weights.<ranker>` | 1.0 | — | a priori (02: fixed, never tuned) |
| `rrf.gate` | true | — | gated RRF (02); `false` is an ablation |
| `abstain_on_constant` | true | — | a priori (§3.2) |
| `prism_m.combine` | `add` | — | PRISM default; `conj` ablation |
| `prism_m.silence_z` | 10.0 | z | a priori: a silent service counts at least as anomalous as a 10-z internal deviation; ablation 5 / 20 |
| `graph_walk.damping` | 0.85 | — | standard PageRank value, a priori |
| `graph_walk.iterations` | 200 | steps | fixed count; 0.85²⁰⁰ < 1e-12 |
| `graph_walk.self_loop` | true | — | a priori; ablation `false` |
| `mode.change_min_proximity` | 0.36787944 | — | e⁻¹, i.e. Δt ≤ τ_change for `exp(−Δt/τ)` |
| `mode.edge_gap_min_ms` | 5.0 | ms | a priori |
| `mode.tail_ratio` | 0.5 | — | earlier notes' DELAY-vs-LOSS rule (location shift vs tail-only), untested |
| `indicator_map` | §3.6 | — | RCAEval indicator vocabulary [rcaeval_facts §Ground truth and scoring][rf-scoring] |

## 5. Determinism and isolation rules

- Pure function; all iteration over sorted names; sums with `math.fsum`; no BLAS products; PageRank in plain Python floats over sorted adjacency lists (≤ 100 nodes, [02 §8](../02-architecture.md)).
- Ranks computed on `round(x, 12)` so last-bit differences in `math.log` between the Windows CRT and glibc cannot reorder services except at an exact 1e-12 boundary (§11 Q6). JSON floats are rounded to 9 decimals by `canonical_json`.
- Rankers are registered under entry point group `veyltrace.rankers` from `packages/causatrix/pyproject.toml`; there is no registry dict in code.
- Allowed imports: `veyltrace_core`, `veyltrace_contracts`, `veyltrace_faultloom` (atom-kind constants and `atom_sources` only), `numpy`, `pyarrow`, `networkx`, stdlib. Banned: `veyltrace_llm`, LLM/HTTP clients, `socket`, `torch`, `transformers`, `pandas`.

## 6. Missing data and failure behaviour

| Missing | Effect |
|---|---|
| traces | `cp_sbfl` abstains; `graph_walk` runs if topology or log edges exist |
| events | `change_prox` abstains; R1 never fires |
| metrics only | `prism_m`, `baro_rs`, `nsigma` vote; mode rules lose `edge_gap` and log inputs |
| graph without edges | `graph_walk` abstains; R4 uses node kinds if present |
| no anomaly atoms at all | every ranker abstains; empty slate (§3.1) |
| `evidence` or `graph.nodes` file absent | `EngineResult.status = failed` |

Fewer active rankers is recorded in `rankers_active`; bench reports results by active-ranker pattern for the telemetry-ablation protocol.

## 7. Tests

**Unit**: each ranker formula on hand-built atoms; competition ranking with ties; gating (each abstention condition, including constant scores); PageRank rows sum to 1 and the §3.7 numbers reproduce to 1e-6; each rule R1–R6 and each indicator branch; `all_scores` ordering.

**Golden** (`golden("slate", "synth-0N")`, fixtures in `packages/causatrix/fixtures/`). Behavioural checklist for the fixture reviewer and the bench smoke experiment:

| Case | Expected |
|---|---|
| synth-01 CPU hog | injected service rank 1; `mode = resource`, `fault_class = cpu`, indicator `cpu` |
| synth-02 network delay | injected service in the slate; `mode = network`, indicator `latency` |
| synth-03 error injection | injected service rank 1; `mode = code` |
| synth-04 change-induced regression | `change_prox` active; injected service rank 1; `mode = change` |
| synth-05 no-fault | rankers may abstain on constant scores; no candidate has I or E ≥ k_anom |

**Property tests**: permutation of evidence rows → identical slate; adding a ranker that abstains never changes F; monotonicity (raising I(s) never lowers `prism_m` or `baro_rs` rank of *s*); RRF bounds (`F ≤ |active| / 61`); renaming services consistently relabels the slate.

**Real-case smoke**: the same three RE2 cases as FaultLoom; `rankers_active` must be {baro_rs, graph_walk, nsigma, prism_m} on RE2-SS (no traces, no events) and add `cp_sbfl` on RE2-OB/TT.

## 8. Performance budget

≤ 1 s and ≤ 300 MB per RE2 case (*estimate*; PRISM-style scoring runs in milliseconds [rcaeval_facts §Published baselines][rf-baselines], PageRank on ≤ 100 nodes × 200 steps is ~10⁵ operations). Causentra's T9 calls `rank()` up to four times per case, so `rank()` must stay ≤ 250 ms on RE2-TT.

## 9. Evaluation hooks and ablations

| Hook | Bench method id / config | Purpose |
|---|---|---|
| Each ranker alone | `causatrix:<ranker>` (slate order from that ranker only) | baselines/ablations (R-09) |
| Fused slate without verifier | `causatrix:rrf` | "AI-off, no verifier" row |
| Leave-one-ranker-out | `rankers.enabled` minus one | contribution of each channel |
| Ungated RRF | `rrf.gate: false` | value of gating |
| Fusion rule | `fusion.method` ∈ {rrf, combsum_minmax, borda} | fusion shoot-out; RRF stays the default [novel_building_blocks §Q8][nbb] |
| K sweep | `slate.k` ∈ {5, 10, 15} | Retrieval@K vs set size |
| PRISM form | `prism_m.combine: conj` | |
| Walk variant | `graph_walk.self_loop: false` | |
| Rule table | — | fault-type accuracy and fine-grained AC@k from `mode`/`fault_class`/`indicator` |

Bench reads `slate.json` to compute Retrieval@K and Rerank@1 ([04 §7](../04-evaluation-protocol.md)).

## 10. Tasks and milestones ([07](../07-roadmap.md))

| ID | Scope | Milestone |
|---|---|---|
| R-00 | stub slate on synth | M0 |
| R-05 | bench baselines that `causatrix:*` rows are compared against | M1 |
| R-09 | six rankers, gated RRF, rule table, slate; each ranker reported alone | M2 |
| R-11 | full RE2 run, scorecard | M2 |
| R-16 | experiment matrix ablations | M4 |

## 11. Open questions (each with a default)

1. ~~"Reversed call graph" wording.~~ *Resolved in 02 §6.7 (2026-10-30):* the walk goes caller → callee, against propagation (§3.4).
2. **Context-klass evidence.** *Default:* none ([06 §11 Q4](06-faultloom.md)).
3. ~~No `socket` fault class.~~ *Resolved in 03 §1 (2026-10-30):* `socket` added (RCAEval RE2 has 15 socket cases per system, [rcaeval_facts §Datasets and telemetry][rf-data]); R2 maps net → `socket`.
4. **K = 5 vs recall.** *Default:* 5 (02). Revisit at M2 if Retrieval@5 on RE1 (tuning set) is below 0.95.
5. **`prism_m.silence_z`.** *Default:* 10.0 a priori; sweep on RE1/synth only.
6. **Cross-platform `math.log`.** Quantisation to 1e-12 makes reorderings vanishingly rare but not impossible. *Default:* accept; the determinism gate runs on Ubuntu CI and on each laptop, and any mismatch is a P1 bug.
7. **Rule table on RE3 code faults (F1–F5).** No fault-class mapping exists in RCAEval for F1–F5. *Default:* report mode accuracy (`code`) only.
8. **`availability` fault class** (pod kill, container restart, pod failure; added to 03 §1 on 2026-10-30) has no rule yet. *Default:* not emitted (a silent non-dependency service falls through to R5/R6); any new rule is decided on synth/lab cases only, never on test splits.

## 12. References

- [02 §6.7, §6.9, §9](../02-architecture.md); [03 §7–§8](../03-contracts.md); [07](../07-roadmap.md); [06-faultloom](06-faultloom.md); [09-causentra](09-causentra.md); [04-evaluation-protocol](../04-evaluation-protocol.md).
- [sota_methods_2026 §Q1 (DecompRCA, RCAtlas), §Q3 (GALA+ RRF, recall-first)][sm]
- [novel_building_blocks §Q3 (CP-SBFL), §Q5 (changes), §Q8 (fusion)][nbb]
- PRISM, BARO, SBFL, network faults and RCAEval scoring: [rcaeval_facts §Anomaly scoring methods][rf-methods], [§Published baselines][rf-baselines], [§Traces][rf-traces], [§Onset and precedence][rf-onset], [§Datasets and telemetry][rf-data], [§Ground truth and scoring][rf-scoring], [§Data quirks][rf-quirks]

[sm]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/sota_methods_2026.md
[nbb]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/novel_building_blocks.md
[rf-data]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#datasets-and-telemetry-per-system
[rf-scoring]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#ground-truth-and-scoring
[rf-quirks]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#data-quirks
[rf-methods]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#anomaly-scoring-methods
[rf-baselines]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#published-baseline-numbers
[rf-onset]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#onset-and-precedence
[rf-traces]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#traces-spectrum-and-timing

