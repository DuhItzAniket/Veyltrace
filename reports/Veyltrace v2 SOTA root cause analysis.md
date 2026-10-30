# Let Agents Propose, Let Verifiers Decide

Veyltrace v2 should have three layers. A recall-first deterministic pipeline gathers evidence. ML models and a local LLM may only *add* hypotheses and fetch evidence. A deterministic verifier then recomputes every claim from a hashed telemetry snapshot and makes the call: it emits a calibrated candidate set or abstains, and it seals a verdict that replays byte for byte from a recorded "cassette". The 2026 evidence makes this design timely. With frontier cloud models, simple LLM harnesses now reach **72–89% Top-1 on a 90-case cross-benchmark, against 38.9% for the best non-LLM method**. Yet stricter tasks expose the limits:

- exact root-cause sets are recovered only **20.7%** of the time;
- realistic on-call tasks top out at **25.3%**;
- live agents fall from **63.7% to 17.9%** on failures they have not seen before;
- one planted false sentence makes models name a decoy first in **21–42%** of cases.

No paper shows a model of 10B parameters or fewer working as an RCA agent. On a 16 GB laptop, the verifier is therefore what lets an unproven model contribute without being trusted. Ranked by evidence per hour of work, the most publishable contributions are:

1. the propose–verify architecture itself, with replayable receipts and measured *proposer lift* and *decoy rejection*;
2. the first calibrated, abstaining RCA output;
3. a decomposed, onset-robust, per-system evaluation that releases per-case outputs;
4. a change-aware evidence channel stress-tested with decoy changes.

A laptop-collected labelled dataset belongs in a second paper, not on the critical path for month one. The stack that fits is one OpenTelemetry Collector feeding a FastAPI receiver, Parquet plus DuckDB, Online Boutique on kind with Chaos Mesh, the OpenTelemetry Demo on Docker Compose, and Qwen3.5-9B at 4-bit through llama.cpp. Every hyperscaler now sells a metered AI SRE agent whose accuracy claims nobody has audited, so the open market gap is an auditable evidence-and-verification engine that those agents can call. With three different coding agents on one repo, enforced structure prevents conflicts better than goodwill: PRs from two different agents that are open at the same time conflict **41.7%** of the time. Finally, the main 2027 ICSE, FSE and KDD cycle-1 research deadlines have passed. The month should therefore end in an arXiv preprint plus a DOI-archived artifact, aimed at ISSRE 2027, KDD 2027 cycle 2, the FSE 2027 Industry track or NeurIPS 2027 Evaluations & Datasets.

## Frontier agents reach 89% Top-1 while grounded diagnosis stalls near 21%

### Statistical methods still beat graphs, and the open problem moved to re-ranking

No graph-based or causal method published in 2026 beat the statistical leaders. The sharpest evidence is DecompRCA, a NeurIPS 2026 Evaluations & Datasets paper co-authored by the RCAEval and PRISM author Luan Pham. It splits Top-k accuracy into two separate failures:

- **retrieval failure**: the true cause never enters the candidate list;
- **re-ranking failure**: the true cause is a candidate but ranked too low.

On RCAEval's microservice suites, simply sorting services by deviation puts the true cause in the **top 15 for 98–100% of faults**. On complex-fault benchmarks, statistical baselines rank it wrongly **79–100%** of the time, and no graph-based method clearly outperformed the strongest statistical baseline ([DecompRCA](https://arxiv.org/abs/2609.36686); [GitHub](https://github.com/cruiseresearchgroup/DecompRCA)). In short, finding candidates is nearly solved on RCAEval; ranking them is not. The single-dataset leader remains PRISM: **0.68 Top-1, 0.91 Top-3 and 0.87 Avg@5 over all 735 RCAEval cases at about 8 ms per case**. It is a preprint without released code ([PRISM](https://arxiv.org/html/2601.21359)).

Pooled across datasets, the picture is humbler. RCAtlas (an October 2026 preprint) pools 90 validated cases from eight public datasets and runs every classical method in one harness. NSigma leads at **38.9% PR@1**, followed by TORAI and SimpleRCA at 33.3%, BARO at 22.2%, CIRCA at 17.8%, RCD at 5.9% and random at 5.5%. On the five ITBench cases, every one of these methods scores zero. The authors also found that NSigma and BARO score only *upward* deviations, so a root-cause service whose traffic *drops* ranks last ([RCAtlas](https://arxiv.org/html/2610.35767)).

On a harder benchmark, the FSE 2026 propagation-aware Train Ticket set (1,430 validated cases), 11 re-evaluated methods average **0.21 Top@1**, and the best reaches 0.37 ([Fang et al.](https://arxiv.org/abs/2510.04711)).

Causal-graph numbers mostly measure the evaluation harness, not the method. CIRCA's AC@1 on (probably) RCAEval's RE2 Online Boutique suite is **0.67 in GALA+'s harness**, against far lower values elsewhere. RCAEval's September 2026 changelog fixed a bug in which CIRCA and the PageRank-based methods silently ranked by column order instead of by score ([GALA+](https://arxiv.org/html/2608.08968v1); [RCAEval README](https://github.com/phamquiluan/RCAEval)). Full causal discovery is no better: learned graphs reach F1 of only **0.1–0.54**, PCMCI at most 0.12, and CIRCA needs 3,792 s for one Train Ticket case ([ASE'24 study](https://arxiv.org/html/2408.13729v1)).

### Simple LLM harnesses overtook hand-crafted agents

The biggest change since the earlier Veyltrace research concerns LLMs. Its claim that LLM agents solve "about one incident in nine" is now **outdated for finding the faulty service**, though still roughly right for full, grounded diagnosis. On RCAtlas, plain harnesses with 2026 frontier models clearly beat every published, hand-crafted RCA agent:

| Approach (RCAtlas, 90 cases) | Mean PR@1 |
|---|---|
| Codex CLI coding harness | **77.2%** |
| SQL ReAct loop over DuckDB | 72.8% |
| One-shot call over an evidence package (no tools) | 65.3% |
| Flow-of-Action (published agent) | 53.3% |
| RCAgent (published agent) | 49.3% |
| mABC (published agent) | 15.6% |
| NSigma (best non-LLM method) | 38.9% |

Cost and speed are modest: the best single run reached **88.9% at about USD 0.26 and 277 s per case**, and the weakest model with Codex reached 68.9% for under one cent ([RCAtlas](https://arxiv.org/html/2610.35767)). Its failure analysis is a checklist for a verifier:

- **Flow-of-Action** declared a wrong root cause "found" after one round.
- **mABC** missed services that *stopped receiving calls*.
- **RCA-Agent's executor** discarded tool outputs over 16,384 tokens.
- **Node-level faults**: agents named the right node in 85–90% of runs but blamed a pod or service on it.

A 5,000-trajectory study on RCABench agrees. Claude Code scored **79.6 Acc@1** on a Qwen backbone and ThinkDepth.ai with Claude Sonnet 4.6 reached 90.0, while mABC scored 42.6 ([trajectory study](https://arxiv.org/html/2608.21310)).

### Stricter metrics collapse those numbers

Stricter tasks expose the limits. OpenRCA 2.0 (500 instances, 11 frontier models) asks for the *exact* set of root causes:

- exact-set accuracy averages **20.7%** (best 29.4%);
- naming at least one correct service averages 76.0%;
- Edge F1 on the propagation path trails Node F1, at **43.4% against 62.2%** ([OpenRCA 2.0](https://arxiv.org/html/2606.27154v2)).

Other benchmarks agree:

- **ORCA-bench** (realistic on-call reports over 50 GB of telemetry): best accuracy **25.3% on medium tasks and 10.0% on hard ones**. Removing source-code access hurts every model ([ORCA-bench](https://arxiv.org/abs/2607.28545)).
- **SREGym**: Claude Code diagnoses 72.6% of live problems. Stratus with Sonnet falls from **63.7% end-to-end on problems ported from older benchmarks to 17.9%** on SREGym-only failures. Agents also "mitigate" without a correct diagnosis 35–59% of the time ([SREGym](https://arxiv.org/html/2605.07161v1)).
- **ITBench-AA**: pass rates stay below 42% ([Artificial Analysis](https://artificialanalysis.ai/evaluations/itbench-aa)).
- **OpenRCA 1.0**: a predictor that reads no telemetry scores 7.46% against the agent's 11.34% (p = 0.06) ([OpenRCA issue #23](https://github.com/microsoft/OpenRCA/issues/23)).

A pre-registered Research Square preprint adds the most uncomfortable results ([Hussain & Farrukh](https://doi.org/10.21203/rs.3.rs-11401166/v1)):

- shifting the assumed fault onset just **two minutes late drops N-Sigma from 0.80 to 0.07 AC@1** and the authors' LLM pipeline from 0.87 to 0.27;
- in their RE2 runs, the LLM agent (0.44) trailed both its own detector count (0.60) and N-Sigma (0.80);
- **the evidence shown accounted for +0.30 and the prompt wording for only +0.05**;
- one false "NOTE" sentence made models name a decoy first in **21–42%** of flagged cases.

"State of the art" in 2026 therefore depends on the metric, the harness and whether the true onset time is handed to the method.

### Hybrids win when the deterministic stage is tuned for recall

The best-documented hybrid pattern is *deterministic candidate generation or evidence extraction, then an LLM that re-ranks or verifies compact evidence*:

| Hybrid | Design | Result |
|---|---|---|
| **GALA+** (ASE'26) | Statistical prior + LLM agent limited to the service graph | **74.44 / 73.33 AC@1** on its two benchmarks (inferred to be RCAEval RE2-OB/TT), vs 66.67 for the best non-LLM baseline in its harness; USD 0.003–0.26 per incident; code not released ([GALA+](https://arxiv.org/html/2608.08968v1)) |
| **DecompRCA** | One listwise LLM re-ranking call | Beats the best of nine baselines by **+7 to +18 points** when given a short system description ([DecompRCA](https://arxiv.org/abs/2609.36686)) |
| **EviRCA** | LLM sees only deterministic "evidence cards" | **40.6–43.9% on OpenRCA**, vs at most 15.2% for prior baselines, using 15–26× fewer tokens ([EviRCA](https://arxiv.org/abs/2609.19825)) |
| **KRCA** (Kuaishou) | Skeleton causal graph + LLM that verifies | **0.88 AC@1** for the service and 0.79 for fault type, in production ([KRCA](https://arxiv.org/abs/2607.01788)) |
| **SpecRCA** (ICSE-NIER'26) | Non-LLM drafter + distilled 3B Llama verifier | **R@1 61.34 at 9.89 s per query**, vs mABC's 34.19 at 83.17 s; one dataset, results labelled preliminary ([SpecRCA](https://arxiv.org/html/2601.02736)) |

The counter-evidence also comes from RCAtlas. DecompRCA's candidate pool contained the true cause in only **57.8%** of cross-benchmark cases, which capped it at 28.5% PR@1, below a one-shot LLM ([RCAtlas](https://arxiv.org/html/2610.35767)). A hybrid's deterministic first stage must be tuned for recall, or it caps the whole system.

| Family | Best 2026 result | Benchmark and metric | Cost per case | Status |
|---|---|---|---|---|
| Statistical | PRISM 0.68 / 0.87 | RCAEval 735 cases, Top-1 / Avg@5 | ~8 ms | Preprint, no code |
| Statistical, cross-benchmark | NSigma 38.9% | RCAtlas 90 cases, PR@1 | ~0.01 s | Preprint |
| Statistical + causal | TORAI 0.77 Top-1 (Train Ticket) | RE2-derived | 13–21 s | FSE'26 |
| Causal graph | CIRCA 17.8%, RCD 5.9% | RCAtlas, PR@1 | seconds to over 1 h | Harness-sensitive |
| Any method, hard data | mean 0.21, best 0.37 Top@1 | FSE'26 Train Ticket, 1,430 cases | seconds to hours | FSE'26 |
| Frontier agent, simple harness | 77.2% mean, 88.9% best | RCAtlas, PR@1 | USD 0.01–0.26; 45–277 s | Preprint |
| Frontier agents, exact cause set | 20.7% mean | OpenRCA 2.0, 500 cases | not reported | Preprint |
| Frontier agents, on-call tasks | 25.3% medium / 10.0% hard | ORCA-bench, 1,079 tasks | not reported | Preprint |
| Hybrid | GALA+ 74.44 / 73.33 AC@1 | probably RE2-OB / RE2-TT | USD 0.003–0.26; ~53–63 s | ASE'26 |
| Hybrid, industrial | KRCA 0.88 AC@1 | Kuaishou production | 77.3% less diagnosis time | Preprint |

Sources: as cited in the text above. DeltaRCA (ASE'26) reports 63% Top-1 by having an LLM read code changes before trace localization; that figure is from a search summary and is unverified ([DOI](https://doi.org/10.1145/3832783.3837424)).

### None of the strong agent results transfers to a laptop yet

Every strong agent result above uses a frontier model behind a cloud API. Weaker models lose 10–20 points on RCAtlas. In the trajectory study, the Qwen backbone acted on the previous round's result in only **24.9% of rounds, against 54.3% for Sonnet**, and consumed about 1.74M tokens per case ([trajectory study](https://arxiv.org/html/2608.21310)). The closest open-weight data point, Kimi K2.5 on SREGym, diagnosed 41.3% of problems and took 674 s to do so ([SREGym](https://arxiv.org/html/2605.07161v1)). **No 2024–2026 paper evaluates a model of 10B parameters or fewer as the investigating RCA agent.** The only small-model success is SpecRCA's fine-tuned 3B *verifier*. That gap is exactly why Veyltrace's verifier must decide and its local model must only propose.

## Verification, calibration and honest measurement are the open ground

### Four contributions survive a month on laptops

Ranked by evidence, novelty and cost, the candidate contributions are:

| Rank | Contribution | Evidence it matters | Novelty status | Build cost (estimate) | Main risk |
|---|---|---|---|---|---|
| 1 | **Propose–verify RCA.** A deterministic, predicate-based verifier over ML and LLM proposals, with replayable receipts. Report *proposer lift*, *decoy rejection* and abstention | LLM-based verifiers add 3.5–35.1 pp ([DiagGuard](https://arxiv.org/html/2608.21310)); a 3B verifier nearly doubles R@1 ([SpecRCA](https://arxiv.org/html/2601.02736)); one false sentence steers models to decoys 21–42% of the time | No paper isolates a *purely deterministic* verifier | ~2 person-weeks | Strict predicates abstain too often, especially on network faults |
| 2 | **Conformal candidate sets** with a "no fault" option, risk–coverage curves and AURC | Every PetShop method names false root causes during normal operation ([PetShop](https://arxiv.org/html/2311.04806v2)); RCAtlas scores abstention as wrong | No RCA application found (absence in searches, not proof) | 2–3 days, ~50 lines of code | Calibration assumes cases are exchangeable, which breaks across systems; small strata |
| 3 | **Decomposed, onset-robust, per-system evaluation** that releases per-case outputs | **0 of 23 RCA papers release per-case outputs** ([Hu et al.](https://arxiv.org/abs/2606.29159)); onset shift takes N-Sigma from 0.80 to 0.07 | Tools exist (RCAEval flags) but are rarely reported together | 3–4 days plus overnight runs | Reviewers call it "just evaluation" unless it is paired with #1–#2 |
| 4 | **Change-event channel + decoy-change stress test** ("RCAEval-C"), backed by real changes in the live testbed | Binary and config pushes triggered **68%** of Google's outages ([SRE workbook](https://sre.google/workbook/postmortem-analysis/)); Gandalf reaches 92–95% precision ([NSDI'20](https://www.usenix.org/conference/nsdi20/presentation/li)); Meta's changed-vs-control cohort checks cut false positives from 12.1% to 2.7% ([Meta SHC](https://arxiv.org/html/2608.20513)) | No public microservice RCA benchmark carries change events | 4–5 days | Synthetic change logs, so live cases are needed as backup |
| 5 | **Laptop-collected labelled dataset** (~300 validated cases) | The FSE'26 benchmark kept 1,430 of 9,152 injections ([Fang et al.](https://arxiv.org/abs/2510.04711)); RCAEval's injection parameters were never published | Fills a reproducibility gap | ~1 week of scripting + ~6 nights of runs | Unknown laptop acceptance rate |
| 6 | **IDI-style interventional trials** as a verifier predicate | IDI beats nine baselines on synthetic data and PetShop ([ICLR'25](https://arxiv.org/abs/2505.00930)) | Untested on RCAEval | ~4 days | Wrong call-graph edges; network faults |
| 7 | **Local proposer study** (≤10B model) plus a measured re-generation determinism rate | Weaker models lose 10–20 points; no ≤10B study exists | No precedent | ~1 week + ~20 h of CPU | Lift may be zero, which is still reportable |
| 8 | **Recall-first retriever fixes**: two-sided deviation, critical-path-weighted SBFL (spectrum-based fault localization), a network mode | One-sided scorers rank traffic drops last ([RCAtlas](https://arxiv.org/html/2610.35767)); the TWIST trace score lifted BARO AC@1 from 14.4% to 36.7% ([GALA](https://arxiv.org/html/2508.12472v1)) | Incremental | ~1 week | Missing parent span IDs; asynchronous calls |
| 9 | **Time-series foundation model (TSFM) residual-scoring ablation** | Zero-shot TSFMs tie classical detectors (VUS-PR 0.319 vs 0.332–0.353) ([TSB-AD study](https://arxiv.org/html/2601.00446)) | No RCA study | 3–4 days | Probably no gain |

The coherent paper is #1 + #2 + #3. The working title is "propose freely, decide deterministically: verifiable and calibrated microservice RCA on a laptop". Add #4 as a section if week 3 allows. #8 is engineering the system needs anyway, because the verifier can only confirm candidates the retriever finds. #6 and #7 are strong ablations. The dataset (#5) is better as its own NeurIPS Evaluations & Datasets or data-track paper. That venue has precedent: DecompRCA, an RCA evaluation paper, was accepted at NeurIPS 2026 E&D.

The research is equally clear about what not to build:

- **Graph neural networks over traces**: no public head-to-head shows them beating simple statistics.
- **Full causal discovery over thousands of series**: F1 of 0.1–0.54, and most pipelines perform like random.
- **mABC-style multi-agent voting**: last or near last in both independent re-runs.
- **Monte Carlo tree search agents in the live demo**: LATS-RCA reached **91.3% on LO2** but cost 9.1 minutes and 156K tokens per investigation ([LATS-RCA](https://arxiv.org/html/2605.03505)).
- **Any LLM-as-judge used as a stop or decision condition.**

### Vendors sell metered agents with unaudited 90–95% claims

By October 2026, every hyperscaler and major observability vendor ships an AI SRE agent:

| Product | Status in 2026 | Pricing |
|---|---|---|
| **AWS DevOps Agent** | GA 31 Mar 2026 | **USD 0.0083 per agent-second** (≈USD 29.88 per agent-hour); ten 8-minute investigations a month cost USD 39.84 ([AWS pricing](https://aws.amazon.com/devops-agent/pricing/)) |
| **Azure SRE Agent** | GA plus a 30-day trial, per a 26 Aug 2026 update ([AZ569760](https://mc.merill.net/message/AZ569760)) | Azure Agent Units; no dollar price per unit found |
| **Grafana Assistant Investigations** | GA 29 Jul 2026 ([Grafana](https://grafana.com/whats-new/2026-07-29-assistant-investigations-is-now-generally-available-in-grafana-cloud/)) | Metered in tokens since 1 Oct 2026 ([Grafana pricing](https://grafana.com/docs/grafana-cloud/platform/pricing-and-usage/assistant/)) |
| **Dynatrace Intelligence** | Launched Jan 2026; combines deterministic causal RCA with agentic AI ([Dynatrace](https://www.dynatrace.com/news/press-release/dynatrace-intelligence-redefines-observability/)) | Closed platform |
| **Datadog Bits AI SRE** | Claims higher accuracy on internal benchmarks, with no figures ([Datadog](https://datadoghq.com/blog/bits-ai-sre-deeper-reasoning)) | AI credits |
| **Resolve AI** (startup) | **USD 1B valuation** ([TechCrunch](https://techcrunch.com/2026/02/04/ai-sre-resolve-ai-confirms-125m-raise-unicorn-valuation/)) | Closed |
| **HolmesGPT** (open source) | CNCF Sandbox, Apache-2.0 | Free; publishes no accuracy results ([CNCF](https://www.cncf.io/blog/2026/01/07/holmesgpt-agentic-troubleshooting-built-for-the-cloud-native-era/)) |
| **Coroot** | Sends ~9.8K tokens of deterministic findings to a model, with no tools and no agent loop ([Coroot](https://coroot.com/blog/hard-part-of-ai-root-cause-analysis-is-no-longer-the-model/)) | AI RCA behind a paywall or cloud metering ([Coroot docs](https://docs.coroot.com/ai/overview)) |

Accuracy claims such as Komodor's ">95%" are self-reported ([Komodor](https://komodor.com/blog/komodor-ai-sre-vs-oss-ai-agent-a-technical-comparison-of-agentic-ai-for-kubernetes-troubleshooting/)). Independent benchmarks sit at 10–42%, as shown above. Separately, Amazon DevOps Guru stopped accepting new customers on 29 October 2026 ([AWS](https://docs.aws.amazon.com/devops-guru/latest/userguide/devops-guru-end-of-support.html)).

Demand centres on trust. In a NeuBird-sponsored survey of 696 respondents ([The Next Platform](https://nextplatform.com/control/2026/07/15/sres-to-ai-agents-prove-yourself-before-you-touch-production/5271533)):

- **60%** cite lack of trust as the main barrier;
- **59%** require near-perfect accuracy;
- **52%** would switch telemetry tools for AI that works across any back-end.

Rootly's practitioner write-up names the core complaint: "a plausible cause delivered with the same tone as a correct one" ([Rootly](https://rootly.com/blog/do-ai-sre-agents-actually-work)).

The positioning follows. Veyltrace should not claim "the first deterministic or causal RCA"; Dynatrace, New Relic and Causely already pitch that. It should also not claim autonomous remediation. Its claim is narrower and stronger: an **open, OTLP-native, laptop-runnable engine** that does four things:

- attaches machine-checkable verdicts (supported, refuted, insufficient) to every hypothesis;
- abstains with a calibrated set when evidence is thin;
- replays every verdict from a receipt;
- publishes per-case accuracy on public benchmarks.

Exposing that engine as an MCP tool (`verify_hypothesis(service, fault_class, window)`) makes it a complement to commercial agents rather than a rival. The idea of grading hypotheses is not new: Datadog marks them validated, invalidated or inconclusive. What no vendor offers is openness, replay and published per-case evidence.

## A deterministic verifier lets unproven local models help safely

### Ten engines fall into three trust classes

> **Update (2026-10-30):** the lead adopted this mapping with small changes (Causalith adds the restricted intervention test; TSFM stays in Anomara as an off-by-default ablation plugin; Relentra's default is the single-call `brief` mode). The binding version is [docs/02-architecture.md §3](../docs/02-architecture.md).

The lead is still assigning the ten engine roles. The mapping below is a proposal. It keeps the four v1 names (Infralume, FaultLoom, Causentra, Causivra) in their v1 roles, which reuses the existing specification, and gives each new name a role its etymology suggests. The column that matters is the trust class: it decides which packages may import model libraries.

| Engine | Proposed role | Trust class | Core methods | Output |
|---|---|---|---|---|
| **Infralume** | Ingest OTLP and benchmark adapters; normalize names and units; cut windows; snapshot and hash | Deterministic | Collector → FastAPI; Parquet with sha256 | Signal Cube snapshot |
| **Signalyth** | Per-signal features: metric series, log templates, trace call edges, critical paths | Deterministic | Drain3; critical-path reconstruction (CRISP-style) | Signal features |
| **Anomara** | Two-sided robust deviation, onset detection, internal/external split | Deterministic (an optional TSFM channel with pinned weights is a proposer) | PRISM-style scoring with scale floors | Anomaly scores, onsets |
| **Causync** | Change events and time alignment | Deterministic | k8sobjects, OpenFeature events, DuckDB ASOF JOIN | Change-to-onset links |
| **Causalith** | Service topology, call graph, blast radius | Deterministic | Graph built from traces plus a per-system YAML | Service graph |
| **FaultLoom** | Weave evidence cards with stable IDs and provenance | Deterministic | EviRCA-style evidence cards | Evidence fabric |
| **Causatrix** | Recall-first retrieval and deterministic ranking/fusion | Deterministic | PRISM core + gated reciprocal rank fusion (RRF) | Top-K hypotheses |
| **Relentra** | Proposers: an LLM re-ranker or agent over read-only tools; ML proposers (kNN fault typing, TSFM) | AI allowed, **proposals only** | Qwen3.5-9B, grammar-constrained JSON, cassettes | Proposals plus tool trace |
| **Causentra** | Verifier: predicates, coverage checks, trials, conformal set, abstention; seals `verdict_hash` | Deterministic (**the decision**) | Code-only predicate evaluation | Verdict |
| **Causivra** | Slot-filled narration, claim checks, receipt, replay command | AI allowed for prose only | in-toto statement, hash-chained trace | Incident card + receipt |

The v1 rule "no AI in the decision path" survives almost intact. The import ban (no `openai`, `ollama`, `torch` and so on) now covers every engine except Relentra and Causivra's narrator. Causentra receives proposals as JSON data, never as model calls.

### Proposals are data; predicates are code

The verifier's contract follows from the failure modes the 2026 papers measured. The trajectory study's taxonomy shows what goes wrong in failed runs ([DiagGuard](https://arxiv.org/html/2608.21310)):

| Failure mode | Share of Sonnet's failed runs | Share of Qwen's failed runs |
|---|---|---|
| Fabricated cause outside the label space | **82%** | 20.2% |
| Propagation edge never tested | 54% | 68.3% |
| Silence treated as health | 30% | 44.2% |

DiagGuard's LLM-based verifier raised Acc@1 in all 14 configurations, by 3.5–35.1 pp. But it did *not* reduce "semantics misread" errors, which went from 11.8% to 13.6%. Checks of meaning therefore belong in code. ARGUS adds the industrial counterpart: a sufficiency gate, an explicit "Unknown" instead of inferred values, and a confidence label computed from tool-success ratios rather than generated by the model ([ARGUS](https://arxiv.org/html/2608.23084)).

From this evidence, Causentra enforces six rules:

1. **Proposers can only add candidates.** The hypothesis set is Causatrix's deterministic top-K *plus* any proposer additions, so turning AI off can never lower recall below the deterministic floor.
2. **The hypothesis space is closed.** Each hypothesis is `{service ∈ enum(topology), fault_class ∈ enum(taxonomy), onset_window}`, enforced as a JSON-schema enum at decode time. Fabricated causes outside the label space become impossible to express.
3. **Every claim is a predicate plus a pointer.** A claim is `{predicate_id, args, evidence_ref}`. The verifier re-runs each referenced query against the snapshot, and the model never supplies a number.
4. **Coverage checks are mandatory.** Each candidate needs a baseline-vs-incident comparison, at least one parent→child edge test, a resource probe and a traffic-drop (silence) check. Without all four, the verdict is `INCONCLUSIVE`.
5. **Hypotheses must survive deterministic consistency tests.** Onset must precede dependents' onsets, except in network mode, where the precedence flips. The suspect's blast radius must explain the anomalous services. Replacing the suspect's values with in-distribution values must restore the symptom (IDI-lite).
6. **A code rule issues the verdict.** It accepts the top hypothesis only when every mandatory predicate passes and its margin over the runner-up clears a calibrated threshold. Otherwise it returns the conformal candidate set and abstains.

These rules can be tested directly. A **permutation test** should show the verdict depends on the *set* of proposals, not on their order or wording. A **proposer-off run** gives the "AI off" baseline. A **planted-decoy test** injects a wrong hypothesis with fabricated claims and checks that the verifier rejects it. This is the deterministic answer to the false-"NOTE" attack, under which models chose the decoy 21–42% of the time ([Hussain & Farrukh](https://doi.org/10.21203/rs.3.rs-11401166/v1)).

Calibration must also stay in code. LM-PACE shows that raw LLM self-confidence is badly calibrated: fixing it took retrieval plus a learned transformation, which cut calibration error to 31% of the direct-prompting baseline ([LM-PACE](https://arxiv.org/pdf/2309.05833)). Veyltrace should never use model-reported confidence. Instead, a split-conformal top-k̂ set calibrated on held-out cases, stratified by system and by which telemetry types are present, gives a coverage guarantee under exchangeability. Recent theory supports conformal sets over rankings ([NeurIPS 2025](https://arxiv.org/abs/2501.11384v3)). Practitioners also find numeric confidences hard to interpret ([Westermo report, search snippet only](https://arxiv.org/pdf/2609.21843)). The UI should therefore show "verified 4/4 predicates; candidate set {A, B}" rather than a probability.

### Replay re-verifies recorded proposals instead of re-generating them

Bit-exact LLM re-generation is not a portable guarantee. In one experiment, 1,000 temperature-0 completions of Qwen3-235B produced **80 distinct outputs**, because server kernels change their reduction order with batch size; batch-invariant kernels fixed it at a speed cost ([Thinking Machines](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)). The common runtimes each have caveats:

- **vLLM**: its batch-invariant mode is beta, and the newest docs require datacenter GPUs of compute capability ≥ 9.0, while older pages say ≥ 8.0, so the docs conflict ([vLLM](https://docs.vllm.ai/en/latest/features/batch_invariance/)).
- **llama.cpp**: its server README warns that enabling `cache_prompt` can make results nondeterministic ([llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)). A matching warning about multiple parallel slots was seen only in a fork of the README (unverified upstream).
- **Ollama**: it needs temperature 0 *and* a fixed seed, and output still drifts across versions and quantisations ([makandra](https://makandracards.com/makandra/626358-ollama-generate-deterministic-results)).

The replay claim should therefore come in two tiers.

**Tier 1 (guaranteed).** The verdict is a pure function of the snapshot hash, the recorded tool results, the recorded proposals, the verifier code hash and the config hash. `veyltrace replay <receipt>` reloads the snapshot and the cassette, re-runs Causentra and asserts the same `verdict_hash` on any laptop. If a recorded tool result's hash no longer matches what the snapshot produces, that is evidence of tampering.

**Tier 2 (best effort).** Re-generating the same proposals uses `llama-server -np 1` (one request slot), `cache_prompt: false`, a fixed seed, a GGUF file pinned by sha256, a pinned llama.cpp commit and the same thread count. Report the measured match rate, such as "N of 50 incidents reproduce byte-identical proposals", as a secondary result.

The receipt combines three published pieces. W3C PROV activities record each tool call, LLM call and verifier check; PROV-AGENT extends PROV for agents ([PROV-AGENT](https://arxiv.org/abs/2508.02866)). An append-only, hash-chained JSONL trace follows the IETF WCA draft ([WCA](https://www.ietf.org/archive/id/draft-bondar-wca-00.html)). An in-toto Statement v1 envelope wraps the result, with subjects matched only by content digest ([in-toto](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)). No source combines all three; this is a design inference.

The v1 determinism rules carry over unchanged: exact quantiles, DuckDB `threads=1` for final aggregates, total tie-breaks, canonical JSON, and determinism tests under two `PYTHONHASHSEED` values. Because the verifier decides, nondeterministic proposals affect only *which* hypotheses get tested, never the integrity of the verdict. Agent accuracy is then reported over 3–5 seeds with a standard deviation.

### Qwen3.5-9B on CPU fits the proposer role within a token budget

| Model | Licence | Size and context | Tool-use scores (vendor-reported) | Fit for a 16 GB laptop |
|---|---|---|---|---|
| **Qwen3.5-9B** | Apache-2.0 | 9B, 262K context | BFCL-V4 **66.1**, TAU2 **79.1**, IFEval 91.5 | Main proposer at Q4_K_M; ~5.5–6.5 GB of weights (estimate) |
| Qwen3.5-4B | Apache-2.0 | 4B | BFCL-V4 50.3, TAU2 79.9 | Fallback for weak CPUs |
| Gemma 4 12B | Apache-2.0 | 11.95B, 256K context | Tau2 69.0 | Alternative; Q4_0 weights ~6.7 GB |
| Gemma 4 E4B | Apache-2.0 | 4.5B effective | Tau2 42.2 | Narration only |
| gpt-oss-20b | Apache-2.0 | 21B total / 3.6B active | Native tool calls; requires the harmony format | Avoid: ~13–14 GB once loaded |

Sources: [Qwen3.5-9B card](https://huggingface.co/Qwen/Qwen3.5-9B); [Gemma 4 card](https://ai.google.dev/gemma/docs/core/model_card_4); [gpt-oss-20b card](https://huggingface.co/openai/gpt-oss-20b); [glukhov memory benchmarks](https://www.glukhov.org/llm-performance/benchmarks/choosing-best-llm-for-ollama-on-16gb-vram-gpu/).

CPU speed is the binding constraint, and published laptop numbers are weak. One measured data point is **6.1–6.5 tokens/s for an 8B Q4_K_M model on a 4-core i7-1165G7** ([dev.to](https://dev.to/tekk_73/an-8b-llm-on-a-4-core-laptop-cpu-no-gpu-6-tokenssec-25gi)). Other sources give estimates of 3–15 tokens/s. Each team laptop must run `llama-bench` and record its prompt-processing and generation speeds with the GGUF hash.

That speed makes the agent loop the expensive option. A single-agent ReAct run averaged 41K tokens per case on LO2 ([LATS-RCA](https://arxiv.org/html/2605.03505)), which is several minutes on a CPU. The laptop default for Relentra should instead be the cheap pattern the evidence supports: **one listwise proposal call over evidence cards plus a short per-system YAML description**. A one-shot call over an evidence package scored 65.3 PR@1 on RCAtlas with frontier models, and DecompRCA's system description added 7–18 points. The multi-turn agent becomes an ablation arm, run under a code-owned state machine (one hypothesis → N checks → verdict request) with a 10–20-turn budget. That design addresses the finding that small backbones rarely act on prior results.

Outputs should be grammar-constrained through llama.cpp's `json_schema`. JSONSchemaBench shows open engines reach about **0.95 coverage on simple function-call-style schemas, but collapse on complex ones** (llama.cpp scores 0.39 on its "GitHub Hard" set) ([JSONSchemaBench](https://arxiv.org/html/2501.10868v2)). Schemas should therefore stay flat and enum-heavy, and Pydantic should re-validate every output. Ollama also recommends restating the schema in the prompt ([Ollama](https://docs.ollama.com/capabilities/structured-outputs)). A plain ~200-line Python loop beats LangGraph or smolagents here, because it controls exactly what gets hashed and recorded.

Budget the proposer arm explicitly. By my estimate, 270 RE2 cases × 3 seeds × ~1.5 minutes per one-shot call is about 20 laptop-hours, so the full agent loop can run only on a stratified subset. Whether a frontier cloud API may be used as an *offline, cassette-recorded* comparison arm is a decision for the lead. It sits awkwardly with "no cloud", but it would show how much proposer quality matters while the verdict stays deterministic.

## Evaluation must survive onset shifts, pooled leaderboards and decoys

### Three benchmark tiers: an easy anchor, a hard set, a cross-check

| Benchmark | Cases | Telemetry and labels | Laptop fit | Role for Veyltrace |
|---|---|---|---|---|
| RCAEval RE1/RE2/RE3 | 735 | Metrics, logs, traces (no traces for Sock Shop); service + fault type | Hugging Face Parquet 3.4 GB; harness wants ≥8 cores, 16 GB RAM, ~50 GB disk ([README](https://github.com/phamquiluan/RCAEval)) | Comparability anchor; tune on RE1 only |
| FSE'26 propagation-aware Train Ticket | 1,430 | Metrics, logs, traces; labels from service down to function | Zenodo; size and licence unverified ([arXiv](https://arxiv.org/abs/2510.04711)) | "Beyond too-easy benchmarks" hard set |
| Nezha | 101 | Online Boutique + Train Ticket; indicator labels | Data in the repo, MIT ([GitHub](https://github.com/IntelligentDDS/Nezha)) | Cross-source check on the same systems |
| AIOps2025 | 400 | Service, pod and node labels; HipsterShop | 11.9 GB Parquet; licence not stated ([AgenticOpsEval](https://arxiv.org/html/2606.29193v1)) | Optional industrial-looking set |
| Cloud-OpsBench | 754 | Pre-recorded tool responses (3.5–8.8 MiB snapshots); CC BY 4.0 | No cluster needed ([arXiv](https://arxiv.org/abs/2603.00468)) | Proposer/agent arm |
| RCAtlas core | 90 | Pooled from 8 datasets | Hosted on a temporary file host (an availability risk) ([RCAtlas](https://arxiv.org/html/2610.35767)) | Cross-benchmark comparison with published agent numbers |
| OpenRCA 1.0 / 2.0 | 335 / 500 | Needs (time, component, reason) output | 1.0 recommends 32 GB RAM and 80 GB disk; 2.0 data unreleased ([OpenRCA](https://github.com/microsoft/OpenRCA)) | Subset only, or skip |

Live benchmarks (SREGym, AIOpsLab, ITBench) are mitigation-centric, scored by LLM judges, and need 16 GB for the cluster alone ([SREGym GitHub](https://github.com/SREGym/SREGym)). They are out of scope for month one. The output contract should still be **(service, fault type, onset time)** from day one, so that OpenRCA-style and AIOps2025-style benchmarks become scorable later.

Baselines should be re-run inside Veyltrace's own harness with the RCAEval commit pinned and its `--report-chance` and `--report-decomposition` flags enabled. The set is BARO, NSigma, CIRCA, RCD, TraceRCA and SimpleRCA, plus a PRISM re-implementation. Skip TORAI unless someone owns its Python 3.8 environment.

### A pre-registered protocol detects 7-point differences, not 3-point ones

The headline metric should be service-level AC@1 **per system**, never only pooled. Hu, Liu & Fu show that pooled leaderboards hide system-specific winners ([Hu et al.](https://arxiv.org/abs/2606.29159)):

- leave-one-system-out selection picks the worse method on up to 5 of 11 subsystems, with regret up to **24.8 pp**;
- 6 of 8 leads with small margins reverse on another subsystem.

Around AC@1 sit:

- AC@3, Avg@5 and MRR;
- Retrieval@K and Rerank@1 (the decomposition);
- Chance@5 and Lift@5;
- fault-type accuracy;
- for the conformal layer: empirical coverage, mean set size, abstention rate and AURC;
- for the proposer arm: proposer lift (verified AC@1 with proposers minus without), decoy-rejection rate and Tier-2 regeneration match rate.

The statistics should copy the pre-registered RCAEval study ([Hussain & Farrukh](https://doi.org/10.21203/rs.3.rs-11401166/v1)). It used paired differences on the same cases, with clusters by (system, root service, fault) because RCAEval's repetitions are not independent; a 2,000-resample cluster bootstrap; a 10,000-permutation cluster sign-flip test; exact McNemar as a secondary analysis; and Holm correction. Its power analysis matters for planning: with ~30% discordant cases, the **minimum detectable difference is about 7 points on 270 cases and 14 points on 90**. Claims of smaller gains should read "not detected". That study also pre-registered via a tagged commit before seeing any fault window, which costs Veyltrace nothing to copy.

Robustness tests are what reviewers will ask for:

- onset shifts of ±60 and ±120 s, plus self-detected onset against the oracle injection time;
- modality ablation (metrics only, plus logs, plus traces), using Sock Shop's missing traces as a natural experiment;
- leave-one-system-out for every tuned threshold;
- service-name anonymisation, which cost an LLM pipeline 0.20–0.21 on RE3;
- the planted-decoy proposal test.

Because Relentra is an LLM component, the 2026 empirical-SE LLM guidelines apply. They require exact model versions and configurations, released prompts and interaction logs, a naive baseline, repeated runs reported as distributions, an open-model baseline, human-validated judges, and discussion of contamination and non-determinism ([llm-guidelines.org](https://llm-guidelines.org/guidelines/)). Veyltrace's cassettes satisfy the logging requirement for free. Finally, publish wall-clock time per case (p50 and p95), peak RSS and the CPU-only hardware spec. Against agents costing USD 0.04–4.64 per case ([trajectory study](https://arxiv.org/html/2608.21310)), a cost table is a selling point.

## Two demo systems and the whole stack fit in 16 GB with care

### Online Boutique and the OpenTelemetry Demo fit; Train Ticket does not

WSL2 gives its VM **50% of Windows RAM by default**, so 8 GB on these laptops ([Microsoft Learn](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)). Raise it to 11–12 GB in `.wslconfig` (my estimate). Two systems fit:

- **OpenTelemetry Demo 3.1.0 on Docker Compose.** `make start-minimal` cuts memory use to about 3 GB ([OTel demo](https://opentelemetry.io/docs/demo/docker-deployment/)). Summing the 3.1.0 compose memory limits gives 4,155 MB for the core services and 2,664 MB for observability; the browser-traffic Locust load generator alone takes 1.5 GB ([compose.yaml @3.1.0](https://github.com/open-telemetry/opentelemetry-demo/blob/3.1.0/compose.yaml)).
- **Online Boutique v0.10.7 on kind.** It requests only **1.57 CPU and 1,368 MiB** ([manifest @v0.10.7](https://github.com/GoogleCloudPlatform/microservices-demo/blob/v0.10.7/release/kubernetes-manifests.yaml)). It is the same system as RCAEval-OB and Nezha-OB, which enables transfer experiments.

Train Ticket needs at least 24 GB of memory and 50 GB of disk ([installation guide](https://github.com/FudanSELab/train-ticket/wiki/Installation-Guide)). SREGym-Lite wants 8 vCPU and 16 GB for its cluster alone.

Fault injection maps cleanly onto the two systems:

- **Chaos Mesh 2.8.7**, installed by Helm with `chaosDaemon.runtime=containerd`, supports kind and reproduces the AIOpsLab and AIOps2025 fault families ([Chaos Mesh](https://chaos-mesh.org/docs/quick-start/)).
- **`stress-ng` and `tc netem` inside containers** reproduce RCAEval's faults. The WSL kernel config builds `CONFIG_NET_SCH_NETEM=m` ([WSL kernel config](https://github.com/microsoft/WSL2-Linux-Kernel/blob/linux-msft-wsl-6.18.58.1/arch/x86/configs/config-wsl)); whether it loads under Docker Desktop is unverified on these laptops.
- **The OTel demo's flagd flags** (`paymentFailure`, `emailMemoryLeak`, `productCatalogLockContention` and 15 more) give application faults with no tooling ([feature flags](https://opentelemetry.io/docs/demo/feature-flags/)). Scrub `feature_flag.*` attributes from engine inputs, because flag names in spans would leak the answer (an inference to verify).
- **Pumba** states it does not support Windows, even on the WSL2 backend ([Pumba](https://github.com/alexei-led/pumba)).

| Component | Memory (estimate unless sourced) |
|---|---|
| Windows + Docker Desktop VM overhead | ~4–6 GB (unsourced estimate) |
| Demo app: Online Boutique (requests) or OTel Demo minimal | 1.3 GB / ~3 GB |
| Collector + Prometheus + Jaeger (OTel demo limits: 400 MB, 200 MB, 1.2 GB) | ~2–2.5 GB without OpenSearch, Loki or Grafana |
| Veyltrace API + DuckDB `memory_limit` | 2–3 GB |
| Qwen3.5-9B Q4 + KV cache | ~6–7 GB |

The arithmetic says a single 16 GB laptop cannot comfortably run the testbed, the telemetry stack, Veyltrace *and* a 9B model at once. The live demo should instead split across two laptops (testbed on one; Veyltrace plus the model on the other), drop to Qwen3.5-4B, or replay cassettes for the proposer step. Overnight injection campaigns and proposer evaluation runs also compete for the same machines, so schedule them on alternate nights.

### One Collector, Parquet and DuckDB replace a five-database stack

**Telemetry.** Run one `otelcol-contrib` Collector with `memory_limiter` and GOMEMLIMIT at roughly 75–80% of its container limit, about 400 MiB for a 512 MB limit ([OneUptime](https://oneuptime.com/blog/post/2026-02-06-gomemlimit-memory-limiter-stable-collectors/markdown)). It should forward OTLP/HTTP protobuf to a FastAPI receiver whose `opentelemetry-proto` version is pinned to match the SDKs. The Collector is still versioned 0.x (v0.164.0, 26 Oct 2026) ([releases](https://github.com/open-telemetry/opentelemetry-collector-releases/releases)).

**Semantic conventions.** Key RCA joins on stable attributes: HTTP, database, `service.instance.id`, `deployment.environment.name` and the core Kubernetes resource attributes. CI/CD, VCS and RPC conventions are only release candidates ([semconv releases](https://github.com/open-telemetry/semantic-conventions/releases)).

**Stretch goals only.** OTel Profiles entered public alpha in March 2026, and the SIG advises against using it for critical production workloads ([OTel blog](https://opentelemetry.io/blog/2026/profiles-alpha/)). OBI eBPF instrumentation is pre-1.0 and needs a Linux kernel with BTF ([OBI goals](https://opentelemetry.io/blog/2026/obi-goals/)).

**Storage.** Keep Parquet (zstd) plus in-process DuckDB as the analytical core. DuckDB **2.0.0 LTS shipped on 21 Oct 2026, and files in its new storage format cannot be read by older versions**, while 1.5 is supported until March 2027 ([DuckDB](https://duckdb.org/2026/10/21/announcing-duckdb-200)). Pin 1.5.x as v1 did, or adopt 2.0 only with Parquet as the persistence format.

**Change alignment.** DuckDB's ASOF JOIN answers "which change came last before each service's onset" in one query ([ASOF](https://duckdb.org/docs/2.0/guides/sql_features/asof_join.html)). Change events come from three sources, normalized into Veyltrace's own `change_event(ts, service, kind, ref, attributes)` table:

- the Collector's `k8sobjects` receiver (deployments and events) ([Splunk docs](https://help.splunk.com/en/splunk-observability-cloud/manage-data/available-data-sources/supported-integrations-in-splunk-observability-cloud/opentelemetry-receivers/kubernetes-objects-receiver));
- OpenFeature's `PROVIDER_CONFIGURATION_CHANGED` event, which may carry the changed flag keys ([OpenFeature](https://openfeature.dev/specification/sections/events));
- scripted deploy records using the CI/CD conventions.

**What to avoid locally.** A separate Tempo deployment alone is sized at 4–8 GB ([Tempo](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/deploy/locally/linux/)), so do not run Tempo, Loki and ClickHouse on the laptops. `grafana/otel-lgtm` is an optional, memory-capped "real Grafana" side panel ([Grafana](https://grafana.com/docs/opentelemetry/docker-lgtm/)).

**No queue.** Use an in-process hot window flushed to Parquet every 5–10 s. Snapshot and hash every analysed window, which turns each live diagnosis into a replayable offline case.

**API and UI.** Use FastAPI with Pydantic v2; it has the largest ecosystem and the most AI-coding-agent familiarity ([Encore](https://encore.dev/articles/litestar-vs-fastapi)). The front end is React with TypeScript on Vite 8 ([Vite](https://vite.dev/blog/announcing-vite8)), ECharts 6.1 for time series with baseline bands ([ASF](https://release-catalog.apache.org/echarts/6.1.0/index.html)), and Cytoscape.js for the service graph. Generate TypeScript types from FastAPI's OpenAPI with `openapi-typescript`, and fail CI on contract drift. Pin ECharts 6, because coding agents trained on v5 examples will emit outdated options.

### A 300-case laptop dataset is a week of overnight runs and a second paper

The proposed "VL-RCA" dataset should fix what reviewers now criticise in RCAEval: unpublished injection parameters, non-independent repetitions, missing telemetry, and answers encoded in folder names. Its design:

- **Systems**: Online Boutique on kind with Chaos Mesh, and the OTel Demo on Compose.
- **Fault catalog**: about 12 types across resource, network, Kubernetes and application faults.
- **Grid**: about 5 target services × 10 faults × 3 repetitions per system, roughly 300 cases.
- **Controls**: about 10% no-fault cases (AIOpsLab-style "noop"), about 10% benign-noise cases, and optionally ~20 two-fault cases.
- **Per-case protocol**: fresh deploy, 3 min warm-up, a baseline-recovered check, 10 min normal, 10 min fault, 2 min cool-down, export. That is about 25 minutes per case, or **57 cases per laptop per 24 h** (my computation).
- **Validation**: keep only cases whose user-facing SLI deviates measurably, as the FSE'26 benchmark did (it kept 1,430 of 9,152 injections) ([Fang et al.](https://arxiv.org/abs/2510.04711)). Report the acceptance rate, which is unknown for laptops.
- **Ground truth**: a separate answer key, opaque case IDs, injector name, version and parameters, and nanosecond injection timestamps.
- **Release**: Croissant metadata with the mandatory Responsible-AI fields for NeurIPS E&D ([NeurIPS](https://blog.neurips.cc/2026/05/04/responsible-ai-metadata-requirements-for-the-evaluations-and-datasets-track-neurips-2026/)), CC BY 4.0 data, and a Zenodo DOI.

Start the campaigns in week 2 so they run in the background. Write the dataset paper after month one.

## Three coding agents need structure, not etiquette, to share one repo

### One AGENTS.md, imported everywhere

By late 2026, `AGENTS.md` is read natively by Codex, OpenCode, Cursor, GitHub Copilot's coding agent, Antigravity and Windsurf/Devin ([agents.md](https://agents.md/)). Claude Code reads it natively from v2.1.277, **but only when no CLAUDE.md exists**. A one-line `CLAUDE.md` containing `@AGENTS.md` works in every version. A CLAUDE.md that merely says in prose "read AGENTS.md" is weak, because Claude sees the file only if it decides to open it ([Claude Code docs](https://code.claude.com/docs/en/memory)).

Veyltrace's root CLAUDE.md is exactly that weak form. It also points to `AGENTS.md` and `docs/02-architecture.md`, which today exist only under `_hackday-v1/`. Fixing this, with the AI-import ban rewritten for the propose–verify split, is a day-one task.

Size limits vary by tool:

| Tool | Instruction limit |
|---|---|
| Windsurf/Devin | 12,000 characters per rule file ([Devin](https://docs.devin.ai/desktop/cascade/memories)) |
| Antigravity | 24,000 bytes per file ([Antigravity](https://antigravity.google/docs/rules/)) |
| Codex | 32 KiB combined ([Codex](https://learn.chatgpt.com/docs/agent-configuration/agents-md)) |

Keep the root file near 8–10 KB, with lane rules in nested `AGENTS.md` files. Each nested file needs its own one-line `@AGENTS.md` CLAUDE.md for Claude. VS Code reads nested AGENTS.md files only through an experimental setting that is off by default ([VS Code](https://code.visualstudio.com/docs/copilot/customization/custom-instructions)).

Avoid duplicates and symlinks. Do not add GEMINI.md or `.cursor/rules` copies. Gemini CLI stopped serving free and personal accounts on 18 June 2026, so a "Gemini" teammate should use Antigravity, which reads AGENTS.md ([Google](https://developers.googleblog.com/en/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)). Git for Windows disables symlinks by default ([Git for Windows](https://gitforwindows.org/symbolic-links)), so use imports instead.

Shared skills belong in `.agents/skills/<name>/SKILL.md`, following the open Agent Skills format ([agentskills.io](https://agentskills.io/)), with a generated copy in `.claude/skills/`. MCP configs differ per tool, so keep them gitignored and personal. Write every multi-step procedure as a `make` or `scripts/` target, because a shell command is the only "slash command" all six agents share.

### Lanes, frozen contracts and no shared registries

The conflict data is stark:

- AgenticFlict found a **27.67%** merge-conflict rate across 107K simulated agentic PRs ([AgenticFlict](https://arxiv.org/abs/2604.03551)).
- PR pairs from *different* agents that are open at the same time conflict **41.7%** of the time, against 19.8% for same-agent pairs ([Xu et al.](https://arxiv.org/abs/2607.04697)).
- **84.4%** of conflicted files are source code, and about 42% of conflicts are structural (add/add or modify/delete).

Structural conflicts disappear when each agent edits only its own tree. The proposed lanes follow the trust classes:

| Lane | Engines and areas |
|---|---|
| **A: evidence** | Infralume, Signalyth, Anomara, Causync, Causalith, FaultLoom, plus the testbed and injectors |
| **B: decision and evaluation** | Causatrix, Causentra including conformal calibration, the eval harness and baselines |
| **C: proposers and product** | Relentra, Causivra, API, UI, the MCP server |

The lead naturally owns `contracts/`, CI and Lane B, but the assignment is the lead's call. Encode the ownership map three times: in AGENTS.md, in `.github/CODEOWNERS` with two owners per path (an author cannot satisfy their own code-owner review), and in a CI check that fails cross-lane edits without a label ([CODEOWNERS](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)).

Four conventions remove the remaining conflict hot spots:

- **Contracts are frozen in week 1.** Pydantic models produce OpenAPI, which produces generated TypeScript that nobody edits. Changes need an ADR and the lead's approval.
- **No shared registries.** Use directory auto-discovery instead of registry dicts, towncrier fragments instead of a hand-edited CHANGELOG ([towncrier](https://towncrier.readthedocs.io/en/stable/tutorial.html)), and date-slug ADR names instead of sequential numbers.
- **Lockfiles have one owner and are regenerated, never hand-merged** ([pnpm](https://pnpm.io/git); [uv issue](https://github.com/astral-sh/uv/issues/16348)).
- **One short-lived branch per task, each in its own worktree** ([Claude Code worktrees](https://code.claude.com/docs/en/worktrees)).

GitHub's merge queue requires an organization-owned public repo, or GitHub Enterprise Cloud for private ones ([GitHub Docs](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)). The personal-account repo `DuhItzAniket/Veyltrace` should therefore use "require branches up to date" plus required checks: lint, types, tests, the determinism replay test and contract sync. Making the repo public makes standard Actions runners free. A private repo on the Free plan gets USD 12 of compute a month, about 2,000 Linux minutes ([Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)). Tag each PR with an `agent:` label. The resulting conflict statistics cost nothing to collect and make a credible threats-to-validity paragraph.

### The main 2027 deadlines have passed; aim the month at an artifact

| Date | Venue and track | Fit | Status |
|---|---|---|---|
| 6 Nov 2026 | CAIN 2027 Posters & Demos (ICSE co-located) | Early demo | Open; very tight |
| 13 Nov 2026 | ICSE 2027 workshops (AGENT, AIPerf and others), ACM SRC, Industry Challenge | Short paper on design + early results | Open; check each CFP and SRC eligibility ([ICSE dates](https://conf.researchr.org/dates/icse-2027)) |
| 16 Nov 2026 | WWW 2027 Demos | Live demo paper | Open ([WWW](https://www2027.thewebconf.org/demos/)) |
| 23 Jan 2027 | FSE 2027 Industry (10+2 pages) | Needs an industrial-relevance framing | Open ([FSE](https://conf.researchr.org/track/fse-2027/fse-2027-industry-papers)) |
| Feb 2027 | KDD 2027 cycle 2 (Research, ADS, D&B) | Method plus evaluation | Exact date unconfirmed ([KDD FAQ](https://kdd2027.kdd.org/frequently-asked-questions/)) |
| ~Apr 2027 | ISSRE 2027 research | Natural home for RCA and dependability | CFP unpublished; date inferred from 2026 ([listing](https://www.beri.net/events/issre-2027)) |
| ~May 2027 | NeurIPS 2027 Evaluations & Datasets | Dataset or evaluation paper (DecompRCA precedent) | Inferred from 2026 ([NeurIPS](https://blog.neurips.cc/2026/03/23/introducing-the-evaluations-datasets-track-at-neurips-2026/)) |

Several deadlines have already passed: the ICSE 2027 research track (30 Jun 2026), ICSE SEIP (23 Oct 2026), the FSE 2027 research track (2 Oct 2026, third-party source) and KDD cycle 1 (26 Jul 2026). The realistic sequence is therefore: by 28 November, an arXiv preprint plus an archived artifact; then FSE Industry or KDD cycle 2 for the method paper, with ISSRE or NeurIPS E&D as fallbacks or for the dataset. Since 21 January 2026, arXiv requires first-time submitters without prior accepted papers in the domain to get a personal endorsement ([CASRAI](https://casrai.org/news/arxiv-2026-endorsement-english-ai-policy-changes)). Line up an advisor-endorser now.

Build artifact readiness from day one:

- a `CITATION.cff` at the root, which gives GitHub a "Cite this repository" link ([GitHub](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-citation-files));
- Zenodo DOIs per release, which need a **public** repo ([GitHub](https://docs.github.com/en/repositories/archiving-a-github-repository/referencing-and-citing-content)), because ACM's "Available" badge rejects plain GitHub links ([AE guidelines](https://li.seas.upenn.edu/artifact-evaluation));
- a `make reproduce` target;
- a `results/<run_id>/manifest.json` for every number. v1's rule that "a Veyltrace number exists only if a script wrote it to `results/`" carries over unchanged.

### Four weeks, three lanes

| Week | Lane A: evidence | Lane B: decision and evaluation | Lane C: proposers and product |
|---|---|---|---|
| 1 (31 Oct–6 Nov) | RCAEval Parquet loaders; PRISM-style two-sided scorer; testbed smoke tests (`.wslconfig`, netem, Chaos Mesh on kind, OTel Demo minimal) with `docker stats` | Root AGENTS.md and CODEOWNERS; frozen contracts (hypothesis, evidence card, verdict, receipt); pinned baselines with chance and decomposition flags; protocol pre-registered by tagged commit | `llama-bench` on all three laptops; Relentra loop with cassette recording; UI on mocked JSON |
| 2 | Signalyth, Causync change channel, Causalith graph; injection scripts running overnight | Causatrix ranker; Causentra predicates, coverage checks and conformal layer; first replay test | Evidence-card listwise proposer; FastAPI receiver and incident card; MCP `verify_hypothesis` |
| 3 | Live demo with real rollouts and flag flips; dataset validation | Full RCAEval, FSE'26 and Nezha runs; onset, modality, proposer and decoy ablations overnight; cluster statistics | Agent-loop ablation on a subset; narration claim checker; receipt viewer |
| 4 | Freeze; datasheet draft | Results tables written by scripts; paper draft | Tag v1.0.0; Zenodo DOI, `CITATION.cff`, demo video, arXiv |

End every week with an "integration Friday": the lead rebases all lanes, re-runs end-to-end replay and updates AGENTS.md. Humans resolved 96.1% of agentic merge conflicts in one 2026 study, though that figure comes from a search summary ([SBES 2026](https://cbsoft.sbc.org.br/2026/data/papers/sbes/How%20AI%20Coding%20Agents%20Resolve%20Merge%20Conflicts%20An%20Empirical%20Study.pdf)).

## Conclusion

The question the field is asking has changed. In 2025 it was whether AI could find root causes at all. By late 2026 frontier agents name the right service most of the time on public data, yet strict metrics, unseen failures and planted decoys show that nobody can tell *when* they are wrong. A verifier that decides converts that weakness into quantities no vendor publishes: proposer lift, decoy-rejection rate, calibrated abstention and replay fidelity. It also makes Veyltrace's laptop constraint an asset. A 9B local model that is right only sometimes is still useful when every claim it makes is recomputed in code. The binding constraint on a laptop is the token budget, not accuracy: compact evidence cards and one-shot listwise proposals make local inference feasible, and cassette replay separates verdict integrity from model nondeterminism.

Two risks deserve honesty in the paper. First, the verifier's predicates encode assumptions. Internal-before-external onset flips for network faults, so network-fault cells will show the highest abstention, and the paper should report that rather than tune it away. Second, the "first conformal RCA" claim rests on searches finding nothing. It needs a full-text check of ICSE, FSE, ASE and arXiv before submission. Several inputs are also unverified and must be measured before anyone quotes them: CPU tokens per second for the chosen models, netem and Chaos Mesh behaviour under Docker Desktop, the FSE'26 benchmark's size and licence, and every vendor-reported tool-use score.
