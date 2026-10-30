# 09 · Causentra — verify hypotheses with fixed trials and decide the verdict

> Status: v0.1-draft · Lane: Reason · Master: [docs/02-architecture.md §6.9](../02-architecture.md) · Contracts: [docs/03-contracts.md §10](../03-contracts.md) (output), §7, §8, §9.1, §6, §4.2, §5.1, §2.1, §12.1 (inputs) · Last updated: 2026-10-30

## 1. Purpose and scope

Causentra is the only engine that sets the verdict ([02 §2 P1](../02-architecture.md)). It takes the deterministic slate, any proposals from Relentra, and the evidence FaultLoom computed (including the symmetric claim checks), runs ten fixed trials on every candidate, applies the fixed decision function, builds a split-conformal candidate set, and returns one of `CONFIRMED`, `LIKELY`, `INCONCLUSIVE` or `NO_FAULT`, with the asks that would settle an inconclusive case.

Why a deterministic verifier: unverified LLM agents fabricate causes outside the label space, treat silence as health and skip edge tests; an LLM-based verifier raised Acc@1 in all 14 DiagGuard configurations (+3.5 to +35.1 pp) but did not reduce "semantics misread" errors (11.8% → 13.6%), so those checks belong in code [verified_agents §Q2][va]. One planted false sentence made models name a decoy first in 21–42% of flagged RE2 cases [benchmarks_and_testbed §Q2][bt]. Our searches up to Oct 2026 found no RCA work that outputs conformal candidate sets, though close work exists ([02 §2 P4](../02-architecture.md); [novel_building_blocks §Q7][nbb]; [sota_methods §Q6][sm]).

Out of scope: creating evidence (FaultLoom), ranking (Causatrix), any model call, reading answer keys. Fitting the calibration is done by bench ([04 §5](../04-evaluation-protocol.md)); Causentra receives the fitted values through `ctx.config`.

## 2. Inputs and outputs (exact fields)

### 2.1 Inputs

| Input | Fields read |
|---|---|
| `slate` ([03 §8](../03-contracts.md)) | `k`, `candidates[].{rank, service, component, indicator, mode, fault_class, fused_score}`, `all_scores[]` |
| `evidence` (§7) | all columns; engine atoms and `claim_check` atoms |
| `proposals` (§9.1), optional | `status`, `proposals[].{proposal_id, hypothesis.service, claims[].{claim_id, predicate, args}}` |
| `graph.nodes` / `.edges` / `.paths` (§6) | `node`, `kind`, `is_entry`; `src`, `dst`, `provenance`; `candidate`, `path_rank` |
| `onsets` (§4.2) | `entry_services` |
| `alignment` (§5.1) | `tolerance_ns` |
| `case_manifest` (§2.1) | `case_id`, `dataset`, `sources` |
| `RunContext` | `run_id`, `ai_mode`, effective config |
| `ctx.config.calibration` | content of `config/calibration/<family>.json` (q̂, τ_nf, split metadata), loaded by core's config loader; never read from `bench/` (§3.7) |

Shared values: `k_anom = thresholds.anomaly_z` (`config/core.yaml`, 3.0); `tol_ms = tolerance_ns / 1e6`; per-service `I(s)`, `E(s)`, `Sil(s)`, `onset_ms(s)` exactly as in [07 §2.1](07-causatrix.md). Causentra imports Causatrix's pure `rank()` and `classify()` and FaultLoom's predicate registry (entry point group `veyltrace.predicates`) and `validate()`.

### 2.2 Output: `verdict.json` ([03 §10](../03-contracts.md))

| Field | Filled by |
|---|---|
| `schema_version`, `case_id`, `run_id` | contract version; `case_manifest`; `RunContext` |
| `status` | §3.9 |
| `root` | §3.9: `{service, component, indicator, fault_class, mode}` of the leader, or null |
| `candidate_set` | §3.7: `{service, component, v, nonconformity}`, sorted by `v` desc, ties in `ranked` order |
| `ranked` | every decision-pool candidate in tie-break order (§3.6): `rank`, `service`, `component`, `indicator`, `fault_class`, `v`, `fused_score`, `origin` (`slate` or `proposal`), `trials[]` (`{id, result, reason?, atoms}` in order T1…T10, non-applicable trials omitted) |
| `confidence` | `{level, margin, alpha, q_hat, set_size}` (§3.9) |
| `asks` | §3.11 |
| `ranks_rcaeval` | §3.12 |
| `proposals_accepted`, `proposals_rejected` | §3.10 |
| `calibration` | `{family, sha256}` of the file used (§3.7) |
| `params_sha256` | `sha256(canonical_json(<effective causentra config section>))` |
| `verdict_hash` | §3.13 |

## 3. Algorithm

### 3.1 Order of operations

1. Load and validate inputs; build U, the derived quantities, the call graph G.
2. Validate proposals and build the decision pool (decision step 1, §3.2).
3. Base score `S0` (step 2, §3.3).
4. Run trials T1–T10 for each decision-pool candidate (§3.4).
5. Claim sum and verified score `V` (step 3, §3.5); round `V` to 9 decimals; every later comparison uses the rounded value.
6. Order the decision pool (step 6, §3.6).
7. Nonconformity and conformal set (step 4, §3.7).
8. Status, root, confidence (step 5, §3.8–§3.9).
9. Proposal decisions, asks, `ranks_rcaeval` (§3.10–§3.12).
10. Assemble, hash, write `verdict.json` (§3.13).

### 3.2 Decision step 1 — decision pool

`DecisionPool = slate.candidates[].service ∪ {hypothesis.service of admitted proposals}`. This is the 02 §4 **decision pool**; FaultLoom's **claim-pass pool** (slate ∪ every proposed candidate) is larger and only determines which candidates get `claim_check` atoms.

A proposal is considered only if `proposals.status ∈ {complete, budget_exhausted}`; proposals are processed in `proposal_id` order and only the first `proposals.max` (5, Relentra's hypothesis budget [02 §6.8](../02-architecture.md)) are eligible. A proposal's service *c* is **admitted** when:

1. *c* ∈ `graph.nodes.node` (else rejected `unknown_entity`);
2. at least one of its claims is valid ([06 §3.5](06-faultloom.md)), has polarity *supports*, and its `claim_check` atom for candidate *c* has `holds = true` (else rejected, §3.10).

Claims that fail FaultLoom's `validate()` (`unknown_predicate`, `bad_args` such as a `subject` key in `args`, or an unknown service argument; constrained decoding should make these impossible, so they signal a malformed proposal) never hold. They do not block admission (02 §6.9 step 1 asks only for one holding supporting claim, and FaultLoom builds the same pool for `intervention` atoms, [06 §3.6](06-faultloom.md)), but they make T10 fail (`claim_invalid`).

A service that is already in the slate keeps `origin = slate` even when a proposal names it; admission then only matters for `proposals_accepted`. Turning the AI off can therefore never remove a slate candidate: proposers can only add ([report][report], "Proposals are data; predicates are code").

### 3.3 Decision step 2 — base score

`S0(c) = fused_score(c) / max_{c' ∈ DecisionPool} fused_score(c')`, with `fused_score` from `slate.all_scores` (every service has one). If the maximum is 0, `S0(c) = 0` for all.

### 3.4 Trials

Each trial returns `pass`, `fail` or `untestable(reason)` with the atom IDs it used. A trial that is **not applicable** to a candidate (its precondition in the table is false) is omitted from `trials[]` and contributes no factor. Mandatory trials are T1–T4 for every candidate, plus T10 for candidates with `origin = proposal`.

| ID | Trial (02 §6.9) | Applicable | `pass` | `fail` (reason) | `untestable` (reason) | Atoms used |
|---|---|---|---|---|---|---|
| T1 | **Origin**: internal anomaly not explained by callees | always | `I(c) ≥ k_anom` or `Sil(c) = 1`, and no direct callee *d* (edge c→d) has `I(d) ≥ I(c)` with `onset_ms(d) ≤ onset_ms(c) + tol_ms` (a missing onset counts as "not later") | `no_internal_anomaly`; `explained_by_callee:<d>` | `no_internal_series`: *c* has no `internal_anomaly` robust_z atom and no `silence` atom | `topI(c)`, compared callees' `topI`, `silence` |
| T2 | **Precedence**: onset ≤ dependents' onsets (aligned, tolerance) | always | `onset_precedence{dependents}` ≥ `trials.T2.min_fraction`; or *c* has a self onset and no anomalous dependents (vacuous) | `dependent_earlier` | `no_onset`: no `onset_precedence{self}` atom | `onset_precedence` atoms |
| T3 | **Propagation**: anomalous upstream services reachable from *c* | always | `propagation{entry}` = 1.0 and (`propagation{path}` absent or ≥ `trials.T3.min_path_anomalous_fraction`) | `entry_unreachable`; `path_not_anomalous` | `no_graph_edges`; `no_anomalous_entry` | `propagation` atoms |
| T4 | **Silence check**: *c* is not judged healthy because something is silent | always | *c* has a `silence` atom and no service reachable from *c* along call edges (descendant, ≠ c) has `silence` = 1 | `silent_callee:<d>` | `no_silence_status`; `no_graph_edges` (cannot inspect descendants) | `silence` atoms |
| T5 | **Latency accounting**: self-time increase explains ≥ 30% of entry latency increase | `sources.traces` | `self_time_share(c)` ≥ `trials.T5.min_share` (0.30) | `share_below_min` | `no_latency_increase`: no `self_time_share` atom | `self_time_share` |
| T6 | **Change alignment**: change on *c* precedes onset within τ | always | `CH(c)` ≥ `trials.T6.min_proximity` (e⁻¹ ⇔ Δt ≤ τ_change) | `no_recent_change` | `no_events`: `sources.events` false | `change_proximity` atoms |
| T7 | **Peer contrast**: affected replica differs from peers | *c* has a `peer_contrast` atom | max `peer_contrast` ≥ `trials.T7.min_gap` | `peers_alike` | — | `peer_contrast` atoms |
| T8 | **Intervention**: anomaly not explained by parents (restricted CI test) | always | `intervention` atom value (`stat_resid`) ≥ `k_anom` | `explained_by_parents` | `intervention_unavailable`: no `intervention` atom (CI test untestable, or *c* beyond `intervention.max_candidates`; [06 §3.6](06-faultloom.md)) | `intervention` atoms |
| T9 | **Leave-one-source-out**: stays in top-K when each source is dropped | ≥ 2 of {metrics, logs, traces, events} present | for every present source *s*, *c*'s position in `rank()` recomputed on atoms with *s* ∉ `atom_sources(atom)` and graph edges whose `provenance` ⊄ {*s*} is ≤ `slate.k` | `drops_out_without:<s>` (first such source, sorted) | — | none (rank positions in `reason` only on fail) |
| T10 | **Claim checks**: every Relentra claim on *c* re-evaluates true | `origin(c) = proposal` | every claim (from proposals naming *c*) is valid and its `claim_check` atom for *c* has `holds = true` | `claim_false:<claim_id>`; `claim_invalid:<claim_id>` | `claim_unevaluable`: none false or invalid but ≥ 1 has `holds = null` | that candidate's `claim_check` atoms |

Interpretation notes:

- **T1** checks the PRISM premise that the root shows internal anomalies while its dependents show mainly external ones [rcaeval_facts §Anomaly scoring methods][rf-methods]. Network faults (DELAY, LOSS) often lack internal anomalies, so T1 will fail on them; the paper reports that abstention rather than tuning it away ([report][report], Conclusion). A network-mode variant is an open question (§11 Q2).
- **T4** is read as the "silence-as-health" coverage check from the failure taxonomy (30% of Sonnet's and 44.2% of Qwen's failed runs [verified_agents §Q2][va]): a candidate whose callee went silent is likely a victim of that callee.
- **T9** re-ranks with FaultLoom's per-source atoms; the graph is filtered by edge provenance. It is a cheap in-run version of the telemetry-ablation protocol ([04 §5](../04-evaluation-protocol.md)).
- **T10** applies only to proposal-origin candidates. Applying it to slate candidates would let a false claim lower a slate candidate's score, which would break the property that AI-on vs AI-off differences come only from code-verified evidence ([02 §6.9](../02-architecture.md) step 3).

### 3.5 Decision step 3 — verified score

```
V(c) = S0(c) × Π_t factor(t, c) × (1 + clip(Σ_p w_p · polarity_p · holds_p(c), −0.3, +0.3))
```

- `factor`: pass 1.0; mandatory trial untestable 0.85, failed 0.25; supporting trial untestable 1.0, failed 0.9 (02); the product runs over applicable trials only.
- The sum runs over the distinct (predicate, canonical args) pairs evaluated in the claim pass. `holds_p(c)` = 1 if the `claim_check` atom for *c* has `holds = true`, else 0 (false or null). `polarity_p` ∈ {+1, −1} from the library; `w_p` = `predicates.<name>.weight` (03 defaults: 0.10, 0.05 for `template_new_in_incident`, `error_rate_above`, `on_critical_path`).
- Clip bounds `claims.clip_low = −0.3`, `claims.clip_high = +0.3`.
- With `ai.mode = off` there are no claim atoms; the sum is empty and `V = S0 × Π factor`.
- `V` is rounded: `V9(c) = round(V(c), 9)`.

### 3.6 Decision step 6 — ordering and tie-break

Sort the decision pool by `(−V9(c), 0 if I(c) ≥ k_anom else 1, onset_ms(c) (missing = +∞), c)`: verified score, internal-first, earliest aligned onset, name A→Z. `ranked[].rank` is 1-based in this order. The **leader** is the first candidate if the decision pool is non-empty and its `V9 > 0`.

### 3.7 Decision step 4 — conformal candidate set

**Nonconformity** of decision-pool candidate *c*: `s(c) = round(1 − V9(c) / V9(leader), 9)` (02: `1 − V(c)/max V` over the decision pool); if there is no leader, `s = 1.0` for all. The verdict field is `nonconformity`.

**Set**: `C = {c ∈ DecisionPool : s(c) ≤ q̂}`. The leader has `s = 0`, so `C` is non-empty whenever a leader exists. Services outside the decision pool are never in `C`; Retrieval@K (truth in the slate) and decision-pool retrieval bound coverage and are reported next to it ([02 §6.9](../02-architecture.md)).

**Where q̂ comes from.** Bench fits it and writes `config/calibration/<family>.json`; core's config loader puts its content in `ctx.config.calibration`. Causentra never opens files under `bench/` or `lab/` ([02 §9](../02-architecture.md), isolation rule 3). The family is `causentra.calibration.family` (set by the experiment YAML), else `calibration.family_map[case_manifest.dataset]`. The fitting rule, specified here so bench and Causentra agree ([04 §5.4](../04-evaluation-protocol.md)):

1. Calibration cases: fault cases of the calibration split only, run through the full pipeline with the same config and the same AI arm as the cases the file will be applied to.
2. Calibration score of a case = nonconformity of the **true** root: `s(root)` read from `verdict.ranked`, where the root matches a decision-pool service after bench's name normalisation (`-db` stripped, as RCAEval's coarse scorer does [rcaeval_facts §Ground truth and scoring][rf-scoring]; if two services match, the smaller score). If the root is **not in the decision pool**, the score is **+∞** (02 §6.9).
3. With `n` scores and level α: `q̂` = the ⌈(n + 1)(1 − α)⌉-th smallest score; `q̂ = +∞` if that index exceeds `n` (n < 9 at α = 0.10).

**Guarantee.** If calibration and test cases are exchangeable and `q̂` is finite, then `P(root ∈ C) ≥ 1 − α` marginally: a finite score ≤ q̂ means the root is in the decision pool, and then `s(root) ≤ q̂` puts it in `C`. When `q̂ = +∞` (too few calibration cases, or more than α of calibration roots outside the decision pool), `C` is the whole decision pool, coverage is bounded by decision-pool retrieval, and the run is flagged in the results. Coverage is always measured on held-out cases, never on the calibration split. Exchangeability fails across systems, so leave-one-system-out coverage is reported as an empirical result, not a guarantee [novel_building_blocks §Q7][nbb]. In `verdict.confidence.q_hat`, +∞ serialises as `null` (`canonical_json` maps ±inf to null).

**Uncalibrated mode** (no calibration for the family; R-10, "no conformal yet"): `q̂ = calibration.uncalibrated_q_hat` (0.0: the leader plus exact ties), `τ_nf = no_fault.default_tau`, and `verdict.calibration = {family: "uncalibrated", sha256: sha256(canonical_json({"family": "uncalibrated"}))}` ([02 §6.9](../02-architecture.md)); coverage is never reported from uncalibrated runs.

**Calibration file content** (contract `calibration`, [03 §12.1](../03-contracts.md); no per-case labels): `{schema_version, family, ai_arm, alert_protocol, alpha, n, rank_index, q_hat, no_fault: {beta, m, rank_index, tau_nf, calibrated, sources}, split: {seed, fold, cases_sha256}, scores_sha256, config_sha256, code_commit, experiment_id}`, where `no_fault.sources` lists the normal-window sources used (`synth-05`, `veyllab`, `rcaeval_pre_injection`) and `q_hat` null means +∞. Its SHA-256 goes into `verdict.calibration.sha256` and `run_manifest.calibration_sha256`.

### 3.8 `NO_FAULT` test and its calibration

Statistic ([02 §6.9](../02-architecture.md) step 5): `M` = the maximum of the entry services' external `score_norm` and every service's internal `score_norm`, with *entry* = `onsets.entry_services`. Causentra reads atoms, not `anomalies`, so it computes `M = log1p(max(max_{e ∈ entry} E(e), max_{s ∈ U} I(s)))` from the `robust_z` atoms. This equals the 02 definition because Anomara defines `score_norm = log1p(score)` for robust z and `log1p` is increasing; FaultLoom tests the equality ([06 §7](06-faultloom.md)). Only the `robust_z` detector enters `M` (`no_fault.detector`, 02 §6.9).

`NO_FAULT` iff no service is silent (`Sil(s) = 1` for no *s* ∈ U, i.e. no `silence` atom above threshold) and `M ≤ τ_nf`. `τ_nf` is the (1 − β)-quantile of `M` over **normal windows** of the calibration split, β = 0.10, so at most about 10% of normal windows are expected to be flagged as faults. Normal windows come from `synth-05`, VeylLab no-fault captures and RCAEval pre-injection segments (alert placed before injection, windows clamped; [04 §5.4](../04-evaluation-protocol.md)). Finite-sample rule: with `m` normal windows, `τ_nf` = the ⌈(m + 1)(1 − β)⌉-th smallest `M`, which keeps the false-alarm rate on exchangeable new normal windows ≤ β. If that index exceeds `m` (m < 9), `τ_nf` is not fitted: `τ_nf = no_fault.default_tau = log1p(3.0) = 1.386294361` (the 3-sigma rule, the same as `k_anom`) and `no_fault.calibrated = false`.

When `NO_FAULT` holds, the candidate set is empty and `root` is null. The rate of wrong `NO_FAULT` on fault cases is measured, not guaranteed ([04 §7](../04-evaluation-protocol.md)). All published methods named false root causes during normal operation in PetShop, which is why the option exists [novel_building_blocks §Q7][nbb].

### 3.9 Decision step 5 — status, root, confidence

Let `top` = leader and `m` = margin = `(V_top − V_runner-up) / V_top` ([02 §6.9](../02-architecture.md) step 5; equals `s(runner-up)`), `m = 1.0` if there is no runner-up, `m = 0.0` if there is no leader. `mand_ok` = every mandatory trial of `top` returned `pass` (`untestable` is not a pass). Rules in order:

| Status | Condition | `root` | `confidence.level` |
|---|---|---|---|
| `NO_FAULT` | §3.8 | null | `none` |
| `CONFIRMED` | `\|C\| = 1` and `mand_ok` and `m ≥ status.c_high` (0.30) | `top` | `high` |
| `LIKELY` | `mand_ok` and `\|C\| ≤ status.likely_max_set` (3) and `m ≥ status.c_med` (0.15) | `top` | `medium` |
| `INCONCLUSIVE` | otherwise | `top` if a leader exists, else null | `low` with a leader, `none` without |

`root = {service, component, indicator, fault_class, mode}`: for slate candidates copied from the slate entry; for proposal-origin candidates from Causatrix's `classify()` (the proposal's own `fault_class`/`indicator` are not used, since code, not the model, labels the fault). For `NO_FAULT`, `candidate_set = []`. `confidence = {level, margin: m, alpha, q_hat, set_size: |C|}`. The margin is relative (scale-free), so `c_high` and `c_med` keep their meaning when trial factors shift all scores.

### 3.10 Proposals accepted and rejected

Every proposal in `proposals.json` gets exactly one outcome, checked in this order ([03 §10](../03-contracts.md) reasons):

| Order | Reason | Condition |
|---|---|---|
| 1 | `budget` | beyond the first `proposals.max` by `proposal_id`, or `proposals.status` ∈ {failed, skipped} |
| 2 | `unknown_entity` | `hypothesis.service` ∉ `graph.nodes` |
| 3 | `unknown_predicate` | not admitted (§3.2) and any claim names a non-library predicate |
| 4 | `bad_args` | not admitted and any claim fails `validate()` on its arguments ([03 §9.1](../03-contracts.md): wrong keys or types, a `subject` key, an unknown service argument) |
| 5 | `claim_false` | not admitted: no valid supporting claim holds for its service (§3.2) |
| 6 | `trial_failed` | its service is in the decision pool and failed a mandatory trial (including T10 `claim_invalid`) |
| — | accepted | none of the above; listed in `proposals_accepted` |

`proposals_accepted` sorted ascending; `proposals_rejected` sorted by `proposal_id`. Proposal `rationale` text is never read.

### 3.11 Asks

Asks are generated by code for `LIKELY` and `INCONCLUSIVE` verdicts from a fixed template table; model-written asks in `proposals.asks` are not copied (they are display data for the card).

| Priority | Trigger (about `top`, or the case when there is no leader) | `kind` | `target` | `why` template |
|---|---|---|---|---|
| 1 | mandatory trial failed | `trial` | `<Tn>:<service>` | `mandatory trial <Tn> failed: <reason>` |
| 2 | trial untestable because a source is absent | `telemetry` | `<source>` | `<Tn> untestable without <source>` |
| 3 | mandatory trial untestable for another reason | `trial` | `<Tn>:<service>` | `mandatory trial <Tn> untestable: <reason>` |
| 4 | `\|C\| > status.likely_max_set` | `trial` | `set:<first three services of C, comma-separated>` | `candidate set has <n> members` |
| 5 | decision pool ≥ 2 and `m < status.c_med` | `context` | `<runner-up service>` | `runner-up within margin <m>` |
| 6 | no leader | `telemetry` | `all` | `no anomaly evidence in any source` |

Sorted by (priority, kind, target), de-duplicated, truncated to `asks.max` (5).

### 3.12 `ranks_rcaeval`

`"{service}_{indicator}"` for the decision pool in `ranked` order, then the remaining services of `slate.all_scores` in that order, with indicators from `classify()`; duplicates removed. It is filled for every status, so bench computes AC@k on ranks independently of abstention, and measures abstention separately ([04 §7](../04-evaluation-protocol.md)). Service names never contain `_` in the RCAEval systems, so RCAEval's `split("_")[0]` recovers the service [rcaeval_facts §Ground truth and scoring][rf-scoring].

### 3.13 `verdict_hash`

`verdict_hash = sha256_hex(canonical_json(verdict without the verdict_hash key))`. Every float in the verdict is already the 9-decimal value used in the decision, so the canonical rounding changes nothing. Replay re-runs steps 5–10 and must reproduce this hash ([02 §6.10](../02-architecture.md)).

### 3.14 Worked example (numbers computed for this doc)

Slate with K = 2 for brevity: A (fused 0.0480), B (0.0460). Relentra (brief mode) proposes C (fused 0.0300 in `all_scores`) with claims `onset_before(·, other_service = A)` and `zscore_above(·, signal = "cpu", k = 4)`; a second proposal names B with a claim on predicate `cpu_spiked` (not in the library). The case has traces, no events.

*Decision pool.* Proposal 1: C ∈ graph, both predicates known, `zscore_above` holds for C → C admitted (`origin = proposal`). Proposal 2: rejected `unknown_predicate`. Decision pool = {A, B, C}; the claim-pass pool is the same set because proposal 2 names B, already in the slate.

*Claim pass* (symmetric, for A, B and C):

| Predicate | A | B | C |
|---|---|---|---|
| `onset_before(·, A)` (supports, w 0.10) | null (subject = other) | false | true |
| `zscore_above(·, cpu, 4)` (supports, w 0.10) | true (A's cpu z = 9) | false | true |
| Σ w·polarity·holds | 0.10 | 0.00 | 0.20 |

*Trials* (only non-pass results listed): A — T6 untestable (no events), T8 untestable (no `intervention` atom); B — T5 fail (supporting), T6 and T8 untestable; C — T2 untestable (no onset; mandatory), T5 fail, T6 and T8 untestable, T9 fail (not in top-K when traces are dropped). T10 passes for C. Untestable supporting trials (T6, T8) cost nothing.

| | S0 | Π factor | 1 + clip(Σ) | V | s (nonconformity) |
|---|---|---|---|---|---|
| A | 0.0480/0.0480 = 1.0 | 1.0 | 1.10 | **1.1** | 0 |
| B | 0.958333333 | 0.9 (T5) | 1.00 | 0.8625 | 0.215909091 |
| C | 0.625 | 0.85 (T2) × 0.9 (T5) × 0.9 (T9) = 0.6885 | 1.20 | 0.516375 | 0.530568182 |

*Set and status.* The brief-arm calibration file has n = 89, α = 0.10 → rank index ⌈90 × 0.9⌉ = 81; say the 81st smallest score is `q̂ = 0.25`. `C = {A, B}` (0 and 0.2159 ≤ 0.25), size 2. Margin = 0.2159 ≥ 0.15 but < 0.30; A passed T1–T4 → **`LIKELY`**, root A, confidence medium. Proposal 1 accepted (C failed no mandatory trial: T2 is untestable, not failed); proposal 2 rejected `unknown_predicate`. Asks: priority 2 fires once (`{telemetry, events, "T6 untestable without events"}`); T8's untestability is not about a missing source and T8 is not mandatory, so it raises no ask.

*Same case, AI off.* No claims, C not in the decision pool: V(A) = 1.0, V(B) = 0.8625, s(B) = 1 − 0.8625/1.0 = 0.1375. With the AI-off calibration's `q̂` (say 0.20), `C = {A, B}`; margin 0.1375 < 0.15 → **`INCONCLUSIVE`**, root A, confidence low, asks `{telemetry, events, "T6 untestable without events"}` and `{context, B, "runner-up within margin 0.1375"}`. The AI's request for a cpu check moved the verdict, but only because code found the check true **for A**; the candidate the model proposed ended last.

### 3.15 Edge cases

| Case | Behaviour |
|---|---|
| Empty slate and no admitted proposal | decision pool empty → `INCONCLUSIVE`, `root = null`, ask priority 6 (unless `NO_FAULT` holds) |
| All V = 0 | no leader; all `s = 1.0`; `INCONCLUSIVE` with null root |
| Exact tie V1 = V2 | margin 0 → never `CONFIRMED`/`LIKELY`; order by internal-first, onset, name |
| Proposal names a slate service | no new candidate; still accepted/rejected by §3.10 |
| Same (predicate, args) claimed by several proposals | counted once in Σ |
| `proposals.status = failed` or `skipped` | treated as no proposals; any listed proposals are rejected `budget` |
| Calibration loaded for another `ai_arm` or `alert_protocol` than the run's | hard error (`EngineResult.status = failed`): the file applies only to the same arm and protocol ([03 §12.1](../03-contracts.md)); mixing would void the guarantee |
| `NO_FAULT` while proposals exist | proposals still get outcomes; `NO_FAULT` wins |

## 4. Configuration — `config/causentra.yaml`

| Key | Default | Unit | Rationale / source |
|---|---|---|---|
| `alpha` | 0.10 | — | 02 §6.9 |
| `factors.pass` / `untestable_mandatory` / `fail_mandatory` / `untestable_supporting` / `fail_supporting` | 1.0 / 0.85 / 0.25 / 1.0 / 0.9 | — | 02 §6.9 (a priori) |
| `mandatory` | `[T1, T2, T3, T4]` (+T10 for proposal origin) | — | 02 §6.9 |
| `claims.clip_low`, `claims.clip_high` | −0.3, +0.3 | — | 02 §6.9 |
| `predicates.<name>.weight` | 03 §7 table | — | 03 §7 (a priori) |
| `proposals.max` | 5 | proposals | Relentra budget, 02 §6.8 |
| `status.c_high` | 0.30 | relative margin | 02 §6.9 |
| `status.c_med` | 0.15 | relative margin | 02 §6.9 |
| `status.likely_max_set` | 3 | candidates | 02 §6.9 |
| `trials.T2.min_fraction` | 1.0 | fraction | literal reading of 02 ("≤ dependents' onsets"); §11 Q3 |
| `trials.T3.min_path_anomalous_fraction` | 0.5 | fraction | a priori |
| `trials.T5.min_share` | 0.30 | fraction | 02 §6.9 |
| `trials.T6.min_proximity` | 0.36787944 | — | e⁻¹ ⇔ Δt ≤ τ_change (Causync's τ) |
| `trials.T7.min_gap` | 3.0 | z | a priori, same scale as `k_anom` |
| `calibration.family` | null (set by experiments) | — | the file itself is `config/calibration/<family>.json`, loaded by core into `ctx.config.calibration` (02 §6.9) |
| `calibration.family_map` | `{re1-*: rcaeval-re1, re2-*: rcaeval-re2, re3-*: rcaeval-re3, nezha-*: nezha, fse26-tt: fse26, veyllab-*: veyllab, synth: synth}` | — | per benchmark family (02 §12 default) |
| `calibration.uncalibrated_q_hat` | 0.0 | — | R-10 "no conformal yet" behaviour |
| `no_fault.beta` | 0.10 | — | 02 §6.9 |
| `no_fault.detector` | `robust_z` | — | a priori (§3.8, §11 Q12) |
| `no_fault.default_tau` | 1.386294361 | score_norm | log1p(3.0): the 3-sigma rule (SimpleRCA's alert rule [rcaeval_facts §Published baselines][rf-baselines]); used only when fewer than 9 normal windows exist |
| `asks.max` | 5 | asks | a priori |

## 5. Determinism and isolation rules

- Pure function of inputs + config (including `ctx.config.calibration`); no clock, randomness or environment reads; no file access outside the run directory and the config the loader provides.
- `V`, `s` (nonconformity) and margins are rounded to 9 decimals before any comparison, so the decision equals what the canonical JSON shows.
- Iteration in sorted order: decision pool A→Z for computation, `proposal_id`/`claim_id` order for proposals, trials T1…T10 in numeric order.
- Permutation invariance: the verdict depends on the **set** of proposals and claims, not their order or wording (property test, §7); this is the deterministic answer to the decoy-sentence attack [report][report].
- Trials are registered under entry point group `veyltrace.trials` in `packages/causentra/pyproject.toml`.
- Allowed imports: `veyltrace_core`, `veyltrace_contracts`, `veyltrace_faultloom` (predicate registry, `validate`, `atom_sources`), `veyltrace_causatrix` (`rank`, `classify`), `numpy`, `pyarrow`, `networkx`, stdlib. Banned: `veyltrace_llm`, LLM/HTTP clients, `socket`, `torch`, `transformers`, `pandas`.

## 6. Missing data and failure behaviour

| Missing | Effect |
|---|---|
| `proposals.json` (AI off) | decision pool = slate; Σ empty; `proposals_accepted = []`, `proposals_rejected = []` |
| traces | T5 not applicable; T9 runs over remaining sources |
| events | T6 untestable for every candidate (uniform factor, ranking unchanged) |
| onsets for *c* | T2 untestable; T1 compares intensities only |
| graph edges | T3 untestable; T4 untestable; T1 cannot see callees (passes on intensity) |
| calibration for the family (`ctx.config.calibration` empty) | uncalibrated mode (§3.7) |
| `slate` or `evidence` | `EngineResult.status = failed`; no verdict |

Missing channels push the verdict toward `INCONCLUSIVE` with a telemetry ask ([02 §9](../02-architecture.md)).

## 7. Tests

**Unit**: every row of the trial table (pass, each fail reason, each untestable reason, non-applicability); V formula including clip at both ends; rounding before comparison; every status branch; every proposal reason in order; asks priorities and truncation; `ranks_rcaeval` composition; uncalibrated mode; q̂ index arithmetic (n = 8 → index 9 > n → q̂ = +∞, serialised null; n = 89 → index 81). The §3.14 example is a test with exact expected numbers.

**Golden** (`golden("verdict", "synth-0N")`). Checklist for fixture review and the bench smoke run:

| Case | Expected (uncalibrated fixture) |
|---|---|
| synth-01 CPU hog | leader = injected service; T1–T4 pass; status `CONFIRMED` or `LIKELY` |
| synth-02 network delay | leader may fail T1 (no internal anomaly); status `INCONCLUSIVE` acceptable, root's indicator `latency` |
| synth-03 error injection | leader = injected service; mode `code` |
| synth-04 change-induced regression | T6 passes for the injected service |
| synth-05 no-fault | `NO_FAULT`, `root = null`, `candidate_set = []` |

**Property tests** (hypothesis):

- order invariance: shuffling proposals and claims gives the same `verdict_hash`;
- AI cannot remove: for random proposals, every slate service is in `ranked`;
- monotone claims: adding a supporting claim that holds only for *c* never lowers `V(c)` and never raises another candidate's V;
- implementation check of the conformal rule on synthetic exchangeable scores: empirical coverage over 2,000 simulated test cases ≥ 1 − α − 0.02; the R-12 acceptance itself is on real **held-out** data (§10);
- clip: |Σ| beyond 0.3 never changes V beyond the clip bound.

**Decoy test** (bench): a planted proposal for a healthy service with fabricated claims must be rejected (`claim_false`) and must not change the leader.

**Real-case smoke**: three RE2 cases; replay twice; equal `verdict_hash`.

## 8. Performance budget

≤ 3 s and ≤ 500 MB per RE2 case including T9's ≤ 4 calls to Causatrix's `rank()` (*estimate*). Inside the 30 s deterministic budget ([02 §9](../02-architecture.md)).

## 9. Evaluation hooks and ablations

| Hook | Config | Question (RQ, [04 §2](../04-evaluation-protocol.md)) |
|---|---|---|
| Trial leave-one-out | `trials.disabled: [Tn]` (factor 1) | which trials carry accuracy and abstention quality (RQ1, RQ3) |
| Mandatory set | `mandatory` | strictness vs abstention on network faults (RQ3) |
| Factor sensitivity | `factors.*` sweep, reported as sensitivity, never selected on test | robustness of conclusions |
| Claim influence | `claims.clip_*` ∈ {0, ±0.15, ±0.3} | proposer lift attribution (RQ2) |
| α | 0.05 / 0.10 / 0.20 | coverage vs set size (RQ3) |
| Calibration family | per benchmark family vs per system vs LOSO | exchangeability (RQ3, RQ4) |
| `NO_FAULT` τ_nf | calibrated vs default; per normal-window source | abstention quality (RQ3) |
| Status thresholds | `c_high`, `c_med` swept to draw risk–coverage curves | selective accuracy (RQ3) |
| Planted decoys | bench `inject_proposals` | decoy rejection rate (RQ2) |

## 10. Tasks and milestones ([07](../07-roadmap.md))

| ID | Scope | Milestone |
|---|---|---|
| R-00 | stub verdict | M0 |
| R-10 | T1–T4, decision steps 1–3 and 5–6, uncalibrated set, `verdict_hash`; determinism gate on synth + 3 real cases | M2 (15 Nov) |
| R-13 | calibration fitting in bench; writes `config/calibration/<family>.json`, hashed into manifests | M3 |
| R-12 | T5–T10, conformal set, `NO_FAULT` threshold, statuses, asks; acceptance: **held-out** coverage within 1 − α ± 0.05 on RE2 (calibration cases excluded) and `NO_FAULT` false-alarm rate on held-out normal windows ≤ β + 0.05 | M3 (22 Nov) |
| O-14 (Observe) | cluster statistics in `bench/stats/` used to report coverage CIs | M3 |
| R-16 | the full matrix | M4 |

## 11. Open questions (each with a default)

1. ~~**Untestable penalises more than a failed supporting trial.**~~ *Resolved in 02 §6.9 (2026-10-30):* supporting untestable = 1.0, failed = 0.9; mandatory untestable = 0.85, failed = 0.25. Non-applicability (omitted trials) for T5, T7, T10 stays.
2. **T1 on network faults.** *Default:* strict (internal anomaly required). Ablation `trials.T1.network_edge_gap: true` would accept `edge_gap{in,p50} ≥ mode.edge_gap_min_ms` as origin evidence when `mode = network`; off by default.
3. **T2 strictness.** *Default:* `min_fraction = 1.0`; ablation 0.8 (one early, noisy dependent fails T2 otherwise).
4. **T4 interpretation** ("not healthy because silent"). *Default:* descendant-silence check (§3.4). Lead to confirm.
5. ~~**Step 1 wording.**~~ *Resolved in 02 §6.9 step 1 (2026-10-30):* admission needs one holding supporting claim (in `graph.nodes`); full T10 (all claims valid and true) is then a mandatory trial for proposal-origin candidates.
6. ~~**`bad_args` reason.**~~ *Resolved in 03 §10 (2026-10-30):* `bad_args` is a `proposals_rejected.reason` (§3.10).
7. ~~**Calibration file contract.**~~ *Resolved in 03 §12.1 (2026-10-30):* contract `calibration`, producer bench, consumer Causentra through `ctx.config`.
8. **Family names with folds.** Cross-fitting ([04 §5](../04-evaluation-protocol.md)) needs one file per fold. *Default:* the fold is part of the family id (`rcaeval-re2.foldA`), so the 02 path pattern `<family>.json` still holds.
9. ~~**Calibration per AI arm and alert protocol.**~~ *Resolved in 03 §12.1 (2026-10-30):* a file applies only to runs with the same `ai_arm` and `alert_protocol`. *Default (still open):* since the path is `<family>.json`, the family id also encodes arm and protocol (e.g. `rcaeval-re2.brief.oracle.foldA`); onset-shift runs reuse their protocol's file so coverage drift is visible.
10. **Margin with V_top = 0.** 02 defines `(V_top − V_runner-up)/V_top`; *default:* 0.0 when there is no leader.
11. ~~**Uncalibrated mode.**~~ *Resolved in 02 §6.9 (2026-10-30):* q̂ = 0, τ_nf = log1p(3), family `uncalibrated`, never used for coverage.
12. ~~**`NO_FAULT` statistic details.**~~ *Resolved in 02 §6.9 (2026-10-30):* `M` uses the `robust_z` detector only, and any silent service vetoes `NO_FAULT` (§3.8).

## 12. References

- [02 §2, §4, §6.9, §9](../02-architecture.md); [03 §7–§10](../03-contracts.md); [07](../07-roadmap.md); [06-faultloom](06-faultloom.md); [07-causatrix](07-causatrix.md); [04-evaluation-protocol](../04-evaluation-protocol.md).
- [verified_agents_local_llms §Q2 (verifier evidence, failure taxonomy), §Q3 (replay tiers), §Q6 (calibration, abstention)][va]
- [novel_building_blocks §Q4 (IDI trials), §Q7 (conformal, PetShop false alarms)][nbb]
- [sota_methods_2026 §Q6 (no RCA calibration work found)][sm]; [benchmarks_and_testbed §Q2 (decoy sentence, statistics)][bt]
- [rcaeval_facts §Anomaly scoring methods][rf-methods], [§Published baselines][rf-baselines], [§Ground truth and scoring][rf-scoring]; [v2 research report][report]

[va]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/verified_agents_local_llms.md
[nbb]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/novel_building_blocks.md
[sm]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/sota_methods_2026.md
[bt]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md
[rf-scoring]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#ground-truth-and-scoring
[rf-baselines]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#published-baseline-numbers
[rf-methods]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#anomaly-scoring-methods

[report]: ../../reports/Veyltrace%20v2%20SOTA%20root%20cause%20analysis.md
