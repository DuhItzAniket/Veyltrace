# 03 · Anomara — score anomalies per series, estimate onsets and the incident onset, flag silent services

> Status: v0.1-draft · Lane: Observe · Master: [docs/02-architecture.md §6.3](../02-architecture.md), §4 (steps 1 and 3), §5.1 · Contracts: [docs/03-contracts.md §4](../03-contracts.md) (reads §2, §2.6, §3) · Last updated: 2026-10-30

## 1. Purpose and scope

Anomara answers, for every series: how far does the incident window deviate from the baseline, in which direction, and when did it start? It then rolls series onsets up to services and picks one incident onset `t_onset`. Separately, it exports the public function `detect_alert(telemetry)`, which core's alert step calls under the detected-alert protocol to find the first sustained SLO breach on the entry service(s) ([02 §5.1](../02-architecture.md)).

**In scope**: detectors `robust_z`, `nsigma`, `bocpd`, `silence` (and the optional `tsfm` plugin); per-service onsets; `t_onset`; `detect_alert`.

**Out of scope**: writing `alert.json`, applying `alert.shift_s` and clamping windows (core's alert step); ranking services (Causatrix); evidence atoms (FaultLoom); clock alignment (Causync); the `NO_FAULT` threshold, which Causentra applies from calibration ([02 §6.9](../02-architecture.md)).

## 2. Inputs and outputs

**`run(ctx)` reads**

| Contract | Fields used |
|---|---|
| `case_manifest` | `system`, `data_start_ns`, `data_end_ns`, `services`, `sources` |
| `alert` | `protocol`, `t_alert_ns`, `shift_ns`, `detector?`, `windows.baseline`, `windows.incident` |
| `signal_cube.series` | all columns |
| `signal_cube.edges` | `caller, callee, window, calls` — only through the shared entry rule `veyltrace_causalith.entry.entry_services()` ([05-causalith §3.3](05-causalith.md)) |

**`detect_alert` reads** (called by core before Signalyth exists): `telemetry.spans` (`trace_id, span_id, parent_span_id, service, kind, start_ns, end_ns, status`), `telemetry.metrics` (`t_ns, service, name, value, unit`), and only the descriptive fields of `case_manifest` (`system` for the entry-service hint, `services`, `sources`, `data_start_ns`, `data_end_ns`). It never reads `t_alert_hint_ns` or `hint_source` (null/`none` under the detected protocol anyway, 03 §2.1), `signal_cube` or any window.

**Writes**

| Contract | Fields |
|---|---|
| `anomalies` | `series_id, service, component, family, klass, source` (copied from the series), `detector`, `score`, `score_norm`, `direction`, `onset_ns?`, `threshold`, `above_threshold` |
| `onsets.json` | `schema_version`, `t_onset_ns`, `method` (`second_external \| single_external \| t_alert_fallback`), `slo_breach_ns?`, `entry_services`, `per_service[{service, external_onset_ns?, external_onset_source?, internal_onset_ns?, internal_onset_source?, silent}]` |

`detect_alert` returns a value to core (§3.8); core writes it into `alert.json` (`t_alert_ns`, `detector.{entry_services, signal, threshold}`).

Every series gets exactly one `anomalies` row per **enabled** detector, even below threshold (03 §4.1), so FaultLoom can recompute evidence. `per_service` has one entry for every service in `case_manifest.services`. `entry_services` = `alert.detector.entry_services` when `alert.detector` is set, else the shared rule on `signal_cube.edges` (Causalith does the same, so the two engines always agree). `slo_breach_ns` = `alert.t_alert_ns − alert.shift_ns` when `alert.protocol = detected`, else null.

## 3. Algorithm

Notation: `B` = series points with `t_ns` in `alert.windows.baseline`; `I` = points in `alert.windows.incident`; `t_alert` = `alert.t_alert_ns`; floats are float64.

### 3.1 Effective step and grid

- `g` (effective step): for `source = metrics`, the median duration of runs of equal consecutive values, but at least the median spacing of observations. RCAEval metrics are 1 s rows that change about every 15 s, so `g ≈ 15 s` there ([rcaeval_facts §Metric step and windows][rf-step]). For traces and logs, `g` = the Signalyth bucket (10 s).
- **Grid series**: the last observed value in each epoch-aligned `g` bucket. Used by persistence, BOCPD and silence. Robust z and N-Sigma scores are computed on the original points.

### 3.2 `robust_z` — robust z with a multi-part scale floor

1. `med_B` = median of `B`; `MAD_B` = median `|x − med_B|`; `IQR_B` = q75 − q25 (linear interpolation).
2. Scale floor ([rcaeval_facts §Anomaly scoring methods][rf-methods]):

   `s_B = max(1.4826 · MAD_B, IQR_B / 1.349, ε(family, unit), η · |med_B|)`, `η = 0.02`.

   | `family` | `unit` | `ε` | Source |
   |---|---|---|---|
   | cpu | `cores` / other | 0.001 / 0.1 | a priori (0.1% CPU); RCAEval CPU looks like percent (unverified) |
   | mem | `bytes` | 1,048,576 | a priori (1 MiB) |
   | disk, net | any | 1.0 | a priori (source unit) |
   | latency, self_time | `ms` | 1.0 | a priori (1 ms latency) |
   | errors | `ratio` / other | 0.01 / 0.1 | a priori |
   | traffic | `1/s` / other | 0.1 / 1.0 | a priori |
   | logs | `1/s` / `count` | 0.1 / 1.0 | a priori |
   | other | any | 1e-6 | a priori (only prevents division by zero) |

   The floor exists because division by a near-zero scale made BARO rank a wrong metric at 4.6 × 10¹⁴ ([rcaeval_facts §Anomaly scoring methods][rf-methods]).
3. Signed `z_t = (x_t − med_B) / s_B`.
4. **Persistence** ([rcaeval_facts §Onset and precedence][rf-onset]): `z̃_t = min{|z_u| : u ∈ [t, t + p·g)}` if those points all share the sign of `z_t` and at least `p` grid buckets are covered; else `z̃_t = 0`. `p = 3`.
5. `score = max_{t ∈ I} z̃_t`; `score_norm = log1p(score)`; `threshold = 3.0` (PRISM's nominal threshold for z, [rcaeval_facts §Anomaly scoring methods][rf-methods]); `above_threshold = score ≥ threshold`.
6. `direction` = sign of `z` at the argmax (`up`/`down`; earliest argmax on ties); `flat` when `score = 0`.
7. `onset_ns` = first `t ∈ I` with `z̃_t ≥ threshold` (start of the first persistent run); null otherwise.
8. If `B` covers fewer than `robust_z.min_baseline_steps` (5) grid buckets: `score = 0`, `flat`, no onset.

Persistence is a deliberate difference from BARO's raw max: it stops one-sample spikes from setting the score. The `nsigma` detector keeps the raw max for parity with the baseline.

**Micro-example.** Baseline latency (ms) `[100, 102, 98, 101, 99, 100, 103, 97]`: `med = 100`, `MAD = 1.5 → 2.224`, `IQR = 101.25 − 98.75 = 2.5 → 1.853`, `ε = 1`, `0.02·100 = 2.0`, so `s_B = 2.224`. A persistent incident value of 130 gives `z = 13.49`, `score_norm = log1p(13.49) = 2.67`. A flat error counter (all zeros, unit `1/s`) has `s_B = ε = 0.1`; one error per second gives `z = 10`, `score_norm = 2.40` instead of infinity.

### 3.3 `nsigma`

`μ_B`, `σ_B` (population std, ddof = 0). `σ' = σ_B` if `σ_B > 0` else 1 (scikit-learn's zero-scale convention, which RCAEval's N-Sigma inherits through `StandardScaler`, [rcaeval_facts §Ground truth and scoring][rf-scoring]). `score = max_{t ∈ I} |x_t − μ_B| / σ'` (raw, no persistence). `score_norm = log1p(max_{t ∈ I} |x_t − μ_B| / max(σ_B, ε, η·|μ_B|))`. `threshold = 3.0`. `onset_ns` = first `t ∈ I` with `|x_t − μ_B|/σ' ≥ 3`. Direction as in §3.2.

### 3.4 `bocpd` — Bayesian online change-point onset

Adams & MacKay recursion over run lengths; BARO uses BOCPD for onset ([rcaeval_facts §Anomaly scoring methods][rf-methods]). Here it is univariate per series.

1. Input: grid series from `alert.windows.baseline` start to `alert.windows.incident` end, standardised `y = (x − med_B)/s_B` with §3.2's scale, so priors are unit-free.
2. Model: Gaussian with unknown mean and variance, Normal-Gamma prior `μ₀ = 0, κ₀ = 1, α₀ = 1, β₀ = 1`; predictive Student-t with `2α` degrees of freedom, location `μ`, scale² `β(κ + 1)/(ακ)`. Priors a priori.
3. Constant hazard `H = 1/λ`, `λ = 100` grid steps (a priori: RCAEval has one fault per case and ≈ 96–150 grid steps per case, [rcaeval_facts §Metric step and windows][rf-step]).
4. Run-length truncation at `R_max = 200`: mass for `r ≥ R_max` is folded into `R_max`.
5. `cp_t = Σ_{r ≤ m} P(r_t = r)`, `m = 2`.
6. `score = max_{t ∈ I} cp_t` ∈ [0, 1]; `threshold = 0.5`; `score_norm = log1p(score)`.
7. `onset_ns`: first grid `t ∈ I` with `cp_t ≥ 0.5`; onset = `t − r̂·g` with `r̂ = argmax_{r ≤ m} P(r_t = r)` (smallest `r` on ties). Direction = sign of mean `y` over `[onset, onset + p·g)`; `flat` without onset.

**Deterministic implementation.** All series that share a grid are stacked into one `(series × run length)` array and advanced with one sequential loop over time. Log-space throughout; normalise with max-shifted log-sum-exp; Student-t log-pdf via `scipy.special.gammaln`; no matrix products (so no multithreaded BLAS); no random numbers. Same inputs give bit-identical posteriors.

### 3.5 `silence` — dropping to zero or disappearing is an anomaly

A silent service must never look healthy ([02 §6.3](../02-architecture.md); [verified_agents §Q2][va]). Let `L = max(silence.min_gap_s, silence.min_steps · g)` (60 s, 3 steps).

- **Zero-silence** (signals in `silence.zero_signals`: `rps`, `workload`, `log_rate`, `cpu`, `mem`): baseline share of grid points equal to 0 ≤ 0.2, and a run of grid points in `I` with value exactly 0 lasting ≥ `L`.
- **Absence-silence** (any series): baseline grid coverage ≥ 0.8, and a run of grid buckets in `I` with no observation lasting ≥ `L`. Buckets after the last observation of the **same source anywhere in the case** do not count, so a truncated case is not "everything went silent".
- `score` = longest qualifying run / `L` (0 if none); `threshold = 1.0`; `onset_ns` = start of the first qualifying run; `direction = down`; `score_norm = log1p(score)`.
- `per_service.silent` = true if any of the service's `rps`, `workload` or `log_rate` series is silent, or at least `silence.service_metric_share` (0.5) of its metric series are silent.

### 3.6 Series onset of record and per-service onsets

1. For a series with `robust_z` above threshold: `τ = τ_z` (the `robust_z` onset); if the `bocpd` onset `τ_b` satisfies `τ_z − onset.bocpd_max_lead_s ≤ τ_b ≤ τ_z`, use `τ = τ_b` (BOCPD moves the onset back to where a ramp began). For a series with `silence` above threshold: its silence onset.
2. `external_onset_ns` = min `τ` over the service's series with (`klass = external` and `robust_z` above) or (`klass ∈ {external, context}` and `silence` above). A service that stops serving is externally visible.
3. `internal_onset_ns` = min `τ` over `klass = internal` series with `robust_z` or `silence` above.
4. `external_onset_source` / `internal_onset_source` = the `source` (`metrics | logs | traces`) of the series that gave that minimum (ties → smallest `series_id`); null when the onset is null (03 §4.2).
5. Onsets are in **source time**. Causync publishes clock offsets; consumers that compare onsets across sources add the `alignment` offset of the recorded `*_onset_source` (and service).

### 3.7 Incident onset `t_onset`

1. Collect non-null `external_onset_ns` over services; sort ascending.
2. `t_onset` = the second element if there are ≥ 2 (`method = second_external`); the only element if there is 1 (`single_external`); `alert.t_alert_ns` if none (`t_alert_fallback`) (03 §4.2).
3. Clamp to `[t_alert − 60 s, t_alert + 300 s]` ([02 §6.3](../02-architecture.md)).

Taking the second-earliest makes `t_onset` robust to one noisy early series. Example: `t_alert = 1000 s`; external onsets cart 1003, checkout 1010, frontend 1012 → `t_onset = 1010`, inside the clamp `[940, 1300]`.

### 3.8 `detect_alert(telemetry)` — entry-service SLO breach (detected-alert protocol)

Public, pure function in `veyltrace_anomara.alert`, called by core's alert step (pipeline step 1) before any signal exists:

```python
@dataclass(frozen=True)
class AlertDetection:
    t_alert_ns: int                    # start of the first sustained breach (before any shift)
    entry_services: tuple[str, ...]    # sorted A→Z
    signal: str                        # e.g. "latency_p99" (traces), "error_rate" (traces), or the metric name
    threshold: float                   # slo.k

def detect_alert(telemetry: TelemetryTables, manifest: CaseManifest,
                 config: AnomaraConfig) -> AlertDetection | None: ...
```

`TelemetryTables` is the set of `telemetry.*` tables loaded through `veyltrace_core.io`. The function reads no files itself, no clock, no RNG, and never touches `t_alert_hint_ns`.

1. **Entry services.** Build caller→callee pairs from `telemetry.spans` over the full span (parent and child in different services) and call the shared rule `veyltrace_causalith.entry.entry_services(call_pairs, services, system, cfg)` ([05-causalith §3.3](05-causalith.md)). No traces → the rule's system hint. Empty → return `None`.
2. **SLI series per entry service**, on `slo.bucket_s` (10 s) epoch-aligned buckets:
   - traces present: entry spans of the service (parent null, missing, or in another service; [02-signalyth §3.3](02-signalyth.md) definition, client-like spans excluded): `latency_p99` = 0.99 quantile of durations (ms, exact, linear), `error_rate` = share with `status = error`; buckets with fewer than `slo.min_spans` spans are skipped;
   - no traces: metrics of the service whose name matches `slo.latency_metric_pattern` (highest quantile in the name wins; unit converted to ms from `unit`) and `slo.error_metric_pattern`; names matching Signalyth's counter-name patterns are differenced into per-second rates first.
3. **Scan** each SLI from `data_start + slo.window_s + slo.gap_s`. At bucket `t` the trailing baseline is the buckets in `[t − slo.gap_s − slo.window_s, t − slo.gap_s)` (≥ `slo.min_baseline_points`); scale per §3.2; one-sided `z_t = (x_t − med)/s` (only increases breach).
4. A breach starts at `t` when `z ≥ slo.k` for `slo.persist_steps` consecutive buckets. Result = earliest breach start over all entry SLIs (ties: latency before errors, then service A→Z); `signal` names the SLI that breached.
5. **No breach** → `None`. Core then has no alert; 04's default counts the fault case as a miss and reports the count separately (`bench_result.run_outcome = no_alert`, 03 §13.2; [04-evaluation-protocol](../04-evaluation-protocol.md)).

Like an online watcher, each decision uses only the trailing baseline, the bucket itself and the next `slo.persist_steps − 1` buckets that confirm it, so the scan cannot look ahead to the injection. `detect_alert` depends only on telemetry and config, never on windows, so re-running it gives the same answer in every pipeline run of the case.

### 3.9 Optional TSFM plugin (`tsfm`, off by default, O-10)

Zero-shot time-series foundation models only tie classical detectors on TSB-AD-U (best zero-shot VUS-PR 0.319 vs 0.332–0.353), and none has been tested inside microservice RCA ([novel_building_blocks §Q1][nbb]). This plugin exists for that ablation; it is cut-list item 1 ([07 §1.1](../07-roadmap.md)).

- Models: Chronos-Bolt-tiny (9M parameters) or Toto 2.0 4M; both Apache-2.0 ([novel_building_blocks §Q1][nbb]). Never Moirai 2.0 or TimesFM 3.0 (non-commercial licences).
- `torch` and the model package are imported **inside** `veyltrace_anomara.tsfm.score()` only when `tsfm.enabled` is true; they are an optional extra (`tsfm`) of the package, not installed by `uv sync --all-packages`. CPU only, one thread, `torch.use_deterministic_algorithms(True)`, offline (weights read from a local path whose SHA-256 is pinned in config; no hub access).
- Context = baseline grid points (≤ `tsfm.max_context`), horizon = incident grid length. `score = max_t |x_t − q50_t| / max((q90_t − q10_t)/2.563, s_floor)` (2.563 = width of a Gaussian 10–90% interval in σ units; `s_floor` = §3.2 floor terms without MAD/IQR). Persistence, threshold 3.0, onset and direction as in §3.2. Detector name `tsfm`.

## 4. Configuration — `config/anomara.yaml`

| Key | Default | Unit | Rationale / source |
|---|---|---|---|
| `robust_z.mad_factor` | `1.4826` | — | normal consistency constant |
| `robust_z.iqr_divisor` | `1.349` | — | normal consistency constant |
| `robust_z.eta` | `0.02` | ratio | a priori, 2% of \|median\| |
| `robust_z.epsilon` | table §3.2 | per unit | a priori |
| `robust_z.persist_steps` | `3` | grid steps | a priori |
| `robust_z.threshold` | `3.0` | z | PRISM nominal threshold |
| `robust_z.min_baseline_steps` | `5` | grid steps | a priori |
| `nsigma.threshold` | `3.0` | σ | a priori (common 3σ rule) |
| `bocpd.lambda` | `100` | grid steps | a priori, one fault per case |
| `bocpd.prior` | `{mu0: 0, kappa0: 1, alpha0: 1, beta0: 1}` | — | a priori, standardised data |
| `bocpd.r_max` | `200` | steps | a priori; covers the longest case grid |
| `bocpd.short_run` | `2` | steps | a priori |
| `bocpd.threshold` | `0.5` | probability | a priori |
| `onset.bocpd_max_lead_s` | `120` | s | a priori |
| `silence.min_gap_s` | `60` | s | a priori |
| `silence.min_steps` | `3` | grid steps | a priori |
| `silence.zero_signals` | `[rps, workload, log_rate, cpu, mem]` | — | a priori |
| `silence.max_baseline_zero_share` | `0.2` | ratio | a priori |
| `silence.min_baseline_coverage` | `0.8` | ratio | a priori |
| `silence.service_metric_share` | `0.5` | ratio | a priori |
| `t_onset.clamp_s` | `[-60, 300]` | s | [02 §6.3](../02-architecture.md) |
| `slo.bucket_s` | `10` | s | a priori, same grid as Signalyth traces |
| `slo.min_spans` | `5` | spans | a priori, as `traces.min_spans_per_quantile` |
| `slo.window_s` | `300` | s | a priori trailing baseline |
| `slo.gap_s` | `30` | s | a priori |
| `slo.k` | `3.0` | z | a priori |
| `slo.persist_steps` | `3` | buckets | a priori |
| `slo.min_baseline_points` | `10` | buckets | a priori |
| `slo.latency_metric_pattern` | `latency\|duration\|response_time` | regex | same patterns as Signalyth rule 5 |
| `slo.error_metric_pattern` | `^error$\|error\|fail\|5xx` | regex | same patterns as Signalyth rule 6 |
| `tsfm.enabled` | `false` | — | [02 §6.3](../02-architecture.md) |
| `tsfm.model` | `chronos-bolt-tiny` | — | Apache-2.0, 9M ([novel_building_blocks §Q1][nbb]) |
| `tsfm.weights_path`, `tsfm.weights_sha256` | unset | — | pinned offline weights |
| `tsfm.max_context` | `512` | points | a priori |

## 5. Determinism and isolation

- Series processed in `series_id` order; grids epoch-aligned; argmax ties → earliest time.
- Medians and quantiles exact (numpy `method="linear"`); no RNG anywhere.
- BOCPD as in §3.4. The TSFM plugin is excluded from the default determinism gate and has its own two-run check when enabled.
- Allowed imports: `numpy`, `scipy`, `pyarrow`, `duckdb` (span grouping in `detect_alert`), stdlib; `veyltrace_causalith.entry` (pure function). `torch` and the model package only inside the lazily imported `tsfm` module (the single exception in [02 §9](../02-architecture.md)). Banned per AGENTS §4.3. No path under `bench/` or `lab/` is ever opened (02 §9 rule 3).

## 6. Missing data and failure behaviour

| Situation | Behaviour |
|---|---|
| Series with no baseline points or too few (§3.2 step 8) | rows written with `score = 0`, `flat`, no onset, `above_threshold = false` |
| Series with no incident points | `robust_z`/`nsigma`/`bocpd` score 0; `silence` evaluated (absence) |
| No external series at all (e.g. metrics-only system without latency) | `external_onset_ns` null for all; `t_onset = t_alert`, `method = t_alert_fallback` |
| No traces | `detect_alert` falls back to metric latency/error series of the entry services |
| No entry service or no entry SLI | `detect_alert` returns `None`; `onsets.entry_services` as found (may be empty) |
| `alert.json` windows clamped (`clamped = true`) | used as given; short baselines fall under §3.2 step 8 |
| Empty `signal_cube.series` | zero-row `anomalies`; `onsets` with `t_onset = t_alert` (`t_alert_fallback`), all per-service onsets and sources null, `silent = false` |
| NaN in a series | treated as missing |

## 7. Tests

**Unit**: scale floor picks each branch (MAD, IQR, ε, η); §3.2 micro-example exact; persistence rejects a single spike and sign flips; N-Sigma zero-scale convention; BOCPD posterior sums to 1 each step and finds a mean step at the right grid index; truncation keeps total mass; silence zero vs absence, truncated case not silent; onset of record (BOCPD inside / outside lead window); `t_onset` and `method` with 0, 1, 2, 3 onsets and both clamp edges; `*_onset_source` matches the winning series; `detect_alert` on hand-built spans (step at a known bucket, persistence, metrics fallback with unit conversion, counter differencing, `None` when flat); `entry_services` and `slo_breach_ns` taken from `alert.json` when `alert.detector` is set.

**Golden (synth-01…05)** against reviewed fixtures, plus checks that need no answer key:
- synth-01: exactly one service has an internal `cpu` series above threshold; its internal onset ≤ its external onset.
- synth-02: external series above threshold, no internal `cpu`/`mem` above threshold on the slowed service.
- synth-03: an `error_rate` or `error` series above threshold with direction `up`.
- synth-04: the regressed service has an onset after the change time present in `telemetry.events`.
- synth-05: no entry-service external series above threshold; `detect_alert` returns `None`.
- synth-01…04: `detect_alert` returns a breach; its time is recorded in the fixture (its distance to the injection is a bench metric).

**Onset accuracy** (FR-8, "≤ 1 time step"): needs the synthetic answer key, so it runs in bench as a per-case metric, not in package tests (AGENTS §4.5).

**Property (hypothesis)**: `score ≥ 0`; `above_threshold ⇔ score ≥ threshold`; with ε and η set to 0, `robust_z` scores are invariant to `x → a·x + b` (`a > 0`); shuffled rows → identical output; `t_onset` always inside the clamp; a series that drops to zero for ≥ `L` with a non-zero baseline yields `silence` above threshold (FR-7).

**Real-case smoke**: one RE2 case per system and one RE3 case: schema-valid, row count = series × detectors, two runs identical, time within §8.

## 8. Performance budget

Per RE2 case: ≤ 4 s and ≤ 0.5 GB (*estimate*, allocation of the 30 s / 3 GB budget). Robust statistics over ~500 series × 1,200 points took about 9 ms in a NumPy benchmark ([rcaeval_facts §Engineering][rf-eng]). BOCPD on grids of ≈ 96–150 steps with up to a few thousand series stays within budget (*estimate*). TSFM is outside the budget (ablation only).

## 9. Evaluation hooks and ablations

| Arm | Bench measures |
|---|---|
| detector set: `robust_z` alone, `+bocpd` onset, `nsigma` alone, `+tsfm` | AC@k via Causatrix; onset error on synth and lab |
| scale-floor terms switched off one at a time | accuracy change (no published ablation exists, [rcaeval_facts §Anomaly scoring methods][rf-methods]) |
| `robust_z.persist_steps` ∈ {1, 3} | spike robustness |
| detected vs oracle protocol | `detect_alert` time minus injection time (bench, needs the answer key), no-alert count |
| no-fault behaviour | above-threshold rate on synth-05, RCAEval pre-injection windows, lab no-fault captures |

## 10. Tasks and milestones

| ID | When | Scope | Acceptance (summary) |
|---|---|---|---|
| O-00 | by M0, Tue 3 Nov | stub, synth fixtures | e2e on `synth-01` |
| O-04 | Phase 2, by M2 Sun 15 Nov | robust z + floor, N-Sigma, BOCPD onset, silence, `t_onset`, `detect_alert`; implement `veyltrace_causalith.entry` first. Core's alert step can use a stub `detect_alert` (returns `None`) until then | golden; onset error on synth ≤ 1 step (bench) |
| O-10 | Phase 3, by M3 Sun 22 Nov — *cut first* | TSFM plugin | ablation arm runs on RE2-OB |
| O-11 | Phase 3 | performance pass | ≤ 30 s and ≤ 3 GB per RE2 case (deterministic path), measured on the slowest laptop |
| O-12 | Phase 4 | docs, fixtures | reviewed by lead |

## 11. Open questions

| # | Question | Default if unresolved |
|---|---|---|
| 1 | *Resolved in 03 §4.2 (2026-10-30):* `onsets.method` vocabulary is `second_external \| single_external \| t_alert_fallback` (§3.7). | — |
| 2 | *Resolved in 03 §4.2 (2026-10-30):* `per_service[].external_onset_source?` and `internal_onset_source?` added, so consumers apply `alignment` offsets per source (§3.6). | — |
| 3 | The entry rule is shared with Causalith through `veyltrace_causalith.entry` (intra-lane import); core also reaches it through `detect_alert`. Lead may prefer `veyltrace_core`. | keep in Causalith |
| 4 | Detected protocol with no breach: `detect_alert` returns `None`; 04 counts the case as a miss. *Resolved in 03 §13.2 (2026-10-30):* `bench_result.run_outcome = no_alert`. | as 04 states |
| 5 | `torch` in the TSFM module needs an isolation-test exemption (lead-owned `tests/test_isolation.py`). *Rule resolved in 02 §9 (2026-10-30)*; the test change is the lead's. | exemption for `veyltrace_anomara/tsfm/` only |
| 6 | *02 §3 resolved (2026-10-30):* it now lists `alert` and `detect_alert()` reading telemetry. 03's catalog still does not list Anomara (`detect_alert`) as a `telemetry.*` consumer. | as specified; lead updates the 03 catalog |
| 7 | `detect_alert` is a cross-lane API (core calls it). Freeze its signature with contracts at M1? | yes; changes need lead approval |

## 12. References

- Master and contracts: [02 §5.1, §6.3, §9](../02-architecture.md); [03 §4](../03-contracts.md); [07](../07-roadmap.md)
- Scale floor, log compression, BARO/PRISM scorers: [rcaeval_facts §Anomaly scoring methods][rf-methods]
- Onset, persistence, internal-before-external rates: [rcaeval_facts §Onset and precedence][rf-onset]; BOCPD: [§Anomaly scoring methods][rf-methods]
- Statistics cost on CPU: [rcaeval_facts §Engineering][rf-eng]
- TSFM evidence and licences: [novel_building_blocks §Q1][nbb]
- Silence-as-health failure: [verified_agents §Q2][va]
- Onset-shift sensitivity: [benchmarks_and_testbed §Q2][bt]
- Adams & MacKay, "Bayesian Online Changepoint Detection", arXiv 0710.3742 · BARO, FSE 2024 (arXiv 2405.09330)

[rf-scoring]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#ground-truth-and-scoring
[rf-step]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#metric-step-and-windows
[rf-methods]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#anomaly-scoring-methods
[rf-onset]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#onset-and-precedence
[rf-eng]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#engineering-duckdb-and-drain3
[nbb]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/novel_building_blocks.md
[va]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/verified_agents_local_llms.md
[bt]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md
