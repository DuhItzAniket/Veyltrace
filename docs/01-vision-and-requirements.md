# 01 · Vision and requirements

> **Status:** v1.0-draft · **Owner:** Aniket Kumar (lead) · **Last updated:** 2026-10-30
> Master spec: [02-architecture](02-architecture.md). If this doc disagrees with 02, 02 wins and this doc is fixed.
> Every number here is cited (`[note §Q]` links to the research notes), is a default stated in 02, or is labelled *target* or *estimate*. Targets are goals for v1.0, not results. Results exist only in `bench/results/` ([AGENTS.md §4.8](../AGENTS.md)).
> Terms are defined in [13-glossary](13-glossary.md).

## 1. Problem

When a microservice system degrades, an on-call engineer has to work out which service, resource or change caused it, from metrics, logs, traces and change events that usually live in different tools. Four facts frame the problem.

**1. Outages are costly, and diagnosis is the slow part.** All figures below are from vendor-run or vendor-sponsored surveys unless marked otherwise.

| Claim | Number | Source | Caveat |
|---|---|---|---|
| Median hourly cost of a high-impact outage | USD 2M per hour (~USD 33,333 per minute) | New Relic 2025 Observability Forecast, 1,700 respondents ([press release](https://newrelic.com/press-release/20250917)) | vendor survey |
| Cost per minute of downtime; average time to resolve an incident | USD 4,537 per minute; 175 minutes | PagerDuty 2024, 500 IT leaders ([release](https://investor.pagerduty.com/news/news-details/2024/PagerDuty-Survey-Reveals-Customer-Facing-Incidents-Increased-by-43-During-the-Past-Year-Each-Incident-Costs-Nearly-800000/default.aspx)) | vendor survey |
| Annual downtime cost for the Global 2000 | USD 400B per year | Splunk + Oxford Economics, June 2024 ([blog](https://www.splunk.com/en_us/blog/cio-office/uncovering-downtime.html)) | vendor-sponsored |
| SREs who say diagnosis is the hardest part of incident management | 53% of 423 | Catchpoint SRE survey ([DevOps.com](https://devops.com/sres-say-theres-plenty-of-room-to-improve-incident-management/)) | vendor survey; year not confirmed |
| Diagnosis time saved by an agentic RCA system at one company | 77.3% less diagnosis time | KRCA at Kuaishou, preprint ([sota_methods §Q2][sota]) | one company's deployment; absolute times not in our notes |

The first four rows come from the v1 market notes, which are kept in the team's local archive, not in the repository (see [ADR hackday-v1-archived](adr/20261030-ak-hackday-v1-archived.md)); the primary URLs are given so each number can be checked, and each must be re-verified against its primary source before publication. No reliable survey splits time-to-resolve into diagnosis versus repair, so we do not claim a diagnosis share.

**2. Most outages follow a change, but research benchmarks contain no changes.** In Google's 2010–2017 postmortems, binary pushes (37%) and configuration pushes (31%) triggered 68% of outages. RCAEval, PetShop and OpenRCA, the benchmarks academic RCA methods are scored on, carry no deploy, config or flag events ([novel_building_blocks §Q5][nb]).

**3. Automated diagnosis is not trusted, for good reasons.**

- In a NeuBird-sponsored survey (The Register × NeuBird, April 2026, n = 696), 60% named lack of trust as the main barrier to AI in operations, 59% required near-perfect accuracy, and 73% were not using AIOps at all ([stack_and_market §B1][sm]).
- Vendor accuracy claims of 90–95% are self-reported. Independent benchmarks are far lower: frontier LLMs recover the exact root-cause set in 20.7% of OpenRCA 2.0 cases on average, the best model reaches 25.3% (medium) and 10.0% (hard) on ORCA-bench, and ITBench-AA pass rates stay below 42% ([stack_and_market §B1][sm]; [sota_methods §Q2][sota]).
- Simple LLM harnesses with 2026 frontier cloud models reach a mean PR@1 of 72.8% (SQL agent) and 77.2% (Codex harness), averaged over three models, on the 90-case RCAtlas set (preprint), against 38.9% for the best non-LLM method ([sota_methods §Q2][sota]; [verified_agents §Q1][va]). We found no 2024–2026 paper that evaluates a model of 10B parameters or fewer as the investigating RCA agent; the closest are SpecRCA's fine-tuned 3B verifier and ThinkFL, which fine-tunes lightweight LLMs of unconfirmed size ([verified_agents §Q1][va]; [sota_methods §Q2][sota]).
- One planted false sentence made models name a decoy first in 21–42% of flagged RCAEval RE2 cases (Hussain & Farrukh, a pre-registered Research Square preprint, not peer-reviewed) ([benchmarks_and_testbed §Q2][bt]).

**4. The field's own measurements are fragile.** Shifting the assumed fault onset two minutes late drops N-Sigma from 0.80 to 0.07 AC@1 on RE2 (same Research Square preprint). Leave-one-system-out selection picks the worse method on up to 5 of 11 subsystems, and none of 23 RCA papers audited released per-case outputs (Hu, Liu & Fu, arXiv preprint) ([benchmarks_and_testbed §Q2][bt]).

**Problem statement.** There is no open, laptop-runnable RCA engine that (a) ranks root-cause candidates with cheap deterministic methods, (b) lets an LLM contribute without being trusted, (c) says when it does not know, (d) lets anyone replay a verdict and get the same result, and (e) publishes per-case accuracy on public benchmarks against honest baselines.

## 2. Vision

Veyltrace diagnoses microservice outages from metrics, logs, traces and change events. Statistical rankers and a local LLM **propose** hypotheses; a deterministic verifier **decides**. The output is a verdict with a root cause, a calibrated candidate set, a status that may be `INCONCLUSIVE` or `NO_FAULT`, the evidence behind it, a plain-English incident card, and a receipt that replays to the same `verdict_hash`. It runs on a 16 GB laptop with no cloud ([02 §1](02-architecture.md)).

One sentence for the README: *AI proposes, code decides, and every verdict is replayable.*

## 3. Who it is for

| User | What they need | What Veyltrace gives them | Interface |
|---|---|---|---|
| **On-call SRE** | A first diagnosis fast enough to act on, with the evidence, and an honest signal when the tool is unsure | Root cause or candidate set, status, evidence table, timeline, propagation path, "asks" for missing data, deterministic next steps | Console, `card.md`, CLI |
| **Platform / observability team** | An engine that fits the telemetry they already emit, runs locally, sends no data out, and can be audited | OTLP ingest, backend-neutral Parquet store, receipts and replay, localhost-only LLM by default | Gateway HTTP API, CLI, receipts |
| **Researchers** | A reproducible RCA harness with honest baselines, per-system statistics, per-case outputs and robustness protocols | `bench/` with pinned baselines, oracle and detected alert protocols, telemetry ablation, decoy changes (RCAEval-C), VeylLab data | `veyltrace bench run`, released artifacts |
| **Other AI agents** (AI SRE agents, coding agents) | A grounding and verification tool they can call instead of trusting their own claims | `verify_hypothesis`, `diagnose`, `get_receipt` over MCP | MCP server (task X-12; 4th on the cut list) |

Positioning for the last group follows the market notes: exposing the engine as an MCP verification tool makes it a complement to commercial agents rather than a competitor ([stack_and_market §B2][sm]).

## 4. Goals

| ID | Goal | Measured by |
|---|---|---|
| G-1 | **Accurate, honestly compared.** Rank the true root cause at least as well as the best simple baseline we can reproduce, per system. | RQ1 in [04-evaluation-protocol](04-evaluation-protocol.md); §9 SC-3 |
| G-2 | **Verifiable.** LLM output changes a verdict only through predicates that code re-evaluates for every candidate. | RQ2; decoy rejection; AI-on vs AI-off |
| G-3 | **Calibrated and willing to abstain.** Return a candidate set with a coverage target, and `NO_FAULT` or `INCONCLUSIVE` when evidence is thin. | RQ3; §9 SC-4 |
| G-4 | **Replayable.** Any verdict re-runs from its receipt to the same hash on another laptop. | RQ6; §9 SC-6 |
| G-5 | **Change-aware.** Deploys, config changes and flag flips are an evidence channel that decoy changes cannot easily fool. | RQ4 (RCAEval-C); §9 SC-7 |
| G-6 | **Local and cheap.** Seconds per case on CPU for the deterministic path; local open-weight LLM. | RQ5; §8 NFR-3, NFR-4 |
| G-7 | **A citable research artifact.** Paper draft, DOI-archived release, per-case outputs, reproduction script. | M4, M5; [11-research-paper-plan](11-research-paper-plan.md) |
| G-8 | **A working live demo** on Online Boutique. | M3; §9 SC-9 |

## 5. Non-goals for v1.0

From [02 §11](02-architecture.md) (binding):

- Automatic remediation or any write action on the cluster.
- A chat interface over raw logs.
- GNN trace models, full causal discovery over all series, LLM-prior causal discovery.
- LLM-as-judge anywhere in the decision path.
- Multi-tenant auth, RBAC, hosted SaaS.
- Training or fine-tuning LLMs (a fine-tuned small verifier is a post-v1.0 research idea).

Also out of scope for v1.0, per other binding docs and the research:

- Live agent benchmarks (SREGym, AIOpsLab, ITBench): they are mitigation-centric, judged by LLMs, and need about 16 GB for the cluster alone ([report][rep], "Three benchmark tiers").
- Train Ticket in the lab: it needs at least 24 GB of memory ([benchmarks_and_testbed §Q3][bt]).
- OTel Profiles and eBPF instrumentation (OBI): alpha and pre-1.0, Linux-kernel-only ([stack_and_market §A1][sm]).
- Cloud deployment: post-v1.0 ([02 §10](02-architecture.md)).

## 6. Market gap

### 6.1 What exists (October 2026)

| Category | Products | Relevant facts |
|---|---|---|
| Hyperscaler agents | AWS DevOps Agent, Azure SRE Agent, Google Gemini Cloud Assist investigations | AWS: GA 31 Mar 2026, USD 0.0083 per agent-second (≈ USD 29.88 per agent-hour). Azure: GA with a 30-day trial per a 26 Aug 2026 update, billed in Azure Agent Units, no dollar price per unit found. Google: still public preview ([stack_and_market §B1][sm]) |
| Observability vendors | Datadog Bits AI SRE, Dynatrace Intelligence, New Relic SRE Agent, Grafana Assistant Investigations, PagerDuty SRE Agent | Datadog claims higher accuracy "on internal benchmarks" with no figures. Dynatrace and New Relic pitch deterministic analysis plus agents on closed platforms. Grafana Investigations GA 29 Jul 2026, token-metered from 1 Oct 2026 ([stack_and_market §B1][sm]) |
| Startups (closed) | Resolve AI, Traversal, Causely, Komodor, incident.io | Resolve AI raised at a USD 1B valuation (Feb 2026). Komodor's ">95%" and incident.io's "90%+" are self-reported. Causely ships an MCP server. incident.io exposes "rejected theories" ([stack_and_market §B1][sm]) |
| Open source | HolmesGPT, k8sgpt, Coroot, Rootly AI Labs | HolmesGPT: CNCF Sandbox, Apache-2.0, no published accuracy results. Coroot sends ~9.8K tokens of deterministic findings to a model with no tools; its AI RCA is paywalled or cloud-metered ([stack_and_market §B1][sm]) |

### 6.2 What nobody combines

No product or open-source project found offers all five of the following together ([stack_and_market §B2][sm]); this comes from searches, not an exhaustive review:

1. an OTLP-native, backend-neutral engine that runs on a laptop;
2. deterministic, replayable diagnoses with a run manifest;
3. per-claim verifiers that check each hypothesis against telemetry and change events, with abstention;
4. public benchmark scores with failure cases;
5. an MCP/HTTP interface so other AI SRE agents can call it to ground and verify their hypotheses.

### 6.3 What we claim and what we do not

| We may claim (once results support it) | We must not claim |
|---|---|
| Open, laptop-runnable, OTLP-native engine with replayable verdicts | "First deterministic or causal RCA" (Dynatrace, New Relic, Causely and Traversal already pitch this) |
| Every LLM claim is re-checked by code, symmetrically across candidates | That grading hypotheses is new (Datadog marks hypotheses validated, invalidated or inconclusive; incident.io shows rejected theories) |
| Calibrated candidate sets with abstention, hedged as "to our knowledge, based on searches up to Oct 2026" | "First calibrated RCA" or "first conformal RCA" without qualification (LM-PACE calibrates LLM root-cause confidence; CROC and an OSDI'26 abstention paper are close and were seen only as snippets; see [02 §2 P4](02-architecture.md) and [11 §4](11-research-paper-plan.md)) |
| Published per-case accuracy with honest baselines | Autonomous remediation |
| Zero marginal cost per diagnosis on a laptop | Any accuracy number not produced by our own `bench/results/` |

"Deterministic core plus LLM narration" is no longer distinctive: Dynatrace, New Relic, Coroot and k8sgpt use it. The difference has to be openness, replay, symmetric verification and published evaluation ([stack_and_market §B1][sm]). Coroot or HolmesGPT could add similar features; the defensible part is research rigour, not code ([stack_and_market §B2][sm]).

## 7. Functional requirements

Each requirement has an acceptance test. "Task" is the roadmap issue in [07-roadmap](07-roadmap.md) that delivers it. Field-level details are in [03-contracts](03-contracts.md).

| ID | Requirement | Acceptance test | Engine / component | Task |
|---|---|---|---|---|
| FR-1 | Ingest RCAEval RE1, RE2 and RE3 cases into canonical telemetry tables and a `case_manifest`. | Every RE2 case ingests; ≤ 10 s per case; outputs validate against the schemas. | Infralume | O-01 |
| FR-2 | Ingest Nezha cases, VeylLab captures and live OTLP snapshots through separate adapters; FSE'26 TrainTicket if its size, format and licence are confirmed. | Nezha cases ingest; a lab capture ingests; a live snapshot ingests and hashes. | Infralume | O-07, O-08, X-10 |
| FR-3 | Scrub leakage at ingest: deny-listed attributes (`feature_flag.*`, `chaos*`, `fault*`, `inject*`), flagd and Chaos Mesh telemetry, original folder names. | A unit test checks every output for deny-listed attribute keys, original folder-name tokens and dropped services and finds none (not a free-text grep, [02 §6.1](02-architecture.md)). | Infralume | O-01 |
| FR-4 | Accept any subset of metrics, logs, traces and events, and record which are present. | Pipeline completes on each single-source variant of `synth-01`; `case_manifest.sources` is correct. | all engines | O-01, O-09 |
| FR-5 | Build typed signals: per-series values with `family` and `klass`, call edges, self-time, critical-path share. | Golden tests on `synth-01…05` and 3 real cases; outputs sorted and deterministic. | Signalyth | O-02 |
| FR-6 | Mine log templates deterministically. | Same templates across two runs and two laptops. | Signalyth | O-03 |
| FR-7 | Score anomalies per series with robust z (with scale floor), N-Sigma and change-point onset, in both directions; detect silence as an anomaly. | Golden tests; a series that drops to zero produces an `anomalies` row with `detector = silence`. | Anomara | O-04 |
| FR-8 | Estimate the incident onset `t_onset`, and provide `detect_alert(telemetry)`, which core's alert step calls under the detected-alert protocol to find the first entry-service SLO breach ([02 §5.1](02-architecture.md)). | Onset error on synthetic cases ≤ 1 time step. | Anomara | O-04 |
| FR-9 | Align clocks across sources; build the change timeline; score change-to-onset proximity and changed-versus-peer contrast. | `synth-04`'s change is found with proximity > 0.5. | Causync | O-06 |
| FR-10 | Build the dependency graph from traces, topology and log mentions with per-edge provenance; compute candidate propagation paths; expose a restricted conditional-independence test. | Graph matches the synthetic topology exactly. | Causalith | O-05 |
| FR-11 | Emit evidence atoms with stable IDs and provenance; provide the predicate library with fixed polarity and weight. | Same inputs give the same `atom_id`s; every predicate unit-tested on synthetic cases. | FaultLoom | R-06, R-08 |
| FR-12 | Evaluate every predicate a proposal cites for every candidate in the claim-pass pool (slate ∪ all proposed candidates; symmetric claim pass); reject predicates outside the library. | A claim on candidate A also yields a `claim_check` atom for every other claim-pass pool candidate; an unknown predicate is rejected as `unknown_predicate`. | FaultLoom | R-08 |
| FR-13 | Run six deterministic rankers, fuse them with gated RRF, assign mode, fault class and indicator, and output a top-K slate plus scores for all services. | Each ranker can be reported alone in `bench`; a ranker whose channel is missing abstains. | Causatrix | R-09 |
| FR-14 | Propose extra candidates, claims and trial requests with a local LLM in `brief` mode, constrained to closed enums of graph nodes, fault classes and library predicates; `investigate` mode as an ablation. | 100% of proposals validate against the schema; budget limits enforced. | Relentra | X-07, X-08 |
| FR-15 | Record every LLM call in a cassette and the agent trace as a hash chain; `ai.mode = replay` fails on any unrecorded call. | Replay of a recorded session is byte-identical; strict mode fails on a missing entry. | `veyltrace_llm`, Relentra | X-01, X-08 |
| FR-16 | Produce a verdict with `--ai off`: Relentra skipped, template card, verdict path unchanged. | `veyltrace diagnose --ai off` writes every artifact in [02 §4.1](02-architecture.md). | Causentra, Causivra | R-10, X-03 |
| FR-17 | Run trials T1–T10, each returning pass, fail or untestable with a reason. | Each trial unit-tested on a synthetic case where it must pass and one where it must fail. | Causentra | R-10, R-12 |
| FR-18 | Apply the fixed decision function over the decision pool; proposals can only add candidates (T10 is mandatory for proposal-origin candidates only); compute `verdict_hash`. | Determinism gate passes; with AI off the claim term is empty; rejected proposals carry a reason. | Causentra | R-10 |
| FR-19 | Output a split-conformal candidate set at α = 0.10 and a status of `CONFIRMED`, `LIKELY`, `INCONCLUSIVE` or `NO_FAULT`, with asks when inconclusive. | Calibration file `config/calibration/<family>.json` hashed into the run manifest; coverage measured per family, on held-out cases only ([03 §12.1](03-contracts.md); [ADR conformal-abstention](adr/20261030-ak-conformal-abstention.md)). | Causentra, bench | R-12, R-13 |
| FR-20 | Write an incident card whose prose cites evidence atoms and whose numbers and names are filled by code; fall back to a template after two checker failures. | The checker rejects seeded sentences with a raw number, an unknown entity or no citation. | Causivra | X-03, X-09 |
| FR-21 | Write a receipt (in-toto Statement v1) and replay it with `veyltrace replay`, using exit codes 0–6. | Replay reproduces `verdict_hash` on every recorded case; altered inputs give exit 3. | Causivra | X-09 |
| FR-22 | Score runs: AC@1/3/5, Avg@5, Retrieval@K, Rerank@1, chance floor, per system, with cluster bootstrap CIs; write per-case outputs. | Metrics unit-tested; `per_case.csv` (committed, [03 §13.2](03-contracts.md)) and `summary.json` written for every experiment. | bench | R-04, R-11, O-14 |
| FR-23 | Re-run BARO, N-Sigma and an alert-count baseline in the same harness. | Within ±5 points of published RCAEval numbers, or the discrepancy documented. | bench | R-05 |
| FR-24 | Drive robustness experiments: alert-time shift, telemetry ablation, decoy changes (RCAEval-C), planted decoy proposals. | Each runs from a committed experiment config; decoys reproducible from a seed. | bench, core (alert shift), Infralume | O-09, O-13, R-16 |
| FR-25 | Fit calibration only on calibration splits defined in [04](04-evaluation-protocol.md) and hash the result. | One calibration file per family; the hash appears in every run manifest that uses it. | bench | R-13 |
| FR-26 | Regenerate every paper table and figure from committed experiment configs. | `bench/results/tables/*.md` regenerate identically. | bench | R-16, R-17 |
| FR-27 | Provide a CLI: `diagnose`, `replay`, `bench`, `data`. | Commands in [AGENTS.md §6](../AGENTS.md) run on a clean clone. | core | R-02 |
| FR-28 | Serve an HTTP API with OpenAPI-generated TypeScript types. | Contract tests pass; CI fails on type drift. | gateway | X-04 |
| FR-29 | Show case list, verdict, candidate set, evidence table, propagation graph, timeline and receipt in the console. | Renders synthetic and RE2 runs. | console | X-05, X-10 |
| FR-30 | Live mode: receive OTLP, buffer, snapshot the window on an SLO breach or "Diagnose now", and run the offline pipeline on the snapshot. | Injected fault on Online Boutique → AI-off verdict on screen in ≤ 5 min; the live verdict replays. | gateway, console, lab | X-10 |
| FR-31 | Expose `diagnose`, `verify_hypothesis` and `get_receipt` over MCP. | Callable from Claude Code and Codex. | gateway | X-12 (cut 4th) |
| FR-32 | Run a laptop fault lab: Online Boutique on kind with Chaos Mesh, at least 8 fault types, load generator, capture packager with separate answer keys and a validation rule. | 8 fault types captured once each; validated-case count posted daily. | lab | X-02, X-06, X-11 |
| FR-33 | Package VeylLab as Parquet plus answer keys plus a Croissant metadata draft. | Ships in v1.0 if ≥ 120 validated cases, else v1.1. | lab | X-14 |
| FR-34 | Generate synthetic cases `synth-01…05` (CPU hog, delay, error injection, change-induced regression, no fault) with answer keys. | Two runs give identical hashes. | core | R-03 |

## 8. Non-functional requirements

| ID | Requirement | Measure or target | Source | Verified by |
|---|---|---|---|---|
| NFR-1 | **Determinism.** Engines 1–7, 9 and the deterministic parts of 10 are pure functions of declared inputs and config. | Two runs on `synth-01` and one real case give identical output hashes. | [02 §9](02-architecture.md) | CI `determinism` job (L-03) |
| NFR-2 | **Replay.** Tier 1: a verdict re-runs from its receipt and cassette to the same `verdict_hash` on any team laptop. Tier 2 (re-generating identical LLM text) is best effort and only measured. | 100% of recorded cases (M3). | [02 §5.2, §6.10](02-architecture.md); [ADR local-first-llm](adr/20261030-ak-local-first-llm.md) | `veyltrace replay`; X-09 |
| NFR-3 | **Latency.** | Deterministic path ≤ 30 s per RE2 case, excluding first-time Parquet conversion; AI path adds ≤ 180 s for Relentra plus ≤ 60 s for Causivra's narration on CPU; live injection-to-verdict ≤ 5 min with `--ai off`. | [02 §9](02-architecture.md); [07 M3](07-roadmap.md) | O-11 on the slowest laptop; R-16 reports p50 and p95 |
| NFR-4 | **Memory.** | ≤ 3 GB peak RSS per RE2 case on the deterministic path. | [02 §9](02-architecture.md) | O-11; `peak_rss_mb` in `per_case.csv` |
| NFR-5 | **Laptop-only.** Runs on a 16 GB Windows 11 laptop with Docker Desktop on WSL2, CPU-only, with no cloud account. | The lab needs the WSL2 VM raised from its 8 GB default to 11–12 GB (*estimate*). OTel Demo and Online Boutique never run together on one laptop. | [benchmarks_and_testbed §Q3][bt]; [02 §10](02-architecture.md) | L-01 benchmark per laptop in `docs/team/<initials>.md` |
| NFR-6 | **Privacy: no data leaves the laptop by default.** | `veyltrace_llm` talks to `localhost` only unless `VEYLTRACE_ALLOW_REMOTE_LLM=1`; engines 1–7 and 9 import no LLM, HTTP or socket library; no telemetry or usage reporting. | [02 §9](02-architecture.md) | `tests/test_isolation.py` (CI `isolation`) |
| NFR-7 | **No ground-truth leakage.** | Engines see only opaque `case_id`s; answer keys are read only in `bench/` and `lab/`; deny-list scrub test passes. | [02 §2 P7](02-architecture.md) | FR-3 test; isolation scan |
| NFR-8 | **Missing telemetry degrades honestly.** | A missing source makes rankers abstain and trials `untestable`, pushing the status toward `INCONCLUSIVE` with an ask; never a crash. | [02 §9](02-architecture.md) | Telemetry-ablation experiment (O-09, R-16) |
| NFR-9 | **Licence.** Code is Apache-2.0. Dependencies must allow redistribution under Apache-2.0. | Do not vendor RCAEval's bundled CausalRCA or RUN (no licence). Do not use non-commercial weights (Moirai 2.0, TimesFM 3.0) in any default path. VeylLab data released as CC BY 4.0 (*target*). Avoid redistributing k6 (AGPL-3.0). | [sota_methods §Q5][sota]; [novel_building_blocks §Q1][nb]; [benchmarks_and_testbed §Q4][bt] | Dependency review in `chore(deps)` PRs |
| NFR-10 | **Accessible console.** | *Target:* WCAG 2.1 AA for the verdict, candidate-set, evidence and receipt views: fully keyboard-operable; status always shown as text, never by colour alone; text contrast meets AA; every chart and graph has a table or list equivalent (evidence table, timeline list); motion respects reduced-motion settings. | a priori | Checklist in the console PR template; details owned by [06-gateway-and-console](06-gateway-and-console.md) |
| NFR-11 | **Portability.** | Python 3.12; Windows 11 laptops for development and the lab; `ubuntu-latest` for CI; LF line endings. | [02 §8](02-architecture.md); `.gitattributes` | CI; weekly determinism run on one Windows laptop (see [12-risks](12-risks.md) RK-15) |
| NFR-12 | **Maintainability.** | Types everywhere (pyright strict in engines); unit, golden and property tests; PRs ≤ 400 changed lines excluding fixtures and generated code. | [AGENTS.md §3, §5](../AGENTS.md) | CI `lint`, `types`, `tests` |
| NFR-13 | **Result provenance.** | Every reported number comes from `bench/results/` produced by a committed config at a clean commit; dirty runs are never used for paper tables. | [AGENTS.md §4.8](../AGENTS.md); [03 §12](03-contracts.md) | `run_manifest.code.dirty`; R-17 |
| NFR-14 | **Safe public repository.** | No secrets, datasets, `.parquet`/`.duckdb` files, model weights or `runs/` output committed; LLM tools are read-only; no write actions on the cluster. | [AGENTS.md §4.6](../AGENTS.md); [02 §6.8, §11](02-architecture.md) | `.gitignore`; review; see [12-risks](12-risks.md) RK-17 |
| NFR-15 | **Grounded explanations.** | Every card sentence cites at least one atom; every number and entity name in prose is filled by code. | [02 §6.10](02-architecture.md) | Claim-checker tests (X-09) |

## 9. Success criteria for v1.0

Each criterion is tied to a milestone in [07 §1](07-roadmap.md) and to a research question in [04](04-evaluation-protocol.md). Values are **targets**. A target that is missed is reported as missed, not tuned away on test data.

**Statistical ground rules.** RE2 has 270 cases (90 per system); RE3 has 90 (30 per system). A pre-registered RCAEval study (Research Square preprint, not peer-reviewed) estimated that, with about 30% discordant cases, the minimum detectable difference in AC@1 at p < 0.05 is about 7 points on 270 cases, 10 points after Holm correction over 13 comparisons, and 14 points on 90 cases ([benchmarks_and_testbed §Q2][bt]). Each RE2 system has only 30 clusters of (system, root service, fault), so the clustered per-system threshold is likely larger than 14 points (*estimate*). Therefore:

- comparisons use the paired difference on the same cases with a cluster-bootstrap CI, not the overlap of two separate CIs (overlap is a stricter and less informative test);
- per-system superiority is claimed only where the paired CI excludes zero; smaller differences are reported as "not detected", not as "no difference";
- reported baselines leave little headroom on some systems: the pre-registered study measured N-Sigma at 0.80 AC@1 on RE2 ([benchmarks_and_testbed §Q2][bt]).

| ID | Milestone | Criterion (target) | RQ |
|---|---|---|---|
| SC-1 | M2 (15 Nov) | `--ai off` produces a schema-valid verdict on 100% of RE2 cases, each ≤ 30 s and ≤ 3 GB peak RSS on the slowest team laptop. | RQ5 |
| SC-2 | M1–M2 | BARO, N-Sigma and the alert-count baseline reproduce within ±5 points of published RCAEval numbers, or the discrepancy is written up (R-05). | RQ1 |
| SC-3 | M2, final at M4 | **Accuracy.** (a) *Required:* on no RE2 system is Veyltrace AI-off significantly worse in AC@1 than the best reproduced simple baseline (paired cluster-bootstrap 95% CI of the difference not entirely below zero). (b) *Aim:* pooled over RE2, the paired difference versus the best reproduced baseline is positive with a 95% CI excluding zero after Holm correction. (c) *Stretch:* a significant per-system gain on at least 2 of 3 RE2 systems, which needs gains of roughly 14 points or more. (d) Retrieval@5 ≥ 0.90 on each RE2 system; any change to K is decided on RE1 or calibration splits only. DecompRCA reports 98–100% retrieval at K = 15 on RE1 ([sota_methods §Q1][sota]). | RQ1 |
| SC-4 | M3, final at M4 | **Calibration.** At α = 0.10: empirical coverage of the conformal set on held-out test cases ≥ 0.85 for each calibration family (allows about 1.6 binomial standard errors at n = 90, *estimate*; R-12's acceptance on RE2 is held-out coverage within 1 − α ± 0.05); mean set size ≤ 3 (PRISM's 0.91 Top-3 on 735 cases suggests about 3 candidates for 90% coverage, [report][rep]); on held-out normal windows `NO_FAULT` is returned ≥ 85% of the time (false alarms ≤ β + 0.05, β = 0.10); on fault cases a wrong `NO_FAULT` occurs ≤ 5% of the time. Leave-one-system-out coverage is reported with no target. | RQ3 |
| SC-5 | M3, final at M4 | **Proposer.** Proposer lift (verified AC@1 with AI on minus AI off) on RE2 is reported over 3 seeds with a CI; no positive-lift target, because we found no published result for a ≤ 10B model as the investigating RCA agent (ThinkFL's model size is unconfirmed) and a zero lift is still a finding. Guard: the lift's CI is not entirely below zero. Planted decoy proposals change the top-1 in ≤ 5% of cases (models chose a planted decoy first in 21–42% of flagged cases, [benchmarks_and_testbed §Q2][bt]). The verdict is identical under any permutation of the proposals (100%). | RQ2 |
| SC-6 | M3 | **Replay.** `veyltrace replay` reproduces `verdict_hash` on 100% of recorded cases on a second laptop and in CI. Tier-2 regeneration match rate is reported with no target. | RQ6 |
| SC-7 | M4 | **Robustness.** With alert-time shifts of ±60 and ±120 s, AC@1 drops by ≤ 10 points per RE2 system (N-Sigma dropped from 0.80 to 0.07 at +2 min, [benchmarks_and_testbed §Q2][bt]). In every telemetry-ablation cell, at least 90% of `CONFIRMED` verdicts are correct. In RCAEval-C, decoy changes alone (no true change) cost ≤ 5 points of AC@1 compared with no change events. | RQ4 |
| SC-8 | M4 | **Cost.** p50 and p95 wall time, peak RSS and LLM tokens per case reported for the deterministic and AI paths, with each laptop's hardware spec. | RQ5 |
| SC-9 | M3 (22 Nov) | **Demo.** A fault injected into Online Boutique on a team laptop produces a verdict on screen in ≤ 5 min with `--ai off`, and that live verdict replays. The AI-on result follows on the split or cassette demo ([02 §10](02-architecture.md)). | — |
| SC-10 | M4 (29 Nov) | Every table and figure in the paper plan regenerates from committed experiment configs; paper draft v1 complete; no open P0/P1 bugs. | all |
| SC-11 | M5 (1 Dec) | `v1.0.0` tagged; Zenodo DOI minted; `CITATION.cff` updated with the DOI; `REPRODUCE.md` verified on a clean clone by a teammate who did not write it; demo video in release assets. | — |
| SC-12 | M5 (conditional) | VeylLab ships in v1.0 if ≥ 120 validated cases exist, otherwise in v1.1 ([02 §12](02-architecture.md); [07 §6](07-roadmap.md)). | — |

The "never cut" list in [07 §1.1](07-roadmap.md) defines the minimum v1.0: RE2 AI-off pipeline, trials T1–T4, conformal set and abstention, replay, Relentra `brief`, console verdict view, live demo on Online Boutique. SC-1, SC-3(a), SC-4, SC-6 and SC-9 cover it.

## 10. Constraints and assumptions

### 10.1 Constraints

| Constraint | Detail |
|---|---|
| Time | One month: Sat 31 Oct – Tue 1 Dec 2026 ([07](07-roadmap.md)). |
| People | Three students (RV University, Bengaluru), one lane each, each with a different AI coding agent ([08 §2](08-collaboration-and-git.md)). |
| Hardware | 16 GB Windows laptops. WSL2 gives its VM 50% of Windows RAM by default ([benchmarks_and_testbed §Q3][bt]). No GPU assumed. |
| No cloud (for now) | No cloud services in the build or demo; any remote LLM is opt-in. Cloud is post-v1.0 ([02 §10](02-architecture.md)). |
| Public repository | `github.com/DuhItzAniket/Veyltrace` is public: standard Actions runners are free, Zenodo can archive it, and merge queue is unavailable on a personal-account repo ([multi_agent_dev §Q3–Q5][md]). |
| Licence | Apache-2.0 for code ([LICENSE](../LICENSE)). |
| Determinism and isolation | No AI or network in the decision path; frozen contracts after M1 ([AGENTS.md](../AGENTS.md)). |
| arXiv | Since 21 Jan 2026, first-time submitters without a prior accepted paper in the domain need a personal endorsement ([multi_agent_dev §Q5][md]). |

### 10.2 Assumptions (to verify)

| Assumption | Why it matters | Verified when / how | If false |
|---|---|---|---|
| RCAEval's Hugging Face Parquet copy (~3.4 GB) stays available under MIT ([sota_methods §Q5][sota]) | Primary benchmark | O-01 (`veyltrace data fetch rcaeval`) | Use the Zenodo zips (~5.2 GB, ~38 GB extracted) on one laptop; see [12-risks](12-risks.md) RK-05 |
| `sch_netem` loads under Docker Desktop's WSL2 kernel; Chaos Mesh works in kind on Windows (both unverified, [benchmarks_and_testbed §Q3][bt]) | Network faults in the lab | X-02 smoke test in week 1 | In-container `tc`, Toxiproxy, or restrict the lab to CPU, memory and flag faults; risk RK-03 |
| Qwen3.5-9B Q4 runs fast enough on team CPUs for `brief` mode within 180 s per case (CPU speeds are *estimates* of 3–15 tokens/s, [verified_agents §Q4][va]) | AI arm feasibility | L-01 `llama-bench` per laptop | Qwen3.5-4B, split demo, cassette demo, subset evaluation; risk RK-02 |
| Cases within one calibration family are close enough to exchangeable for split conformal | Coverage guarantee | R-13; LOSO reported | Claim only empirical coverage; risk RK-07 |
| No-fault windows can be built from RCAEval pre-injection data, `synth-05` and VeylLab no-fault captures | `NO_FAULT` threshold | R-13 | Report `NO_FAULT` on lab data only; risk RK-24 |
| FSE'26 TrainTicket set has usable size, format and licence (all unverified, [benchmarks_and_testbed §Q1][bt]) | Hard benchmark | M1 review (R-07) | Drop to stretch ([02 §12](02-architecture.md)) |
| Each teammate has about 20–25 focused days in the month | Roadmap load ([07](07-roadmap.md) estimates sum to 24.5 / 20 / 23.5 person-days for Reason / Observe / Explain, plus 2 shared; [08 §2](08-collaboration-and-git.md)) | Kickoff | Cut list ([07 §1.1](07-roadmap.md)); risk RK-19 |

## 11. Stakeholders

| Stakeholder | Interest | Role in the project |
|---|---|---|
| Aniket Kumar (lead, Reason lane) | Architecture, decision engine, evaluation, paper | Owns shared docs, contracts, CI, `bench/`, `paper/`; final say on ADRs and CCRs |
| Annapurna S (Observe lane) | Ingest, signals, anomalies, change and graph engines | Owns engines 1–5 and their docs |
| C Lakshanaa (Explain lane) | LLM proposer, card and receipt, gateway, console, lab | Owns engines 8 and 10, `packages/{llm,gateway}`, `console/`, `lab/` |
| Faculty advisor / arXiv endorser (to identify) | Supervision, endorsement, possible co-authorship | See [11 §7](11-research-paper-plan.md) |
| On-call SREs and platform teams | A diagnosis they can check | Target users; feedback on demo and card |
| RCA researchers | Reproducible harness, per-case outputs, dataset | Users of `bench/` and VeylLab |
| AI SRE agent builders | A verification tool | Users of the MCP interface |
| Reviewers and artifact evaluators | Claims backed by artifacts | Audience for [11](11-research-paper-plan.md) |
| Upstream projects (RCAEval, Nezha, Online Boutique, OTel Demo, Chaos Mesh, Qwen) | Correct attribution and licence compliance | Cited and credited |

## 12. Glossary

All terms (AC@k, atom, slate, pool, claim pass, receipt, cassette, q̂, NO_FAULT, klass, lane, CCR, and the ten engine names) are defined in [13-glossary](13-glossary.md).

[rep]: ../reports/Veyltrace%20v2%20SOTA%20root%20cause%20analysis.md
[sota]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/sota_methods_2026.md
[bt]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md
[va]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/verified_agents_local_llms.md
[nb]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/novel_building_blocks.md
[sm]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/stack_and_market.md
[md]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/multi_agent_dev_and_sdlc.md
