# 13 · Glossary

> **Status:** v1.0-draft · **Owner:** Aniket Kumar (lead) · **Last updated:** 2026-10-30
> Definitions follow [02-architecture](02-architecture.md) and [03-contracts](03-contracts.md); if a definition here disagrees with them, they win and this file is fixed. Metric formulas that depend on RCAEval's code are marked "per RCAEval" and must match the pinned RCAEval commit.

## 1. Metrics

| Term | Definition | Where |
|---|---|---|
| **AC@k** (also Top-k, PR@k) | Share of cases whose true root cause is among the first k entries of the ranking. Headline metric is service-level **AC@1**, always reported per system. The fine-grained variant scores `"{service}_{indicator}"` strings (`verdict.ranks_rcaeval`). | [04](04-evaluation-protocol.md); [03 §10](03-contracts.md) |
| **Avg@5** | Mean of AC@1 … AC@5 for a case set, per RCAEval: Avg@k = (1/k) Σ_{j=1..k} AC@j. | [04](04-evaluation-protocol.md) |
| **MRR** | Mean reciprocal rank of the true root cause. | [04](04-evaluation-protocol.md) |
| **Retrieval@K** | Share of cases whose true root cause is in the retrieval stage's top K. In Veyltrace, the retrieval stage is the Causatrix slate (K = 5 by default). It is an upper bound on final accuracy and on conformal coverage. From the DecompRCA decomposition; exposed by RCAEval as `--report-decomposition K`. | [02 §6.7](02-architecture.md) |
| **Rerank@1** | Among cases where retrieval succeeded, the share where the true root cause is ranked first. AC@1 = Retrieval@K × Rerank@1. | [02 §6.7](02-architecture.md) |
| **Chance@5** | Expected AC@5 of a random ranking of the case's services, per RCAEval's `--report-chance`. | [04](04-evaluation-protocol.md) |
| **Lift@5** | RCAEval's chance-corrected score reported by `--report-chance`; take the exact formula from the pinned RCAEval code. | [04](04-evaluation-protocol.md) |
| **Proposer lift** | Verified AC@1 with `ai.mode = record` minus verified AC@1 with `ai.mode = off`, on the same cases, with a paired CI. Not the same as Lift@5. | RQ2 in [04](04-evaluation-protocol.md) |
| **Decoy rejection rate** | Share of cases where a planted wrong proposal with fabricated claims does not become the verdict's top-1. | RQ2 |
| **Coverage** | Share of held-out test cases whose true root cause is inside the conformal candidate set; never measured on the calibration split. | RQ3; [ADR conformal-abstention](adr/20261030-ak-conformal-abstention.md) |
| **Set size** | Number of candidates in the conformal set. | RQ3 |
| **Abstention rate** | Share of cases with status `INCONCLUSIVE` (and, separately, `NO_FAULT`). | RQ3 |
| **AURC** | Area under the risk–coverage curve: error rate as a function of the share of cases answered, when cases are answered in order of confidence. Lower is better. | RQ3 |
| **MDD** | Minimum detectable difference: the smallest accuracy difference a test can detect at the chosen significance. About 7 points on 270 cases and 14 on 90 with ~30% discordant cases, per a pre-registered RCAEval study. | [01 §9](01-vision-and-requirements.md) |
| **Cluster** | A group of RCAEval cases sharing (system, root service, fault). Repetitions in a cluster are not independent, so bootstrap and permutation tests resample clusters. | [04](04-evaluation-protocol.md) |
| **Tier-2 regeneration match rate** | Share of recorded cases whose LLM output is byte-identical when regenerated on the same machine and settings. Measured, never guaranteed. | RQ6 |

## 2. Pipeline, evidence and decision

| Term | Definition | Where |
|---|---|---|
| **Case** | One incident window from one dataset, identified by an opaque `case_id` (first 12 hex of SHA-256 of the original folder name or capture id). | [03 §1](03-contracts.md) |
| **Entry service** | A service that receives external traffic (`graph.nodes.is_entry`). SLO breaches are detected there. | [03 §6.1](03-contracts.md) |
| **Atom** (evidence atom) | One row of `evidence`: a numeric observation about one candidate, with `kind`, `value`, `window`, `refs` to source rows and `origin` (`engine` or `claim_check`). Its `atom_id` is `E` + 10 hex of SHA-256 over (kind, candidate, canonical args), so the same inputs give the same IDs. Only FaultLoom creates atoms. | [02 §6.6](02-architecture.md); [03 §7](03-contracts.md) |
| **Evidence card** | A compact, code-computed summary of one slate candidate (its top atoms, timeline and propagation path) given to Relentra in `brief` mode instead of raw telemetry. | [02 §6.8](02-architecture.md) |
| **Slate** | Causatrix's output: the top-K candidates (default K = 5) with per-ranker ranks, fused score, mode, fault class and indicator, plus `all_scores` for every service. | [02 §6.7](02-architecture.md); [03 §8](03-contracts.md) |
| **Proposal** | Relentra's output for one hypothesis: a candidate (service, fault class, indicator) from closed enums, claims, requested trials and a display-only rationale. Proposals are data, never decisions. | [02 §6.8](02-architecture.md); [03 §9.1](03-contracts.md) |
| **Claim** | `{predicate, args, cites}` inside a proposal: a request to evaluate a library predicate. It counts only through the code result of the claim pass. | [03 §9.1](03-contracts.md) |
| **Predicate** | A named function in FaultLoom's library (e.g. `zscore_above`, `onset_before`, `change_before_onset`) with a fixed signature, a fixed polarity (supports or refutes the subject being the root) and a fixed weight from config. The first argument is the subject service. | [02 §6.6](02-architecture.md); [03 §7](03-contracts.md) |
| **Pool** | Two pools, never confused. **Claim-pass pool**: slate ∪ all proposed candidates (pipeline step 8). **Decision pool**: slate ∪ proposed candidates (in `graph.nodes`) with at least one supporting claim that holds; T10 is then a mandatory trial for those proposal-origin candidates. | [02 §4, §6.9](02-architecture.md) |
| **Claim pass** | Pipeline step 8: FaultLoom evaluates every predicate Relentra cited for every candidate in the claim-pass pool and appends `claim_check` atoms with `holds` set. Unknown predicates are rejected. | [02 §4](02-architecture.md) |
| **Symmetric evaluation** | The rule behind the claim pass: a predicate the AI asks about is evaluated for every pool candidate, not only the one it advocates. The AI can surface discriminating evidence but cannot argue for its favourite. | [02 §2 P2](02-architecture.md) |
| **Trial** | One of T1–T10, a deterministic check Causentra runs on a candidate (origin, precedence, propagation, silence, latency accounting, change alignment, peer contrast, intervention, leave-one-source-out, claim checks). Result: `pass`, `fail` or `untestable(reason)`. T1–T4 are mandatory; T10 is mandatory for proposal-origin candidates only. Trial factors: pass 1.0; mandatory untestable 0.85, failed 0.25; supporting untestable 1.0, failed 0.9. | [02 §6.9](02-architecture.md) |
| **Verified score V(c)** | The decision function's score: normalised fused score × trial factors × (1 + clipped weighted sum of claim-pass results for c). | [02 §6.9](02-architecture.md) |
| **Verdict** | Causentra's output: status, root (or null), conformal candidate set, ranked pool with trial results, confidence, asks, accepted and rejected proposals. | [03 §10](03-contracts.md) |
| **verdict_hash** | SHA-256 of the canonical JSON of the verdict without the hash field. Replay must reproduce it. | [02 §6.9](02-architecture.md) |
| **Asks** | What the verdict says would settle an inconclusive case: missing telemetry, a trial, or context. | [03 §10](03-contracts.md) |
| **Card** | Causivra's incident card: title, status, root, set, timeline, path, evidence table, why-not, asks, next steps. LLM prose uses placeholders filled by code and passes a claim checker, or falls back to a template. | [02 §6.10](02-architecture.md) |
| **Canonical JSON** | Sorted keys, `(",", ":")` separators, UTF-8, floats rounded to 9 decimals, NaN/Inf → null. Basis of every hash. | [03 §1](03-contracts.md) |

## 3. Uncertainty and status

| Term | Definition | Where |
|---|---|---|
| **α** | Target miscoverage of the conformal set. Default 0.10, i.e. a 90% coverage target. | [02 §6.9](02-architecture.md) |
| **Nonconformity** | For a decision-pool candidate c: s(c) = 1 − V(c) / max V over the decision pool. Lower means more like the root. | [02 §6.9](02-architecture.md) |
| **q̂** (q-hat) | The split-conformal threshold: the ⌈(n+1)(1−α)⌉-th smallest calibration score over n calibration cases, where a case's score is the true root's nonconformity, or +∞ when the true root was outside the decision pool; q̂ = +∞ if that index exceeds n (`q_hat` null in the verdict). Uncalibrated default q̂ = 0 (set = top candidate only). | [02 §6.9](02-architecture.md); [ADR conformal-abstention](adr/20261030-ak-conformal-abstention.md) |
| **Conformal set** (candidate set) | Every decision-pool candidate with nonconformity ≤ q̂. Its coverage guarantee is marginal and assumes calibration and test cases are exchangeable; it never contains services outside the decision pool. | [02 §6.9](02-architecture.md) |
| **Calibration family** | The group of cases a q̂ is fitted on and applied to (default: one per benchmark family; splits by cluster). Calibration files live in `config/calibration/<family>.json`, written by `bench`, read by Causentra through `ctx.config`, and hashed into run manifests. | [02 §6.9, §12](02-architecture.md); [03 §12.1](03-contracts.md); [04](04-evaluation-protocol.md) |
| **Margin** | (V_top − V_runner-up) / V_top; 1.0 if there is no runner-up. | [02 §6.9](02-architecture.md) |
| **Confidence level** | `confidence.level`: CONFIRMED → `high`, LIKELY → `medium`, INCONCLUSIVE with a leader → `low`, otherwise `none`. Never a probability. | [02 §6.9](02-architecture.md); [03 §10](03-contracts.md) |
| **CONFIRMED** | Set size 1, all mandatory trials pass, margin to the runner-up ≥ c_high (0.30). | [02 §6.9](02-architecture.md) |
| **LIKELY** | Top candidate passes all mandatory trials, set size ≤ 3, margin ≥ c_med (0.15). | [02 §6.9](02-architecture.md) |
| **INCONCLUSIVE** | Any case that is not `CONFIRMED`, `LIKELY` or `NO_FAULT`. The verdict lists asks. | [02 §6.9](02-architecture.md) |
| **NO_FAULT** | No service is silent and M ≤ τ_nf, where M is the max of the entry service's external `score_norm` and every internal `score_norm` (`robust_z` detector). τ_nf is the (1 − β)-quantile of M over normal windows (β = 0.10; from `synth-05`, VeylLab no-fault captures and RCAEval pre-injection segments); uncalibrated default τ_nf = log1p(3). The candidate set is empty. | [02 §6.9](02-architecture.md); [ADR conformal-abstention](adr/20261030-ak-conformal-abstention.md) |
| **LOSO** (leave-one-system-out) | Calibrate or tune on all systems but one, test on the held-out system. Used to report how coverage and thresholds transfer. | [04](04-evaluation-protocol.md) |

## 4. Time and alert protocols

| Term | Definition | Where |
|---|---|---|
| **t_alert** | The time an engine is told the incident was raised, read from `alert.json`, which core's alert step (pipeline step 1) writes. Engines never see the injection time. | [02 §5.1](02-architecture.md); [03 §2.6](03-contracts.md) |
| **Oracle-alert protocol** | t_alert = the dataset's published injection time, passed by the adapter as `case_manifest.t_alert_hint_ns` and copied by core's alert step. Comparable with RCAEval literature. | [02 §5.1](02-architecture.md) |
| **Detected-alert protocol** | t_alert = first entry-service SLO breach, found when core's alert step calls Anomara's `detect_alert(telemetry)`; `t_alert_hint_ns` is null. Realistic; reported next to the oracle protocol. | [02 §5.1](02-architecture.md) |
| **Live protocol** | t_alert = the gateway watcher's trigger or the "Diagnose now" click time, passed as the hint. Demo only. | [02 §5.1](02-architecture.md) |
| **t_onset** | Incident onset estimated by Anomara: the second-earliest external-klass onset among services, clamped to [t_alert − 60 s, t_alert + 300 s]. Downstream scoring windows are anchored here. | [02 §6.3](02-architecture.md) |
| **Baseline / incident window** | Defaults [t_alert − 20 min, t_alert − 2 min] and [t_alert − 2 min, t_alert + 8 min], clamped to available data. | [02 §5.1](02-architecture.md) |
| **Alert shift** | Robustness test that moves t_alert by ±60 or ±120 s (`alert.shift_s`, applied by core's alert step and recorded as `alert.shift_ns`). | [02 §5.1](02-architecture.md); [07 O-09](07-roadmap.md) |

## 5. Signals and fault taxonomy

| Term | Definition | Where |
|---|---|---|
| **klass** | Tag on every series: `internal` (resource, self-time, own logs), `external` (caller-visible latency and errors) or `context` (traffic). Spelled with a k to avoid the Python keyword. PRISM's internal-versus-external split. | [02 §6.2](02-architecture.md); [03 §1](03-contracts.md) |
| **family** | Signal family of a series: `cpu`, `mem`, `disk`, `net`, `latency`, `errors`, `traffic`, `logs`, `self_time`, `other`. | [03 §1](03-contracts.md) |
| **Mode** | Coarse fault mechanism: `resource`, `network`, `code`, `change`, `dependency`, `unknown`. | [03 §1](03-contracts.md) |
| **Fault class** | Fine fault type: `cpu`, `mem`, `disk`, `socket`, `delay`, `loss`, `error`, `exception`, `availability`, `config`, `dependency`, `unknown`. Assigned from evidence patterns by a rule table. | [02 §6.7](02-architecture.md); [03 §1](03-contracts.md) |
| **Indicator** | The candidate's top-scoring signal family; the root-cause metric in RCAEval's fine-grained scoring. | [02 §6.7](02-architecture.md) |
| **Silence** | A series that drops to zero or disappears; treated as an anomaly, never as health. | [02 §6.3](02-architecture.md) |
| **Self-time** | A span's duration minus its children's; attributes latency to the service doing the work. | [02 §6.2](02-architecture.md) |
| **Critical path** | The longest chain of spans that determines a trace's end-to-end latency (CRISP-style). Critical-path share is a service's mean share of end-to-end latency on that path. | [02 §6.2](02-architecture.md); [03 §3.4](03-contracts.md) |
| **CP-SBFL** | Critical-path-weighted spectrum-based fault localisation: Ochiai spectrum counts weighted by each service's critical-path self-time share. The `cp_sbfl` ranker. | [02 §6.7](02-architecture.md) |
| **RRF** (reciprocal rank fusion) | Fusion of rankings by summing 1/(k + rank) over rankers, k = 60. *Gated*: a ranker votes only if its input channel exists for the case. Weights fixed a priori at 1.0. | [02 §6.7](02-architecture.md) |
| **Telemetry ablation** | Re-running cases with sources dropped (`sources.drop`: metrics, logs, traces or events) to test graceful degradation. | [02 §9](02-architecture.md); [07 O-09](07-roadmap.md) |
| **Change proximity** | exp(−Δt / τ_change) for the latest change on a candidate before its onset. | [02 §6.4](02-architecture.md) |
| **Peer contrast** | Difference in anomaly between a changed or affected replica and its healthy peers. | [02 §6.4](02-architecture.md) |
| **Decoy change** | A synthetic change event on a service that is not the root, injected by `bench` to test that the change channel is not gullible. | [02 §6.4](02-architecture.md) |
| **Decoy proposal** | A planted wrong hypothesis with fabricated claims, used to test that the verifier rejects it. | RQ2 |

## 6. Provenance and replay

| Term | Definition | Where |
|---|---|---|
| **ai.mode** | `off` (no LLM; template card), `record` (LLM calls run and are recorded), `replay` (LLM outputs read from the cassette; any unrecorded call fails). | [02 §5.2](02-architecture.md) |
| **brief / investigate** | Relentra's two modes: `brief` (default) makes one or two LLM calls over evidence cards; `investigate` runs a budgeted multi-turn tool loop, used as an ablation. | [02 §6.8](02-architecture.md) |
| **Cassette** | The recorded LLM calls of a run, keyed by SHA-256 of the canonicalised request. Replay reads it instead of calling the model. | [02 §6.8](02-architecture.md) |
| **Agent trace** | `agent_trace.jsonl`: Relentra's state transitions, LLM calls and tool calls as a hash chain, `line_hash = sha256(prev_hash ‖ canonical_json(line))`. | [03 §9.2](03-contracts.md) |
| **Run manifest** | `run_manifest.json`: code commit (and dirty flag), environment, config hash (of `config.lock.json`, the fully resolved config in the run dir), `uv.lock` and calibration hashes, input and output hashes, AI settings. No timestamps. | [03 §12](03-contracts.md) |
| **Receipt** | `receipt.json`: the run manifest, `verdict_hash`, `card_hash` and agent-trace head, wrapped as an in-toto Statement v1 with predicate type `https://veyltrace.dev/rca-verdict/v1`. | [02 §6.10](02-architecture.md); [03 §11.2](03-contracts.md) |
| **Replay** | `veyltrace replay <receipt>`: by default re-hash the stored outputs of steps 0–4, `config.lock.json`, the calibration file and the cassette, then re-run steps 5–10 and compare hashes; `--full` re-hashes the raw inputs and re-runs steps 0–10. Exit codes: 0 ok, 1 error, 2 verdict mismatch, 3 inputs missing or changed, 4 invalid config, 5 environment drift (Python major.minor, library versions or `uv.lock`; OS reported only), 6 narrative mismatch only. | [02 §6.10](02-architecture.md) |
| **Tier 1 / Tier 2 replay** | Tier 1 (guaranteed): re-verify recorded LLM outputs to the same `verdict_hash`. Tier 2 (best effort): regenerate identical LLM outputs on the same machine; only measured. | [ADR local-first-llm](adr/20261030-ak-local-first-llm.md) |
| **run_id** | First 16 hex of SHA-256 over (case_id, config hash, code commit, ai.mode). Not a timestamp. | [02 §4.1](02-architecture.md) |

## 7. Evaluation and data

| Term | Definition | Where |
|---|---|---|
| **RE1 / RE2 / RE3** | RCAEval's three suites (735 cases in total). RE2 has 270 cases (90 per system); RE3 has 90 (30 per system). | [04](04-evaluation-protocol.md) |
| **OB / SS / TT** | Online Boutique, Sock Shop, Train Ticket (RCAEval systems). Sock Shop has no traces in RE2/RE3. | [04](04-evaluation-protocol.md) |
| **Answer key** | Ground-truth table (root service, fault class, injection times, decoys; for lab cases also `validated` and `sli_impact_json`). Read only by `bench/` and `lab/`. | [03 §13.1](03-contracts.md) |
| **RCAEval-C** | Our extension of RCAEval with synthetic change events: a true change aligned with the injected fault with probability π, plus decoy changes on other services. | [02 §6.4](02-architecture.md); [07 O-13](07-roadmap.md) |
| **VeylLab** | Our laptop-collected dataset from Online Boutique (and optionally the OTel Demo) with published injection parameters, impact validation and no-fault controls. | [05-fault-lab-and-dataset](05-fault-lab-and-dataset.md) |
| **synth-01…05** | The five synthetic cases from `veyltrace_core.synth` on a six-service toy system: CPU hog, network delay, error injection, change-induced regression, no fault. | [08 §8](08-collaboration-and-git.md) |
| **Golden fixture** | A producer's checked-in outputs for `synth-01…05` under `packages/<engine>/fixtures/`, loaded by consumers with `veyltrace_core.testing.golden(contract, case)`, so no lane waits for another. | [03 §1](03-contracts.md); [08 §8](08-collaboration-and-git.md) |
| **Pre-registration** | A tagged commit fixing hypotheses, splits and analysis before any test-split result is seen. | [11 §8](11-research-paper-plan.md) |

## 8. Process

| Term | Definition | Where |
|---|---|---|
| **Lane** | One person's area of ownership: Observe, Reason (lead) or Explain. A lane edits only its own paths, listed in `.github/lanes.yml`; CI rejects cross-lane edits without the `cross-lane` label. | [08 §2](08-collaboration-and-git.md); [AGENTS.md §2](../AGENTS.md) |
| **CCR** (Contract Change Request) | The issue form used to change a contract after M1: what, why, producer and consumers, additive or breaking. Paired with an ADR; the lead implements it. | [08 §5](08-collaboration-and-git.md) |
| **ADR** (architecture decision record) | A short dated file recording one decision, its alternatives and consequences: `docs/adr/YYYYMMDD-<initials>-<slug>.md`. | [adr/README](adr/README.md) |
| **Worktree** | A separate git working directory on its own branch; one per agent session, so two agents never share a working copy. | [08 §4](08-collaboration-and-git.md) |
| **Towncrier fragment** | One-sentence changelog entry `changes/<issue>.<type>.md`, one per PR, compiled into release notes at release. Replaces a hand-edited CHANGELOG. | [08 §3.1](08-collaboration-and-git.md) |
| **Entry point** | A Python packaging hook (`veyltrace.engines`, `.adapters`, `.fetchers`, `.rankers`, `.trials`, `.predicates`) declared in each package's own `pyproject.toml`, replacing central registries. | [08 §3.1](08-collaboration-and-git.md) |
| **Milestones M0–M5** | Ground ready (3 Nov), contracts frozen (8 Nov), AI-off scored (15 Nov), AI-on and live (22 Nov), results frozen (29 Nov), v1.0.0 (1 Dec). | [07 §1](07-roadmap.md) |
| **Cut list** | The ordered list of features dropped if a milestone slips by more than a day. | [07 §1.1](07-roadmap.md) |

## 9. The ten engines

| # | Engine | Role in one line | Lane | Spec |
|---|---|---|---|---|
| 1 | **Infralume** | Ingests benchmark folders, lab captures and live OTLP into canonical telemetry tables and scrubs leakage. | Observe | [engines/01-infralume](engines/01-infralume.md) |
| 2 | **Signalyth** | Turns telemetry into typed signals: series with klass tags, call edges, log templates, critical paths. | Observe | [engines/02-signalyth](engines/02-signalyth.md) |
| 3 | **Anomara** | Scores anomalies per series, estimates onsets and the incident onset, flags silent services. | Observe | [engines/03-anomara](engines/03-anomara.md) |
| 4 | **Causync** | Aligns clocks across sources, builds the change timeline and scores change proximity and peer contrast. | Observe | [engines/04-causync](engines/04-causync.md) |
| 5 | **Causalith** | Builds the dependency graph with provenance and computes candidate propagation paths. | Observe | [engines/05-causalith](engines/05-causalith.md) |
| 6 | **FaultLoom** | Creates all evidence atoms and runs the symmetric claim pass over the predicate library. | Reason | [engines/06-faultloom](engines/06-faultloom.md) |
| 7 | **Causatrix** | Runs six deterministic rankers, fuses them and outputs the hypothesis slate. | Reason | [engines/07-causatrix](engines/07-causatrix.md) |
| 8 | **Relentra** | LLM investigator that proposes candidates, claims and trials; never decides. | Explain | [engines/08-relentra](engines/08-relentra.md) |
| 9 | **Causentra** | Deterministic verifier: runs trials, applies the decision function, conformal set and abstention; seals `verdict_hash`. | Reason | [engines/09-causentra](engines/09-causentra.md) |
| 10 | **Causivra** | Writes the incident card under a claim checker, assembles the receipt and implements replay. | Explain | [engines/10-causivra](engines/10-causivra.md) |
