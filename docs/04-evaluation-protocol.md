# 04 · Evaluation protocol (pre-registered)

> **Status:** v0.1-draft (frozen at tag `prereg-v1`, §1) · **Owner:** lead (Reason lane); `bench/decoys/` and `bench/stats/` are implemented by the Observe lane (O-13, O-14) · **Last updated:** 2026-10-30
> Master spec: [02-architecture](02-architecture.md) (wins on architecture; this file wins on protocol details, as [11](11-research-paper-plan.md) states). Targets: [01 §9](01-vision-and-requirements.md). Engine specs: [06 FaultLoom](engines/06-faultloom.md), [07 Causatrix](engines/07-causatrix.md), [09 Causentra](engines/09-causentra.md). Tasks: [07-roadmap](07-roadmap.md). Every reported number must come from the procedure below or be listed as a deviation (§12).

## 1. Scope and pre-registration

This document fixes, before any Veyltrace arm is run on a test split: research questions and hypotheses, datasets, splits, methods, metrics, statistical tests and reporting rules.

- **Freeze.** This file, the Reason engine configs (`config/{core,faultloom,causatrix,causentra}.yaml`) and every YAML in `bench/experiments/` marked `prereg: true` are frozen at the git tag `prereg-v1`, pushed before the first test-split run of any Veyltrace arm: target M1 (Sun 8 Nov), at the latest before R-11's full RE2 run. The GitHub tag and push time are the evidence, as in the pre-registered RCAEval study that tagged a commit before seeing any fault window [benchmarks_and_testbed §Q2][bt].
- **What may run before the tag.** Baseline reproduction on RE2 (R-05; it measures other methods), all work on synth and RE1, and three **development cases** (one per RE2 system) listed in `bench/dev_cases.yaml`. Development cases are excluded from every test table and reported separately.
- **After the tag.** Any change to a frozen file is a deviation: a row in §12 (date, change, reason, whether test results had been seen) and an ADR. If a change is motivated by test results (e.g. after the M2 scorecard), the paper reports both the pre-registered and the revised numbers.
- **Out of scope here.** Lab construction and dataset release ([05](05-fault-lab-and-dataset.md)); the paper's narrative and the long-form threats ([11](11-research-paper-plan.md)).

## 2. Research questions and pre-registered hypotheses

Targets are the v1.0 success criteria of [01 §9](01-vision-and-requirements.md) (SC-n); hypothesis labels (Hn) match [11](11-research-paper-plan.md). No effect sizes are predicted beyond these targets; §8 says which differences this design can detect.

| RQ | Question | Hypotheses and targets | Confirmatory analysis |
|---|---|---|---|
| **RQ1 Accuracy** | How accurate is the AI-off pipeline per system against honest floors and reproduced baselines, and where does it fail: retrieval or re-ranking? | **H1a / SC-3(a)** on no RE2 system is `veyltrace:off` significantly worse in AC@1 than the best reproduced simple baseline. **H1b / SC-3(b)** pooled over RE2, the paired AC@1 difference vs the best reproduced baseline is positive. **SC-3(c)** (stretch) significant per-system gain on ≥ 2 of 3 systems. **H1c / SC-3(d)** Retrieval@5 ≥ 0.90 per RE2 system | (a) per system: 95% cluster-bootstrap CI of the paired difference not entirely below 0; (b) pooled: CI excludes 0 and the cluster permutation test is significant after Holm; (c) per-system permutation tests in the same Holm family `rq1` (pooled + 3 systems). "Best reproduced simple baseline" = the highest AC@1 among `rcaeval:nsigma`, `rcaeval:baro`, `simplerca` on the same evaluation cases (per system for (a), pooled for (b)); choosing it on the test set favours the baseline |
| **RQ2 Proposer lift** | Does a ≤ 10B local LLM, restricted to proposing code-verified predicates and candidates, change verified accuracy, and can decoys steer it? Arms: AI off; `brief` + verifier; `investigate` + verifier; agent-only (brief proposals, no verifier) | **H2a / SC-5** the CI of proposer lift (AC@1 `brief` − AC@1 off, 3 seeds) is not entirely below 0 (no positive target: we found no published result for a ≤ 10B model as the investigating RCA agent; ThinkFL's model size is unconfirmed). **H2b** planted decoy proposals change the top-1 in ≤ 5% of cases. **H2c** the verdict is identical under every permutation of the proposals (100%). Exploratory: `investigate` vs `brief`, verifier vs agent-only, 9B vs 4B | lift per RE2 system and pooled with cluster-bootstrap CIs (family `rq2`, Holm over 3 systems + pooled); H2b and H2c as proportions with exact binomial CIs |
| **RQ3 Calibration** | Do conformal sets reach nominal coverage within a benchmark family, how large are they, does coverage hold across systems, and is abstention informative? | **H3a / SC-4, R-12** held-out coverage ≥ 0.85 per calibration family at α = 0.10 (R-12 acceptance: within 1 − α ± 0.05 on RE2). **H3b** mean set size ≤ 3. **H3c** AURC of the verified score V is lower than that of the fused score F. **H3d** (expected negative) leave-one-system-out coverage falls below nominal; the gap is reported. **SC-4 / R-12** `NO_FAULT` on ≥ 85% of held-out normal windows (false alarms ≤ β + 0.05); wrong `NO_FAULT` on ≤ 5% of fault cases | estimation with cluster-bootstrap CIs; no significance test |
| **RQ4 Robustness** | How do results change under alert-time shifts, missing telemetry, leave-one-system-out calibration, decoy changes (RCAEval-C) and, for LLM arms, anonymised names? | **H4a / SC-7** AC@1 drops ≤ 10 points per RE2 system under ±60 and ±120 s shifts (±30 s exploratory). **H4b / SC-7** in every telemetry-ablation cell ≥ 90% of `CONFIRMED` verdicts are correct. **H4c / SC-7** decoy changes alone (no true change) cost ≤ 5 AC@1 points vs no change events; a true change raises AC@1. **H4d** anonymisation changes LLM-arm accuracy (direction not predicted) | estimation with CIs per cell |
| **RQ5 Cost** | What do the deterministic and AI paths cost on CPU laptops? | **H5 / SC-1, SC-8** deterministic p95 ≤ 30 s and ≤ 3 GB peak RSS per RE2 case on the slowest laptop; the AI path adds ≤ 180 s (Relentra `brief`) plus ≤ 60 s (Causivra narration) p95 ([02 §9](02-architecture.md)) | descriptive (p50, p95) |
| **RQ6 Replay** | Do verdicts replay exactly, and how often does regenerating the LLM output reproduce it? | **H6a / SC-6** Tier 1 replay reproduces `verdict_hash` on 100% of recorded cases on a second laptop and in CI. **H6b** Tier 2 regeneration match rate reported, no target | proportions with exact binomial CIs |

Everything not listed as confirmatory is exploratory and labelled as such.

## 3. Datasets

| Tier | Dataset | Size | Telemetry | Labels | Role | Status |
|---|---|---|---|---|---|---|
| Tuning | RCAEval **RE1** (OB, SS, TT) | 375 cases (125 per system; 5 faults × 5 services × 5 repetitions) | metrics only | service, fault (folder name) | the only real data on which a value may be tuned | verified [rcaeval_facts, "Datasets and telemetry per system"][rc]; 50 RE1-OB cases have a duplicate `time` header and RE1 has no disk metric, checked before use; 2 broken RE1-OB cases excluded (125 → 123) [rcaeval_facts, "Data quirks"][rc] |
| Anchor | RCAEval **RE2** (OB, SS, TT) | 270 (90 per system; cpu, mem, disk, socket, delay, loss × 5 services × 3 repetitions) | metrics + logs; traces for OB and TT only; one RE2-TT case has no logs | service, fault | RQ1–RQ6 headline | verified [rcaeval_facts, "Datasets and telemetry per system"][rc] |
| Anchor | RCAEval **RE3** | 90 (30 per system; code faults F1–F5; not a uniform grid; F5 only in OB) | metrics + logs; traces OB/TT | service, fault | RQ1, RQ4 (code faults) | verified; one RE3-TT label was relabelled `f6` → `f3` [rcaeval_facts, "Data quirks"][rc] |
| Derived | **RCAEval-C** (RE2 + synthetic change events) | 270 × grid (§5.2) | RE2 + `telemetry.events` | RE2 labels + `answer_key.decoy_changes_json` | RQ4 change channel | generator in `bench/decoys/` (O-13, Observe lane) |
| Derived | **RCAEval normal windows** (pre-injection segments) | ≤ 1 per RE2/RE3 case | as the case | no fault | `NO_FAULT` calibration and held-out false-alarm rate | §5.4; short clamped baselines (§11) |
| Cross-check | **Nezha** | 101 (Online Boutique 56, Train Ticket 45) | metrics, logs, traces | service; inner-service indicator | RQ1 cross-source; RQ4 transfer | in GitHub repo, MIT [benchmarks_and_testbed §Q1][bt]; adapter O-08 |
| Hard (if feasible) | **FSE'26 propagation-aware Train Ticket** | 1,430 validated cases from 9,152 injections; 25 fault types in 6 categories; ~50 services | metrics, logs, traces | service down to function | RQ1 "beyond easy benchmarks"; 11 re-evaluated methods averaged 0.21 Top@1, best 0.37 | Zenodo 10.5281/zenodo.17105974; **size, file format and data licence unverified** [benchmarks_and_testbed §Q1][bt]; go/no-go at R-07 (M1); default "stretch" ([02 §12](02-architecture.md)) |
| Lab | **VeylLab** (Online Boutique v0.10.7 on kind; OTel Demo 3.1.0 on Compose) | target ≥ 120 validated cases by M4 (X-11); grid and controls in [05](05-fault-lab-and-dataset.md) | metrics, logs, traces, **real** deploy/config/flag events | answer key with injector, parameters, ns timestamps; ≈ 10% no-fault and ≈ 10% noisy controls | RQ1 (change-aware), RQ3 (`NO_FAULT`), RQ4 | about 57 cases per laptop-day is a computation from a 25-minute protocol; laptop acceptance rate unknown [benchmarks_and_testbed §Q5][bt] |
| Optional | **Cloud-OpsBench** | 754 cases, 57 fault types (OB 11 services, TT 41) | pre-executed tool responses (3.46 / 8.75 MiB snapshots), not raw telemetry | joint RCA labels | RQ2 agent-only arm only; the deterministic pipeline cannot run on it | CC BY 4.0 [benchmarks_and_testbed §Q1][bt]; feasibility unverified |
| Smoke | **synth-01 … synth-05** (6-service toy: CPU hog, network delay, error injection, change-induced regression, no fault) | 5 | all four sources | exact | CI, golden fixtures, harness tests; synth-05 also contributes a normal window to `NO_FAULT` calibration (02 §6.9) | never reported as results |

Ground truth for RCAEval is the folder name `{service}_{fault}` (and `cases.parquet` on Hugging Face); bench derives `answer_key` from it and engines see only the opaque `case_id` ([02 §2 P7](02-architecture.md); [rcaeval_facts, "Ground truth and scoring"][rc]). The Hugging Face Parquet copy (3.44 GB) is used, not the 38 GB Zenodo extraction [rcaeval_facts, "Downloads and licence"][rc]. RCAEval injects faults into only five services per system, so a ranker that reads no telemetry reaches Avg@5 0.488 on held-out incidents (Buljić, arXiv preprint; [rcaeval_facts, "Published baseline numbers"][rc]); this is why AC@1, Lift and the prior-only floor are always reported.

## 4. Methods and baselines

All methods run in **one harness** (`veyltrace bench run`), on the same cases, inputs and alert times, in one pinned environment (Python 3.12; `uv.lock` hash recorded). Published numbers are never mixed into our tables: BARO's AC@1 on RE2-TT is 0.67 in RCAEval's harness and 0.32 in PRISM's [rcaeval_facts, "Published baseline numbers"][rc], and CIRCA is reported at 0.32 AC@1 on RE2-TT in RCAEval's paper, 0.67 in GALA+'s harness (probably RE2-OB) and 17.8% PR@1 on RCAtlas [sota_methods §Q1][sm].

| Method id | What | Code |
|---|---|---|
| `chance` | analytic: AC@k = min(k, n)/n, n = candidate services in the case | bench |
| `prior-only` | ranks services by how often they are the root in the calibration fold; reads no telemetry | bench |
| `rcaeval:nsigma`, `rcaeval:baro`, `rcaeval:mmbaro` | N-Sigma, BARO, multi-source BARO | RCAEval's own code in an isolated venv (below) |
| `rcaeval:circa`, `rcaeval:tracerca`, `rcaeval:microrank`, `rcaeval:pc_pagerank`, `rcaeval:causalrca` | other RCAEval methods "where runnable" under Python 3.12 within `resources.timeout_s` (timeouts are misses) | same; TraceRCA may need a wrapper because it is not wired into `main.py` (source in team's local archive; verify at R-05) |
| `rcaeval:rcd`, `rcaeval:torai` | need a separate Python 3.8 environment [sota_methods §Q5][sm] | run only if someone owns that environment; otherwise "not run" |
| `simplerca` | Fang et al.'s alert count: metric alerts at 3-sigma or above the history P95, trace alerts at P95 latency ≈ 3× baseline, log alerts on ERROR/FAIL/EXCEPTION counts; rank by alert count ([arXiv 2510.04711](https://arxiv.org/abs/2510.04711); [rcaeval_facts, "Published baseline numbers"][rc]) | bench re-implementation |
| `prism-plain` | PRISM from the paper: z-score per property on the pre-alert window, max pooling, internal = cpu/mem/disk/socket, external = latency/error, M = I + E − ln(1 + I + E); metrics only ([arXiv 2601.21359](https://arxiv.org/html/2601.21359); [rcaeval_facts, "Anomaly scoring methods"][rc]) | bench re-implementation (no released code); labelled as such |
| `causatrix:<ranker>` × 6, `causatrix:rrf` | each ranker alone; the fused slate without verifier | [07 §9](engines/07-causatrix.md) |
| `veyltrace:off` | full pipeline, `ai.mode = off` | |
| `veyltrace:brief` | `ai.mode = record`, Relentra `brief`, verifier on | |
| `veyltrace:investigate` | Relentra `investigate`, verifier on (cut item 3 in [07 §1.1](07-roadmap.md)) | |
| `agent-only:brief` | same model and evidence cards; the model's hypotheses in order are the ranking, then the remaining slate order; no verifier | bench reads `proposals.json` |
| `naive-change` | RCAEval-C only: blame the service with the latest change before `t_alert` | bench |

**RCAEval environment.** A separate venv `bench/.venv-rcaeval/` (Python 3.12, one of the versions `main.py` accepts [rcaeval_facts, "Downloads and licence"][rc]) at a commit pinned at M1 (v1.8.1 was current on 2026-10-20; source in team's local archive, verify at M1), invoked as a subprocess and never imported into the workspace. Its `output/` directory is deleted before each run because `main.py` scores every stale result file it finds (source in team's local archive; verify at R-05). RCAEval's `--report-chance` and `--report-decomposition` outputs are stored next to ours. Baselines receive the same `t_alert` as Veyltrace (from the run's `alert.json`, passed as RCAEval's `inject_time`). R-05 acceptance: BARO and N-Sigma within ±5 points of the published RCAEval numbers, or the discrepancy written up (SC-2).

## 5. Protocols, splits and calibration

### 5.1 Alert protocols ([02 §5.1](02-architecture.md))

Core's alert step writes `alert.json` ([03 §2.6](03-contracts.md)) before Signalyth runs.

| Protocol | `t_alert` | Notes |
|---|---|---|
| Oracle | `case_manifest.t_alert_hint_ns` = the dataset's published injection time | RCAEval-comparable; default for every table unless stated |
| Detected | Anomara's `detect_alert(telemetry)`: first sustained SLO breach on the entry service(s) | realistic; reported next to oracle (M2 exit criterion); a fault case with no detected breach is counted as a miss and reported as a separate count (`run_outcome = no_alert` in `per_case.csv`, [03 §13.2](03-contracts.md)) |
| Live | the watcher's trigger or the "Diagnose now" click | demo only; not used for tables |

### 5.2 Perturbation protocols (RQ4)

| Protocol | Hook | Grid (a priori) |
|---|---|---|
| Onset shift | `alert.shift_s` (O-09) | −120, −60, −30, +30, +60, +120 s added to the oracle `t_alert`; a 2-minute shift took N-Sigma from 0.80 to 0.07 AC@1 on RE2 in one preprint [benchmarks_and_testbed §Q2][bt] |
| Telemetry ablation | `sources.drop` (O-09) | drop metrics; drop logs; drop traces; drop events; metrics only. RE2-SS/RE3-SS have no traces, a natural experiment [rcaeval_facts, "Datasets and telemetry per system"][rc] |
| Leave-one-system-out | calibration family `<family>.loso-<system>` | calibrate on two systems, test on the third; also RE2 (OB + TT) → Nezha (OB + TT) |
| RCAEval-C decoys | `protocol.decoys`, generator in `bench/decoys/` (O-13) | true change on the root at `t_inject − U(0, 120 s)` with probability π ∈ {0, 0.5, 1.0}; Poisson decoy changes on non-root services at rate λ ∈ {0, 2, 6} per hour within [`t_inject` − 30 min, `t_inject` + 5 min]; kinds drawn from {deploy, config, flag}; seed `rng(case_id, "rcaeval-c")` [novel_building_blocks §Q5][nbb] |
| Name anonymisation (AI arms, optional) | `protocol.anonymize_services` | names → `S01…`; a prior LLM pipeline lost 0.20–0.21 on RE3 under anonymisation [benchmarks_and_testbed §Q2][bt] |
| Planted decoy proposal (RQ2) | `protocol.inject_proposals` | one fabricated proposal per case for a healthy service with false claims |
| Proposal permutation (RQ2) | `protocol.permute_proposals` | the recorded proposals re-ordered with a seeded permutation; Causentra re-run from the cassette |

True and decoy changes are written with identical schema (`source_system = synthetic` for all), so the channel cannot tell them apart by format; Causync treats them like real changes (O-13 acceptance).

### 5.3 Tuning

Every threshold and weight in the Reason configs is set a priori with a cited source ([06](engines/06-faultloom.md), [07](engines/07-causatrix.md), [09](engines/09-causentra.md) §4). If a value must be tuned, it is tuned only on RE1 or synth, the choice is committed before `prereg-v1`, and RE1 results are never reported as test results. No parameter is selected on RE2, RE3, Nezha, FSE'26 or VeylLab. Sensitivity sweeps (trial factors, status margins) are reported as curves, never used to pick a value.

### 5.4 Calibration splits (conformal q̂ and `NO_FAULT` τ_nf)

Calibration is fitted by bench (R-13) and written to `config/calibration/<family>.json`; core's config loader passes it to Causentra, and engines never read `bench/` ([02 §6.9, §9](02-architecture.md)). Coverage and false-alarm rates are measured only on held-out cases.

1. **Clusters** = (system, root service, fault). Repetitions of a cluster are not independent (shared deployments and DB state in RCAEval [rcaeval_facts, "Data quirks"][rc]) and never straddle splits. A normal window derived from a fault case belongs to that case's cluster.
2. **Strata** = (system, fault class); no-fault cases form one stratum per system. Within each stratum, clusters are shuffled with a seeded RNG (`split.seed`, default 20261108) and assigned alternately to fold A and fold B; the starting fold alternates between strata (sorted by name), so odd-sized strata do not all favour fold A.
3. **Cross-fitting.** Calibrate on A, test on B; calibrate on B, test on A. Every test prediction uses a calibration that shares no cluster with it, and every case gets exactly one test prediction. Files: `config/calibration/<family>.foldA.json`, `.foldB.json` (the fold is part of the family id).
4. **Per AI arm and alert protocol.** `V` differs between arms, so `off`, `brief` and `investigate` each get their own files; a file applies only to runs with the same arm and alert protocol (`ai_arm`, `alert_protocol` in [03 §12.1](03-contracts.md)), so detected-alert runs get their own files too. Perturbed runs (onset shift, telemetry ablation, decoys) reuse the files of their unperturbed protocol, so coverage drift under perturbation is visible.
5. **q̂.** Calibration score = nonconformity of the true root; +∞ if the root is outside the decision pool. q̂ = the ⌈(n + 1)(1 − α)⌉-th smallest score, +∞ if that index exceeds n; α = 0.10 ([09 §3.7](engines/09-causentra.md)). RE2: 90 clusters → about 135 cases per fold → rank index ⌈136 × 0.9⌉ = 123.
6. **τ_nf.** Statistic `M` of [09 §3.8](engines/09-causentra.md) on the **normal windows** of the calibration fold; τ_nf = the ⌈(m + 1)(1 − β)⌉-th smallest, β = 0.10; fewer than 9 normal windows → default τ_nf = log1p(3.0) and `calibrated = false`. Normal windows ([02 §6.9](02-architecture.md)):
   - `synth-05` (calibration only, never reported);
   - VeylLab no-fault captures;
   - **RCAEval pre-injection segments**: oracle protocol with `alert.shift_s = −510`, so `t_alert = t_inject − 510 s` and the incident window [`t_alert` − 2 min, `t_alert` + 8 min] ends 30 s before injection; the baseline is clamped to the data start (RE2 has ~12 min before injection [rcaeval_facts, "Metric step and windows"][rc], so about 1.5 min of baseline remains; segments with < 60 s of baseline are dropped). The segment may contain the tail of the previous case's fault, because RCAEval's next case started about 1.5 min after the previous fault with no baseline check (stated for RE2-TT, [rcaeval_facts, "Metric step and windows"][rc]); this biases τ_nf upward (more `NO_FAULT` on faults) and is reported.
   Normal windows are split with the same clusters and folds, so the held-out false-alarm rate (R-12) uses windows whose calibration fold excluded them.
7. **Variants** (RQ3/RQ4): per-system Mondrian files `<family>-<system>.foldA`; LOSO files `<family>.loso-<system>`.

## 6. Experiment matrix

Cell = milestone at which the cell is first filled ([07](07-roadmap.md)); "—" = not planned; "opt" = only if time allows. R-16 fills or marks every cell "not run" with a reason.

| Dataset × protocol | Baselines (§4) | Causatrix rankers alone + `rrf` | `veyltrace:off` | `veyltrace:brief` | `veyltrace:investigate` | `agent-only:brief` |
|---|---|---|---|---|---|---|
| synth × oracle (smoke) | M0 (R-04) | M2 | M2 | M3 | M3 | M3 |
| RE1 × oracle (tuning only) | M1 (R-05) | M2 | M2 | — | — | — |
| RE2 × oracle | M1 (R-05) | M2 (R-09, R-11) | M2 (R-11) | M3 (X-08) | M4 (subset of 90) | M3 |
| RE2 × detected | M2 (R-11) | M2 | M2 | M4 | — | M4 |
| RE2 × onset shift | M4 | M4 | M4 | M4 (subset) | — | — |
| RE2 × telemetry ablation | M4 (methods that accept the input) | M4 | M4 | — | — | — |
| RE2 × calibration (cross-fit) and normal windows | — | — | M3 (R-13, R-12) | M3 | M4 | — |
| RE2 × LOSO calibration | — | — | M4 | M4 | — | — |
| RCAEval-C × decoy grid | M3 (`naive-change`) | M3 | M3 (O-13) | M4 | — | M4 |
| RE2 × planted decoy proposals / permutation | — | — | — | M4 | opt | M4 |
| RE3 × oracle | M2 | M2 | M2 | M4 | — | M4 |
| Nezha × oracle | M3 (O-08) | M3 | M3 | M4 | — | — |
| RE2 → Nezha transfer | — | — | M4 | — | — | — |
| FSE'26 TT × oracle (if feasible) | M4 | M4 | M4 | — | — | — |
| VeylLab × oracle (incl. no-fault) | M4 | M4 | M4 | M4 | opt | M4 |
| Cloud-OpsBench (optional) | — | — | — | — | — | opt |

Cross-cutting: RQ5 cost is recorded on every run. RQ6 Tier 1 replay on 100% of recorded AI runs at M3 (exit criterion), then on a second laptop and in CI at M4; Tier 2 regeneration on 50 recorded cases at M4. Statistics (bootstrap, permutation, McNemar, Holm) come from `bench/stats/` (O-14) for every cell.

LLM budget (*estimate*): 270 RE2 cases × 3 seeds × ~1.5 min per `brief` call ≈ 20 laptop-hours [report][report]; `investigate` runs on 90 cases (one repetition per cluster, chosen by seed) × 3 seeds.

## 7. Metrics

Notation: *F* = fault cases of the evaluated split, *N* = normal windows; for case *i*: truth `r_i`; ranking `R_i` = services from `verdict.ranks_rcaeval` (or the baseline's `ranks`) after RCAEval's coarse transform `x.split("_")[0].replace("-db", "")`, de-duplicated in order [rcaeval_facts, "Ground truth and scoring"][rc]; `n_i` = candidate services; `C_i` = conformal set.

| Metric | Definition | Notes / `per_case.csv` column |
|---|---|---|
| AC@k (k = 1, 3, 5) | (1/\|F\|) Σ 1[r_i ∈ R_i[:k]] | headline AC@1 per (dataset, system); `hit_at_1/3/5` |
| Avg@5 | mean of AC@1…AC@5 | RCAEval definition |
| MRR | mean of 1/position of `r_i` in `R_i` (0 if absent) | from `ranks` |
| Fine-grained AC@k | (service, indicator) match; answers cpu→cpu, mem→mem, delay→latency, loss→latency, disk→diskio (RE2/RE3) or latency (RE1), socket→socket | RCAEval convention [rcaeval_facts, "Ground truth and scoring"][rc]; RE3 F1–F5 not scored at this level |
| Fault-type accuracy | `root.fault_class` vs mapped answer (socket → `socket`, [03 §1](03-contracts.md)); RE3: `mode = code` | `fault_class_hit` |
| Retrieval@K | (1/\|F\|) Σ 1[r_i ∈ slate top-K] | `retrieval_hit`; also decision-pool retrieval (`pool_hit`) |
| Rerank@1 | AC@1 / Retrieval@K | AC@1 = Retrieval@K × Rerank@1 (DecompRCA; RCAEval `--report-decomposition`) [sota_methods §Q1][sm] |
| Chance@k, Lift@k | Chance@k = mean_i min(k, n_i)/n_i; Lift@k = AC@k / Chance@k; also AC@k − Chance@k | RCAEval's `--report-chance` output stored alongside (§13 Q4) |
| Prior-only floor | AC@k of `prior-only` | |
| Onset error | \|`onsets.t_onset_ns` − `answer_key.t_inject_ns`\| / 1e6 | `onset_error_ms`; detected protocol |
| Coverage | (1/\|F\|) Σ 1[r_i ∈ C_i] on held-out folds; gap = coverage − (1 − α); coverage given decision-pool retrieval | `in_set`; per system, per fold, pooled over folds |
| Set size | mean and median \|C_i\|; share of singleton sets | `set_size` |
| Risk–coverage, AURC | order cases by (status CONFIRMED > LIKELY > INCONCLUSIVE, then margin desc); for each prefix: answered fraction vs error (1 − AC@1) among answered; AURC = area under that curve; computed for V (verdict) and for F (fused score) | H3c [verified_agents §Q6][va] |
| Selective accuracy | AC@1 among CONFIRMED; among CONFIRMED ∪ LIKELY; with answer rates | `status` |
| `NO_FAULT` rates | false-alarm rate = share of held-out normal windows *not* declared `NO_FAULT`; wrong-`NO_FAULT` rate = share of fault cases declared `NO_FAULT`; precision and recall on mixed sets | VeylLab, RCAEval normal windows (synth-05 excluded from reporting) |
| Proposer lift | AC@1(arm) − AC@1(off), paired | `ai_mode`, `seed` |
| Proposal outcomes | admitted, accepted, rejection reasons, decision-pool retrieval gain | from `verdict.json` |
| Decoy metrics | proposal decoys: share of cases where the top-1 changed (H2b); RCAEval-C: share of cases where a decoy-changed service is ranked first | `decoy_present`, `decoy_ranked_first` |
| Permutation invariance | share of cases with identical `verdict_hash` across proposal permutations | `verdict_hash` |
| Claim-grounding rate (narration) | share of card summary sentences with ≥ 1 citation resolving to an evidence atom; numeric fidelity (100% by construction, measured); checker rejection and template-fallback rates | Causivra; code-computed, no judge [verified_agents §Q8][va] |
| Cost | wall time per case and per stage (p50, p95); peak RSS (MB); tokens in/out; CPU model, cores, RAM, OS | `wall_ms`, `peak_rss_mb`, `tokens_in`, `tokens_out` |
| Replay | Tier 1 = share of recorded runs where `veyltrace replay` exits 0 (same laptop, other laptop, CI) plus exit-code histogram; Tier 2 = share of cases whose regenerated proposals (`llama-server -np 1`, `cache_prompt: false`, fixed seed, pinned GGUF) are byte-identical | [verified_agents §Q3][va] |

**Failed runs** (crash, timeout, missing output) count as misses in every accuracy metric and are reported as a count; denominators are always the full split [benchmarks_and_testbed §Q2][bt].

**AC@k ignores status.** It is computed on `ranks_rcaeval`, which Causentra fills for every status, so abstention cannot raise accuracy; abstention quality is measured separately (coverage, risk–coverage, `NO_FAULT` rates).

**ECE is not used.** Veyltrace outputs a set and a status, not a probability; ECE needs a predicted probability per case. Coverage, set size and risk–coverage measure what the system claims. Practitioners also found numeric confidences hard to interpret [verified_agents §Q6][va].

## 8. Statistics

Implemented in `bench/stats/` (O-14, Observe lane), validated on a toy example with a known answer.

- **Unit and clusters.** Case-level paired outcomes; clusters = (system, root service, fault): 90 on RE2, about 30 on RE3 [benchmarks_and_testbed §Q2][bt].
- **Confidence intervals.** 95% percentile cluster bootstrap, 2,000 resamples, seeded, for every metric and every paired difference.
- **Primary test.** Two-sided cluster sign-flip permutation test on the paired AC@1 difference: per cluster *c*, `d_c` = mean over its cases of (hit_A − hit_B); statistic = mean of `d_c`; 10,000 random sign flips, seeded.
- **Secondary test.** Exact McNemar on case-level discordant pairs (unclustered).
- **Multiplicity.** Holm correction within pre-declared families: `rq1` (pooled + 3 per-system superiority tests), `rq2` (pooled + 3 systems). Non-inferiority (H1a) is decided by the unadjusted 95% CI. Exploratory comparisons are reported with unadjusted p-values and labelled exploratory.
- **Minimum detectable differences** (30% discordant cases, p < 0.05): about **7 points on 270 cases**, about 10 after Holm over 13 comparisons, about **14 points on 90 cases** (Hussain & Farrukh, a pre-registered Research Square preprint, [benchmarks_and_testbed §Q2][bt]). Per-system comparisons (90 cases) detect only ≈ 14-point differences; smaller observed differences are reported as "not detected", not "no difference".
- **LLM arms.** At least 3 seeds (5 if time permits); per-seed values and mean ± SD; paired tests use the per-case mean hit over seeds (values in {0, ⅓, ⅔, 1}); the bootstrap resamples clusters, not seeds. Published agent studies report ±0.6–1.6 points over 5 runs [verified_agents §Q3][va].
- **Pooling.** Per-system results are primary; pooled numbers (case-weighted, system as stratum) support H1b/H2a only within RE2; no test pools across datasets. Leave-one-system-out results are reported because pooled leaderboards picked the worse method on up to 5 of 11 subsystems (regret up to 24.8 points) [benchmarks_and_testbed §Q2][bt].
- **Proportions** (coverage, false-alarm rates, decoy flips, replay rates): cluster-bootstrap CIs where clusters exist, exact binomial CIs otherwise. The conformal guarantee is marginal and assumes exchangeability, so the empirical gap is the reported quantity.

## 9. Experiment YAML and result outputs

`veyltrace bench run bench/experiments/<name>.yaml` reads one YAML, runs every method on every case and writes `bench/results/<experiment_id>/` ([03 §13.2](03-contracts.md)).

```yaml
experiment_id: re2-oracle-rq1-v1        # unique; output directory name
description: "RQ1: AI-off vs reproduced baselines on RE2, oracle alert"
prereg: true                            # part of the frozen set (tag prereg-v1)
rq: [RQ1]
dataset:
  parts: [re2-ob, re2-ss, re2-tt]       # case_manifest.dataset ids
  cases: all                            # or a path to a case-id list
  exclude: bench/dev_cases.yaml
  normal_windows: rcaeval_pre_injection # none | rcaeval_pre_injection | veyllab
split:
  family: rcaeval-re2
  scheme: crossfit2                     # crossfit2 | loso | none
  cluster: [system, service, fault]
  stratify: [system, fault]
  seed: 20261108
protocol:
  alert: oracle                         # oracle | detected
  shift_s: 0                            # -> alert.shift_s
  sources_drop: []                      # -> sources.drop
  decoys: null                          # {pi: 0.5, rate_per_h: 2, window_s: [-1800, 300]}
  anonymize_services: false
  inject_proposals: null                # planted decoy proposals
  permute_proposals: null               # {n: 5, seed: 3}
methods:
  - {id: "veyltrace:off", kind: veyltrace, ai: {mode: "off"}, overrides: {}}
  - id: "veyltrace:brief"
    kind: veyltrace
    ai: {mode: record, relentra_mode: brief, model: qwen3.5-9b-q4_k_m, seeds: [1, 2, 3]}
  - {id: "rcaeval:baro", kind: rcaeval, rcaeval: {method: baro, length: 20}}
  - {id: "rcaeval:nsigma", kind: rcaeval, rcaeval: {method: nsigma, length: 20}}
  - {id: "simplerca", kind: internal_baseline}
  - {id: "chance", kind: internal_baseline}
calibration: {fit: true, alpha: 0.10, no_fault_beta: 0.10}   # writes config/calibration/<family>.fold*.json
metrics: [ac_at_k, avg_at_5, mrr, fine_ac_at_k, retrieval_at_k, rerank_at_1, chance, lift, coverage, set_size, risk_coverage, no_fault_rates, cost]
statistics:
  primary_metric: ac_at_1
  per: system
  noninferiority: {vs: best_simple_baseline, baselines: ["rcaeval:nsigma", "rcaeval:baro", "simplerca"]}
  holm_family: rq1
  bootstrap: {resamples: 2000, seed: 1}
  permutation: {n: 10000, seed: 2}
  mcnemar: true
resources: {workers: 2, timeout_s: 600, max_rss_mb: 3072}
```

| Field | Meaning |
|---|---|
| `experiment_id`, `description`, `prereg`, `rq` | identity; `prereg: true` files change only through §12 |
| `dataset.*` | case selection; exclusions listed in the summary; `normal_windows` adds the §5.4 normal windows |
| `split.*` | §5.4; `crossfit2` runs both folds and reports test predictions only |
| `protocol.*` | §5.1–§5.2; each value maps to a pipeline hook and is recorded in every `run_manifest` (through the config hash) |
| `methods[]` | `kind` ∈ {veyltrace, rcaeval, internal_baseline, agent_only}; `overrides` are dotted config keys; `seeds` multiply runs |
| `calibration.*` | fit on the calibration fold and write `config/calibration/` before testing |
| `metrics`, `statistics`, `resources` | §7, §8; `timeout_s` per case per method; a timeout is a miss |

Outputs ([03 §13.2](03-contracts.md)):

- `per_case.csv` — UTF-8 CSV, committed to git, sorted by `case_id, method, seed`; columns `case_id, dataset, system, method, ai_mode, seed, fold, protocol, run_outcome, pool_hit, shift_s, sources_dropped, status, ranks, hit_at_1, hit_at_3, hit_at_5, retrieval_hit, fault_class_hit, in_set, set_size, onset_error_ms, decoy_present, decoy_ranked_first, wall_ms, peak_rss_mb, tokens_in, tokens_out, verdict_hash` (booleans `0/1`, missing values empty; `run_outcome` ∈ `ok`, `failed`, `timeout`, `no_alert`; `pool_hit` = truth in the decision pool);
- `summary.json` — metrics per (dataset, system, method) with bootstrap CIs and test results;
- `manifest.json` — experiment config hash, code commit, dataset hashes.

`bench/results/tables/*.md` are generated from `summary.json` files only (R-17).

## 10. Reporting rules

1. **Release per-case outputs**: `per_case.csv` for every experiment (committed), plus verdicts, slates and cassettes of AI arms in the Zenodo artifact; none of 23 surveyed RCA papers released per-case outputs [benchmarks_and_testbed §Q2][bt]. Raw benchmark telemetry is not redistributed; dataset licences are respected.
2. **Traceability.** Every number in the paper comes from a generated table → `summary.json` → `manifest.json` → a committed experiment YAML + code commit (+ the calibration files' SHA-256 in each `run_manifest`). Runs with `code.dirty = true` are never used ([03 §12](03-contracts.md)). Estimates are labelled *estimate*.
3. **Per system, next to the floors.** Every accuracy table shows chance, prior-only, N-Sigma, BARO and the alert-count baseline per system ([02 §2 P8](02-architecture.md)); pooled rows are secondary.
4. **State the protocol** of every number: alert protocol, shift, sources present, calibration family and fold, AI arm, seeds.
5. **Denominators and exclusions**: failed runs, timeouts, undetected alerts, excluded cases (e.g. the 2 broken RE1-OB cases) and development cases are listed.
6. **Abstention is reported, not hidden.** Network-fault cells are expected to show the highest abstention ([report][report], Conclusion); they are shown, not tuned away.
7. **LLM reporting checklist** (2026 empirical-SE LLM guidelines [benchmarks_and_testbed §Q2][bt]):
   - model name, version, provider and quantisation; **GGUF SHA-256**; runtime and its version or commit (llama.cpp / Ollama);
   - decoding parameters (temperature, seed, top_k, top_p, max_tokens), context limit, budgets;
   - prompts, system briefs and JSON schemas (files and SHA-256s), released;
   - interaction logs: cassettes and hash-chained `agent_trace` files, released;
   - seeds and per-seed results (a distribution, not one run);
   - an open-weight model (the default proposer is one) and naive baselines (AI off, agent-only);
   - contamination: RCAEval and Nezha have been public since 2023–2024 and may be in training data; anonymisation-probe results;
   - non-determinism: Tier 1 and Tier 2 replay rates;
   - hardware, tokens and wall time per case;
   - vendor-reported model scores marked as vendor-reported; no LLM judge in the decision path; any judge used to evaluate prose is validated against human ratings with κ and AC1 reported.
8. **Cut items** ([07 §1.1](07-roadmap.md)) appear in the matrix as "not run" with the ADR reference.

## 11. Threats to validity (brief; long form in [11](11-research-paper-plan.md))

- **Internal.** Re-implemented baselines (`prism-plain`, `simplerca`) may differ from the originals; mitigated by unit tests and comparison with published numbers where they exist. Harness effects are large in this field (§4), so only same-harness comparisons are claimed. The lead builds the system and runs the evaluation; the pre-registration tag, the development-case list and the deviations log bound that risk but do not remove it. RCAEval normal windows have ~1.5 min baselines and may contain a previous fault's tail (§5.4).
- **Construct.** RCAEval and the lab inject faults into demo systems; they are not production incidents [rcaeval_facts, "Datasets and telemetry per system"][rc]. Labels are service-level; fine-grained RE3 labels are undefined. The change channel is tested on synthetic decoys plus a limited number of real lab changes.
- **External.** Three RCAEval systems, Nezha's two and a laptop lab; laptop-collected data has host contention. Conformal coverage assumes exchangeability, which fails across systems (LOSO reported).
- **Conclusion.** 90 cases per system detect only ≈ 14-point differences; clustered tests and Holm correction are used; LLM variance is handled with seeds.

## 12. Deviations log

| Date | Change | Frozen item affected | Reason | Test results seen before change? | ADR |
|---|---|---|---|---|---|
| — | — | — | — | — | — |

## 13. Open questions (each with a default)

1. **`per_case.csv` columns still missing.** *Resolved in 02/03 (2026-10-30):* [03 §13.2](03-contracts.md) now has `fold`, `pool_hit` and `run_outcome` (`ok`, `failed`, `timeout`, `no_alert`).
2. **Detected protocol without a breach.** *Resolved in 03 (2026-10-30):* the case is a miss, counted under `run_outcome = no_alert`.
3. **FSE'26 TT feasibility.** *Default:* stretch; decided at R-07 after checking size, format and licence.
4. **RCAEval's Lift@5 definition** is not in our notes. *Default:* ours is the ratio (§7); RCAEval's printed value is stored beside it and its definition checked against the code at M1.
5. **RCAEval normal-window placement.** *Default:* `t_alert = t_inject − 510 s` with clamped baselines (§5.4). Alternative: shorten both windows for normal segments only; rejected by default because fault cases and normal windows should be scored with the same window rule.
6. **Seeds.** *Default:* 3 seeds for `brief`, 3 for `investigate` on the 90-case subset; 5 if the M3 timing allows.
7. **Roadmap wording.** *Resolved in 07 (2026-10-30):* R-04 now names `per_case.csv`, as in [03 §13.2](03-contracts.md).

## 14. References

- [01 §9](01-vision-and-requirements.md), [02](02-architecture.md) (§2, §5.1, §6.7, §6.9, §9, §12), [03](03-contracts.md) (§2.6, §10, §12, §13), [07](07-roadmap.md), [11](11-research-paper-plan.md); engine specs [06](engines/06-faultloom.md), [07](engines/07-causatrix.md), [09](engines/09-causentra.md).
- [benchmarks_and_testbed §Q1 (datasets), §Q2 (metrics, statistics, LLM guidelines), §Q5 (lab dataset)][bt]
- [sota_methods_2026 §Q1 (DecompRCA, RCAtlas, harness variance), §Q5 (implementations)][sm]
- [novel_building_blocks §Q5 (RCAEval-C), §Q6 (telemetry ablation, LOSO), §Q7 (conformal)][nbb]
- [verified_agents_local_llms §Q3 (replay tiers), §Q6 (abstention), §Q8 (explanation metrics)][va]
- [rcaeval_facts][rc] (RCAEval dataset layout, ground truth and scoring, windows, data quirks, published baseline numbers and PRISM details, each with its primary source)
- [v2 research report][report]

[bt]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md
[sm]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/sota_methods_2026.md
[nbb]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/novel_building_blocks.md
[va]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/verified_agents_local_llms.md
[rc]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md
[report]: ../reports/Veyltrace%20v2%20SOTA%20root%20cause%20analysis.md
