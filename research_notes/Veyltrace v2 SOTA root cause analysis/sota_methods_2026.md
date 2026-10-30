# SOTA in microservice RCA and root-cause localization as of late October 2026: classical vs LLM/agentic vs hybrid, with measured numbers (delta over the earlier Veyltrace notes)

Researched 30 Oct 2026. These notes are a **delta** on `research_notes/Veyltrace outage diagnosis research/sota_rca_methods.md` and `novel_techniques.md`. Those notes already cover PRISM (0.68/0.91/0.87 on 735 RCAEval cases), BARO, TORAI (FSE'26), EventADL, the Fang et al. SimpleRCA critique, the Buljić 5-service-prior critique, the ASE'24 causal study, RCLAgent, OpenRCA 1.0 (11.34%), Kim et al. (AIOps'26), ITBench 13.8%, AIOpsLab and Flow-of-Action. Those numbers are repeated here only when a new 2026 source **confirms, contradicts or supersedes** them.

Status labels: **[peer-reviewed]** (accepted venue stated), **[preprint]** (arXiv only), **[repo]**, **[search-summary]** (taken from a search engine summary and not opened, so treat as weaker). Metric names: AC@k = Top-k = PR@k (share of cases with the true cause in the top k); EM = exact root-cause set. "LLM agent" = an LLM driving tool calls over telemetry.

---

## Q1. Classical (statistical, causal, trace, log, multi-source) RCA: who leads in 2026, on which data, and where do the papers disagree?

### Takeaway
No new graph-based or causal method beat the 2026 statistical leaders (PRISM, TORAI, NSigma/BARO-style deviation scoring). Three late-2026 evaluations (NeurIPS'26 DecompRCA, ASE'26 GALA+, RCAtlas) find again that **graph-based RCA never clearly beats the best statistical baseline**. On simple benchmarks such as RCAEval RE1, **retrieval is nearly solved**: the true cause is in the deviation-ranked top-15 for 98–100% of faults. The open problem is **re-ranking**: statistical baselines mis-rank the true cause in 79–100% of complex-fault cases. Cross-paper numbers for CIRCA and RCD still vary enormously, from about 0.06 to 0.67 AC@1 on the same RCAEval systems.

### Cited Findings
**New consolidated evidence (2026)**
- **DecompRCA, "Where Root Cause Analysis Fails: A Retrieval-Reranking Decomposition"** **[peer-reviewed, NeurIPS 2026 Evaluations & Datasets Track]**. Authors: Muhammad, **Luan Pham** (the BARO/RCAEval/PRISM author), Barrière, Shetty, Pulga, Salim (UNSW / Baker Hughes). arXiv 2609.36686, 29 Sep 2026.
  - It splits top@k into *retrieval failure* (the true cause is never a candidate) and *reranking failure* (it is a candidate but ranked too low).
  - On complex-fault benchmarks, statistical baselines mis-rank the true cause **79–100%** of the time. On simple benchmarks, retrieval reaches **98–100%**.
  - "Graph-based methods never clearly beat the best statistical baseline."
  - — [arXiv abs](https://arxiv.org/abs/2609.36686)
- **DecompRCA benchmark suites:** RCAEval **RE1-OB, RE1-SS, RE1-TT** (125 cases each), plus three industrial control/building suites (WADI with 14 attacks, SWaT with 36, HVAC with 48 faults). Deviation magnitude puts the true cause in the **top 15 for 98–100% of microservice faults**, but in only **35–64%** for WADI, SWaT and HVAC. — [DecompRCA GitHub](https://github.com/cruiseresearchgroup/DecompRCA)
- **RCAEval now ships the decomposition metrics.** The Sep 2026 changelog added `--report-decomposition K` (Retrieval@K, Rerank@1) from the NeurIPS'26 paper and `--report-chance` (Chance@5, Lift@5). It also **fixed PageRank-based methods and CIRCA "silently falling back to column order"**, which may explain some earlier anomalous numbers for those baselines. — [RCAEval README](https://github.com/phamquiluan/RCAEval)

**Independent re-run of classical baselines inside GALA+ (ASE'26).** These are Table 1 AC@1 / AC@3 in %. Every value is a multiple of 1/90, which implies 90-case sets, i.e. probably RCAEval **RE2-OB / RE2-TT** (my inference). — [GALA+ arXiv HTML](https://arxiv.org/html/2608.08968v1)

| Method | OB AC@1 | OB AC@3 | TT AC@1 | TT AC@3 |
|---|---|---|---|---|
| CIRCA | **66.67** | 90.00 | 53.33 | 71.11 |
| RCD | 64.44 | 72.22 | 10.00 | 18.89 |
| BARO | 14.44 | 87.78 | **66.67** | 82.22 |
| TraceRCA | 13.19 | 61.54 | 64.44 | 75.56 |
| HeMiRCA | 37.78 | 58.89 | 21.11 | 34.44 |
| Nezha | 28.89 | 52.22 | 15.56 | 40.00 |
| CausalRCA | 26.67 | 68.89 | timeout | timeout |
| PC-PageRank | 15.56 | 36.67 | 1.11 | 6.67 |
| Granger-PageRank | 12.22 | 35.56 | 3.33 | 6.67 |
| LiNGAM-PageRank | 0.00 | 1.11 | 0.00 | 0.00 |

**RCAtlas (Oct 2026), a cross-benchmark core set with every classical method run in one harness**
- RCAtlas has 90 validated cases pooled from eight public RCA datasets: AIOps 2022, AIOps 2025, ITBench-SRE, LEMMA-RCA, OpenRCA 1.0, OpenRCA 2.0, RCA-100 and RCAEval RE1–3. **[preprint, arXiv 2610.35767, 26 Oct 2026, Peking University / BUPT]** — [arXiv HTML](https://arxiv.org/html/2610.35767)
- Classical results on all 90 cases (PR@1 / RR, %):

| Method | PR@1 | RR |
|---|---|---|
| NSigma | 38.9 | 47.5 |
| TORAI (3-pass mean) | 33.3 | 46.8 |
| SimpleRCA | 33.3 | 45.1 |
| BARO | 22.2 | 31.7 |
| FaultInsight | 18.9 | 29.7 |
| CIRCA | 17.8 | 29.2 |
| RCD | 5.9 | 10.5 |
| Random | 5.5 | 12.0 |

  — [arXiv HTML](https://arxiv.org/html/2610.35767)
- Results on the 27-case RCAEval slice of RCAtlas (PR@1, %): TORAI 63.0, NSigma 59.3, SimpleRCA 55.6, BARO 44.4. On ITBench (5 cases), NSigma, TORAI, SimpleRCA and BARO all score **0.0**. On AIOps 2022, BARO and SimpleRCA score 0.0. — [arXiv HTML](https://arxiv.org/html/2610.35767)
- **Failure modes the RCAtlas authors identify in classical methods:**
  - NSigma and BARO score only *positive* deviations, so a service whose traffic **drops** ranks last.
  - RCD misses the root cause entirely in 71 of 89 cases.
  
  — [arXiv HTML](https://arxiv.org/html/2610.35767)
- **RCAtlas case validation:** 2,359 released cases → 542 screened → 348 passed eight exclusion rules. The exclusions included 69 with an unclean before-period, 56 with no evidence of the fault, 38 with incomplete data, 37 with the fault late in the window, 14 with a missing culprit, **20 with multiple faults**, and 8 with contradictory labels. — [arXiv HTML](https://arxiv.org/html/2610.35767)

**New 2025–2026 classical or learned methods not in the earlier notes**
- **DeltaRCA, "Enhancing Trace-Based RCA for Microservice Systems via Code Change Understanding"** **[peer-reviewed, ASE 2026, pp. 1612–1624, published 7 Oct 2026; Zhang, Zhang, Xie, Chen, Wu, Peng]**.
  - It "left-shifts" RCA: an LLM agent reads code changes to find semantically affected operations, which then weight a heterogeneous graph for **spectrum-based fault localization**.
  - On two microservice benchmarks with 200 injected faults it reports **63% Top-1 and 79% Top-3** on average.
  - — [DOI 10.1145/3832783.3837424](https://doi.org/10.1145/3832783.3837424) **[search-summary]**
- **CCLH (arXiv 2511.17566, Nov 2025) [preprint].** It uses cascaded conditional learning with a heterogeneous hypergraph and treats root-cause localization (RCL) and failure-type identification (FTI) *sequentially*, not jointly. — [arXiv](https://arxiv.org/pdf/2511.17566)
- **DynaCausal (arXiv 2510.22613, Oct 2025) [preprint].** Dynamic causality-aware RCA. Its numbers were not retrieved. — [arXiv](https://arxiv.org/html/2510.22613v1)
- **RuntimeSlicer (arXiv 2603.21495, 2026) [preprint].** A unified runtime-state representation for failure management. Its numbers were not retrieved. — [arXiv](https://arxiv.org/pdf/2603.21495)

### Inferences
- **Cross-paper variance is now the dominant "result" for causal baselines.** On (probably) RE2-OB, GALA+'s harness gives CIRCA 0.67 and RCD 0.64 AC@1, while RCAEval's own paper gives CIRCA 0.32 and RCD 0.09 on RE2-TT. RCAtlas gives RCD 5.9% overall. The Sep 2026 RCAEval fix for "CIRCA silently falling back to column order" suggests that some earlier low numbers were implementation bugs. Veyltrace must run every baseline in its own harness and pin the RCAEval commit.
- **GALA+'s BARO numbers match the RCAEval paper almost exactly** (TT 66.67/82.22 vs 0.67/0.82; OB 14.44 vs Fang et al.'s RE2-OB 0.14). This supports using "inject_time + default config" BARO as the canonical reference. PRISM's lower BARO numbers (RE2-TT 0.32) look like the outlier configuration.
- **For the RE2 systems, the reported Top-1 leaders are:** PRISM on OB (0.90) and SS (0.86); TORAI on TT (0.77); GALA+ 0.74 (OB) / 0.73 (TT); CIRCA 0.67 (OB, GALA+ harness); BARO 0.67 (TT). These come from different harnesses, and no paper compares PRISM, TORAI and GALA+ head to head.
- **The DecompRCA finding reframes Veyltrace's design problem.** On RCAEval the candidate set is easy, since a top-15 by deviation already holds the root cause about 99% of the time. The contribution has to come from **reranking within a small candidate set**, which is exactly where PRISM's internal/external logic, onset precedence and trace evidence act.
- **Two-sided deviation scoring is a cheap, evidence-backed fix.** RCAtlas shows one-sided scorers (BARO, NSigma) miss traffic-drop root causes, and OpenRCA 2.0's "presence bias" (agents treating silence from a failed service as normal) is the same failure in LLMs.

### Gaps
- DecompRCA's per-suite Retrieval@K / Rerank@1 numbers and its retriever signals were not retrievable from the abstract or README; they are in the PDF.
- GALA+ does not name its two benchmarks explicitly in the retrieved text; "RE2-OB/RE2-TT" is inferred from the 1/90 granularity and the BARO match.
- DeltaRCA's benchmarks and baselines were not verified beyond the search summary.
- No new trace-only or log-only classical method from 2025–2026 with RCAEval numbers was found. TraceRCA, MicroRank and Nezha remain the reference baselines.

---

## Q2. LLM and agentic RCA: how well do agents actually do in late 2026, at what cost, and how do they fail?

### Takeaway
The picture changed sharply in 2026. With 2026 frontier models, **simple harnesses** (a coding agent such as Codex CLI, or a DuckDB SQL ReAct loop over the raw files) reach **72–89% PR@1** on the 90-case cross-benchmark RCAtlas, against 38.9% for the best non-LLM method (NSigma). They also beat every published hand-crafted RCA agent (FoA 53.3%, RCAgent 49.3%, RCA-Agent 43.3%, mABC 15.6%), at USD 0.01–0.26 and 45–277 s per case. But stricter metrics stay low:
- **OpenRCA 2.0:** exact root-cause set 20.7% on average across 11 frontier LLMs, against 76% for naming "any correct service".
- **ORCA-bench (realistic oncall inputs):** at most 25.3% on medium tasks and 10.0% on hard ones.
- **SREGym:** end-to-end success drops from 63.7% on problems ported from older benchmarks to 17.9% on new failures.

The older notes' claim that "LLM RCA is 4–12.5% accurate" is therefore **outdated for service-level localization**, but still roughly right for full, grounded diagnosis.

### Cited Findings
**RCAtlas / "Free to Look, Free to Reason: Simple LLM Harnesses Outdiagnose Hand-Crafted RCA Agents"** — Bi, Zhang, Li, Wang, Ma; arXiv 2610.35767, 26 Oct 2026 **[preprint]** — [arXiv HTML](https://arxiv.org/html/2610.35767)
- **All 90 cases (PR@1 / RR, %):**

| Method | PR@1 | RR |
|---|---|---|
| Codex harness | 77.2 | 80.6 |
| SQL agent | 72.8 | 74.9 |
| One-shot (no tools) | 65.3 | 69.8 |
| FoA | 53.3 | 58.7 |
| RCAgent | 49.3 | 53.7 |
| RCA-Agent (OpenRCA) | 43.3 | 41.9 |
| DecompRCA | 28.5 | 34.4 |
| mABC | 15.6 | 16.1 |
| NSigma (best non-LLM) | 38.9 | 47.5 |

- **Simple harnesses by model (PR@1, %):**

| Model | SQL agent | Codex | One-shot |
|---|---|---|---|
| GPT-6.1 Sol | 84.1 | 87.0 | 74.4 |
| GPT-6 Astra (xhigh) | not run | 86.7 | 82.2 |
| DeepSeek V4.1 Flash | 78.9 | 85.6 | 75.6 |
| MiMo-V2.6-Pro | 64.4 | 74.4 | 57.8 |
| Claude Haiku 5.5 | 71.1 | not run | 60.0 |
| GPT-6 Luna | 68.5 | 68.9 | 60.4 |

  The best single run is Sol at xhigh with Codex: **88.9% PR@1, about USD 0.26 and 277 s per case**.
- **Cost per case:**
  - SQL agent: Luna USD 0.011 / 134 s; Sol USD 0.083 / 45 s.
  - Codex: Luna about USD 0.009 / 69 s; Sol about USD 0.149 / 105 s; Astra about USD 1.32 / 216 s.
  - One-shot: about 235k–293k prompt tokens.
  - Published agents make about 35–50 LLM calls per case.
- **Scaling observations:**
  - Raising reasoning effort above medium multiplies wall time by 1.5–7× for −2 to +7 RR.
  - Upgrading the model (Luna → Sol) gains 13–15 RR.
  - Every cost/time-Pareto-optimal run above NSigma uses a simple harness.
- **Per-source PR@1 for Codex:** RCAEval 90.1, OpenRCA 1.0 65.5, OpenRCA 2.0 72.2, RCA-100 66.7, AIOps 2025 81.5, AIOps 2022 52.8, ITBench 80.0, LEMMA 96.7. AIOps 2022 is the hardest source for every method.
- **Failure modes the paper identifies:**
  - **FoA:** the matched SOP may never read the logs, and its judge declared a wrong root cause "found" in round 1.
  - **mABC:** it walks the call chain and misses services that *stop receiving calls*. It was left undetermined in 42 of 89 cases on GPT-6 Luna, mostly on sources with few or no traces.
  - **RCA-Agent:** its executor discards outputs over 16,384 tokens, which cost Luna 16% of its steps.
  - **DecompRCA:** its candidate pool contains the root cause in only **57.8%** of cases, which caps its accuracy.
  - **Node-level faults:** agents name the true node in 85–90% of runs but blame a pod or service on it.
- **Limitations:** the authors reimplemented the published agents, only Codex was tested among coding harnesses, and there was no hallucination or calibration analysis.

**OpenRCA 2.0, "From Outcome Labels to Causal Process Supervision"** — Fang, Yang, Shang, Lu, Xu, Wang, Zhang, Zhang, Yu, He (CUHK-Shenzhen); arXiv 2606.27154 v2, 30 Jun 2026 **[preprint]** — [arXiv HTML](https://arxiv.org/html/2606.27154v2)
- **Benchmark:** 500 instances on TrainTicket, OpenTelemetry Demo and DeathStarBench Hotel Reservation, with 27 fault types. Step-wise propagation-path labels are built by the PAVE pipeline, and the benchmark adds process metrics (Path Reachability, Node F1, Edge F1).
- **Results for 11 LLMs (EM / AnySvc / PR, %):**

| Model | EM | AnySvc | PR |
|---|---|---|---|
| Gemini 3.1 Pro | 29.4 | 82.0 | 70.4 |
| Claude Opus 4.7 | 27.6 | 82.6 | 70.0 |
| Claude Sonnet 4.6 | 26.2 | 79.4 | 52.6 |
| MiMo 2.5 Pro | 22.8 | 77.8 | 59.6 |
| GLM 5.1 | 21.6 | 79.0 | 69.6 |
| Kimi K2.6 | 21.0 | 70.8 | 63.2 |
| DeepSeek V4 Pro | 20.4 | 65.6 | 53.0 |
| Qwen3.6-Max | 19.2 | 79.2 | 71.8 |
| Hy 3.0 Preview | 17.4 | 71.0 | 53.4 |
| Seed 2.0 Pro | 14.8 | 78.6 | 66.4 |
| MiniMax M2.7 | 6.8 | 69.8 | 46.4 |
| **Mean** | **20.7** | **76.0** | **61.5** |

  Edge F1 trails Node F1 for every model (43.4% vs 62.2% on average).
- **Failure modes:** premature commitment, **presence bias** (treating silence from a failed service as normal), and **salience capture** (fixating on the loudest downstream signal).
- **Release:** promised on acceptance (data CC-BY-SA 4.0, code Apache 2.0).

**OpenRCA 1.0 re-examined**
- **GitHub issue #23 (29 Jul 2026):** a leave-one-out "most frequent (component, reason) per system" predictor that reads **no telemetry** scores **7.46%** strict accuracy, against 11.34% for RCA-Agent with Claude 3.5. McNemar p = 0.0596, not significant.
  - Per system, the agent beats the baseline on Bank (+9.56 pp) and Telecom (+7.84 pp), but **loses** on Market-cloudbed-1 (−1.43) and Market-cloudbed-2 (−3.85).
  - By field, the agent roughly doubles the baseline on `reason` (21.1% vs 10.6%) but only matches it on `component` (18.9% vs 17.8%).
  - Maintainer reply (12 Oct 2026): leave-one-out uses evaluation labels, so it is not "zero-information" under the protocol.
  - — [GitHub issue](https://github.com/microsoft/OpenRCA/issues/23)
- **EviRCA (arXiv 2609.19825, 17 Sep 2026, Zhejiang University group (Deng) [preprint]):** **40.6–43.9%** correct on OpenRCA with two LLMs, against at most 15.2% for prior OpenRCA baselines. It uses **15–26× fewer tokens and runs 3–20× faster.** — [arXiv abs](https://arxiv.org/abs/2609.19825)

**Live SRE-agent benchmarks**
- **SREGym (arXiv 2605.07161, 8 May 2026, UIUC / Toronto [preprint]):** 90 problems on DeathStarBench, Train Ticket, Astronomy Shop and two in-house apps on Kubernetes.

| Agent (model) | Diag. | Mitig. | E2E | With noise: Diag / Mitig / E2E | Time to diagnose | Tokens per run |
|---|---|---|---|---|---|---|
| Stratus (Sonnet-4.6) | 61.5 | 78.5 | 54.8 | 51.5 / 65.5 / 40.2 | 114 s | 812K |
| Stratus (Kimi K2.5) | 41.3 | 60.6 | 32.9 | 38.9 / 57.3 / 30.4 | 674.5 s | 413K |
| Claude Code (Sonnet-4.6) | **72.6** | 75.6 | **60.7** | 62.6 / 76.3 / 53.7 | 292.5 s | 1.47M |
| Codex (GPT-5.4) | 70.0 | 65.2 | 53.3 | 59.3 / 64.0 / 45.9 | 176.4 s | 1.98M |

  - Stratus/Sonnet E2E falls from **63.7% on ported problems to 17.9% on new SREGym-only failures**.
  - Agents **mitigate without a correct diagnosis 35–59% of the time** (trial and error).
  - Agents behave greedily: the first plausible anomaly is taken as the target, and it is often noise.
  - No agent proposed disk-level diagnostics for hardware faults or connected the system and application layers in metastable failures.
  - 60–72% of tool calls are read-only `kubectl get`/`logs`.
  - Repo: github.com/SREGym/SREGym.
  
  — [arXiv HTML](https://arxiv.org/html/2605.07161v1)
- **Stratus (arXiv 2506.02009, 2025):** with GPT-4o it mitigated 9/13 AIOpsLab and 9/18 ITBench problems. Eight ITBench problems were "solved" because the fault did not persist after pod restarts. — [arXiv HTML](https://arxiv.org/html/2506.02009v2) **[search-summary]**
- **ORCA-bench (arXiv 2607.28545, v3 29 Sep 2026 [preprint]):**
  - Setup: **1,079 RCA tasks** over 6 days of OTel-instrumented microservice telemetry (50 GB). Agents use real Prometheus/Jaeger/OpenSearch interfaces and have access to source code. The LLM judge was re-scored by humans (κw = 0.91).
  - Best accuracy: **25.3% (Medium)** and **10.0% (Hard)**, and the gap "persists even with Claude Fable 5".
  - The weakest model **hallucinates an implausible root cause in 40%** of reports.
  - **Removing source-code access lowers accuracy and raises hallucination for every model.**
  
  — [arXiv abs](https://arxiv.org/abs/2607.28545)
- **AgenticOpsEval (arXiv 2606.29193, 28 Jun 2026, Tsinghua / Nankai, Dan Pei group [preprint]):** the AIOps2025 and RCA100 datasets, with over 500 expert-labelled cases on HipsterShop and the OTel Demo across five fault categories. It scores Localization, Identification (fault type) and Reason (evidence grounding). Agent numbers were not in the abstract. Data: aiops.cn/gitlab/aiops-live-benchmark/agenticopseval. — [arXiv abs](https://arxiv.org/abs/2606.29193)

**Trajectory and process studies**
- **Lu, Fang et al. (arXiv 2608.21310, v2 9 Oct 2026 [preprint]):**
  - Setup: 5,000 trajectories on RCABench from 9 frameworks × 2 backbones.
  - Correct localization can hide wrong causal reconstruction.
  - Failures cluster as *omitted evidence*, *misinterpreted evidence* and *unsupported reasoning*. Failing runs drift to unrelated services or repeat shallow queries.
  - A lightweight defense raised Acc@1 by **3.5–35.1 pp** in every configuration.
  
  — [arXiv abs](https://arxiv.org/abs/2608.21310)
- **OpsHarness (arXiv 2608.25661, 26 Aug 2026, CUHK (Lyu) [preprint]):** a self-evolving harness around a general agent, with trajectory-contrast proposals and dual-gate verification. It reports **59.0% top-1**, **4.02× better than baseline RCA agents**, and +63.4% over a bare general agent (unclear whether relative or absolute). — [arXiv abs](https://arxiv.org/abs/2608.25661)

**New peer-reviewed LLM-RCA methods (numbers not in the abstracts)**
- **AMER-RCL** (agentic memory plus recursive reasoning) **[ICSE-SEIP'26]**: it claims about 16% higher accuracy than the second-best method and more than 3.5× faster batch inference than LLM baselines. The figures come from a search snippet; the abstract itself gives no numbers. — [arXiv 2601.02732](https://arxiv.org/abs/2601.02732)
- **SpecRCA** (hypothesize-then-verify) **[ICSE-NIER'26]**: evaluated on AIOps 2022. — [arXiv 2601.02736](https://arxiv.org/abs/2601.02736)
- **ThinkFL** (multi-stage GRPO reinforcement fine-tuning of *lightweight* LLMs) **[TOSEM'26]**: it claims latency "from minutes to seconds". — [arXiv 2504.18776](https://arxiv.org/abs/2504.18776)
- **KRCA** (Kuaishou, arXiv 2607.01788 v3 [preprint]): **AC@1 0.88** for service localization and **0.79** for failure type, at least 31% above the strongest baseline, with **77.3% less diagnosis time**. It has been in production for more than 6 months. — [arXiv abs](https://arxiv.org/abs/2607.01788)

### Inferences
- **What "SOTA" means now depends on the metric.**
  - Service-level top-1 with a frontier model and a free-form harness: 75–89%.
  - Exact multi-cause set (OpenRCA 2.0): about 21–29%.
  - Grounded causal path: about 52–72% PR, with Edge F1 about 43%.
  - Realistic oncall with vague reports: 10–25%.
  
  A credible 2026 paper must report more than AC@1.
- **The RCAtlas result is strongest evidence that "hand-crafted agent pipelines" are a dead end**, but it rests on the 90-case core set, cloud-hosted 2026 frontier models, and reimplemented baselines. It does **not** show that small local models work. MiMo-V2.6-Pro and GPT-6 Luna, the weaker models, already lose 10–20 points.
- **Benchmark leakage is a live concern for LLM results.** The Codex rules explicitly forbid trying to identify the source dataset, and public RCAEval/OpenRCA data may be in pretraining corpora. No paper quantifies contamination.
- **For a laptop-only system, LLM-first RCA is not viable as the primary ranker.** Even the cheapest strong runs need 45–277 s and cloud APIs. SREGym's Kimi K2.5 (open weights) is the closest open-model data point, at 41.3% diagnosis and 674 s to diagnose.

### Gaps
- An "Opus 4.5 27% / Opus 4.6 35% on OpenRCA" figure appeared only in a search summary of an unidentified GitHub project or blog. It is **unverified** and may use a different harness. — [search result: aurorasre.ai blog](https://www.aurorasre.ai/blog/ai-sre-accuracy-benchmarks) **[search-summary]**
- No primary numbers were retrieved for AMER-RCL, SpecRCA, ThinkFL, EviRCA's model names, OpsHarness's benchmarks, or AgenticOpsEval's agent results.
- No new ITBench-SRE leaderboard (beyond the 13.8% in the earlier notes and the ITBench-AA figure) or AIOpsLab primary per-task table was found.
- No study evaluates ≤8B open-weight models running locally on RCAEval or OpenRCA. ThinkFL is the closest, but its base-model size was not retrieved.

---

## Q3. Hybrid designs (statistical/causal scoring + LLM reasoning or verification): which give the best accuracy *and* trustworthiness?

### Takeaway
The best-documented hybrid pattern in 2026 is **"deterministic candidate generation or evidence extraction → LLM reranks or verifies over compact evidence"**:
- **GALA+ (ASE'26):** a statistical STRIX prior plus a graph-bounded LLM agent reaches **74.44 / 73.33 AC@1** on OB / TT, against 66.67 for the best non-LLM baseline in its harness, at **USD 0.003–0.26 per incident**.
- **DecompRCA (NeurIPS'26):** a statistical retriever plus a single listwise LLM rerank beats the best of 9 baselines on all 6 suites, by **+7 to +18 points** when a short system-description document is supplied.
- **EviRCA:** deterministic "evidence cards" plus read-only tools give 40.6–43.9% on OpenRCA, against at most 15.2% before, with 15–26× fewer tokens.

The main counter-evidence is RCAtlas: when candidate generation is too narrow, a hybrid caps itself (DecompRCA's pool held the true cause in only 57.8% of cross-benchmark cases). Raw-data free-form agents then win.

### Cited Findings
- **GALA+ architecture** — [arXiv HTML](https://arxiv.org/html/2608.08968v1)
  - **STRIX** builds a weighted service graph from traces and scores each service on three dimensions:
    - **Instability** = p99/p50 latency ratio.
    - **Centrality** = PageRank × (1 + in-degree)/(1 + out-degree).
    - **Impact** = TotalLatency × (share of the service's average latency *not* explained by its slowest callee).
  - The three rankings are fused by **Reciprocal Rank Fusion (k = 60)**, so the scores need no calibration.
  - The LLM agent then does a graph-bounded investigation with localized multi-modal evidence and outputs ranked diagnoses, a summary and stratified actions.
  - Default backbone: GPT-4.1-mini at temperature 1.0. Also tested: gemini-2.5-flash, claude-sonnet-4-5, GPT-4.1, deepseek-v3.1, Qwen3-Next-80B-A3B and llama-4-maverick (open models served via Together AI).
  - **Cost per incident (OB):** llama-4-maverick USD 0.003, Qwen3-80B 0.015, GPT-4.1-mini 0.022, gemini-2.5-flash 0.030, deepseek-v3 0.044, gpt-4.1 0.110, claude-sonnet-4-5 0.255.
  - **Latency:** 52.9 s (OB) and 63.2 s (TT) per incident; 32.7K and 90.4K tokens.
  - **LLM baselines in the same harness (AC@1, OB / TT):** Flow-of-Action 48.35 / 47.78, ReAct 44.44 / 24.44, GALA v1 38.89 / 41.94, RCA-Agent 20.00 / 32.22, mABC 13.33 / 12.22, GraphRAG 21.35 / 7.78.
  - **Code is not released** (industrial agreement); a technical-report repo is at github.com/EvanTian233/GALA-for-RCA.
  - Evaluation includes **SURE-Score**, a rubric co-developed with SREs, plus an independent human SRE evaluation.
- **DecompRCA design**
  - A multi-signal statistical retriever, then **one listwise LLM call** to rerank, with no causal graph and no labels. Run via the Groq API at T = 1.0; the model is not named in the README.
  - It matches or beats the best of 9 baselines on all 6 suites, by up to +12 top@1. With identical candidates plus a short system-description document, the reranker leads the best baseline by **+7 to +18 points on every benchmark**.
  - Licence MIT. Python 3.10. PC/FCI baseline graphs take hours on RE1-TT and are cached.
  
  — [arXiv abs](https://arxiv.org/abs/2609.36686); [GitHub](https://github.com/cruiseresearchgroup/DecompRCA)
- **EviRCA:** "decouples deterministic evidence extraction from LLM reasoning". A system-agnostic extractor turns metrics, traces and logs into compact multimodal *evidence cards*. The LLM sees only the cards, through a few predefined **read-only** tools, and never touches raw telemetry or runs code. The authors find the bottleneck is "judging extracted evidence rather than searching for it", and accuracy depends heavily on extraction quality. — [arXiv abs](https://arxiv.org/abs/2609.19825)
- **KRCA:** API-level drilldown → a skeleton causal graph from anomalous metrics as a "high-recall structural prior" → a memory-augmented multi-agent LLM that *verifies* causality and writes the report. It reports 0.88 AC@1 in Kuaishou production. — [arXiv abs](https://arxiv.org/abs/2607.01788)
- **SpecRCA:** a hypothesis-drafting module plus a parallel root-cause verifier (hypothesize-then-verify) **[ICSE-NIER'26]**. — [arXiv abs](https://arxiv.org/abs/2601.02736)
- **DeltaRCA:** the LLM reads *code changes*, and its output only re-weights a deterministic SBFL propagation (63% Top-1 / 79% Top-3). — [ASE'26 DOI](https://doi.org/10.1145/3832783.3837424) **[search-summary]**
- **Counter-evidence (RCAtlas):** DecompRCA scores 28.5% PR@1 cross-benchmark (capped by 57.8% candidate recall), below the one-shot LLM (65.3%) and NSigma (38.9%). Simple harnesses "free to look" at the raw data win. — [arXiv HTML](https://arxiv.org/html/2610.35767)

### Inferences
- **Hybrid rule 1 (recall first).** The deterministic stage must be tuned for *recall*: report Retrieval@K with K of about 5–15 and aim for ≥98% on RCAEval, as DecompRCA shows is achievable. The precision step can then be a deterministic reranker (PRISM-style) with an optional LLM verifier. A narrow candidate set is the single biggest hybrid failure mode.
- **Hybrid rule 2 (evidence cards, not raw data).** EviRCA and GALA+ both show that giving the LLM compact, pre-computed evidence cuts tokens 15–26× and keeps it from hallucinating data. This is the trustworthiness argument for Veyltrace's "LLM narrates over an evidence table" design, and it makes the LLM step laptop-feasible.
- **Hybrid rule 3 (system description).** DecompRCA's +7 to +18 points from a short system-description document is the cheapest documented LLM gain. For Veyltrace the equivalent is a per-system YAML of services, roles, dependencies and resource limits fed to the narrator or verifier.
- **For a deterministic-decision-path project** (the Veyltrace AGENTS.md rule), the defensible position is:
  - deterministic retrieval + reranking + calibrated set as the *decision*;
  - an LLM used only for (a) narration and (b) an *optional, ablated* "verifier" whose output is logged but never changes the ranking.
  
  The paper can then report "LLM-verifier agreement" as a trust metric without putting AI in the decision path.

### Gaps
- No paper reports the *calibration* of hybrid outputs (whether LLM-verified confidence predicts correctness).
- No hybrid has been evaluated with a ≤14B local model on RCAEval. GALA+'s cheapest open model (llama-4-maverick) is a large MoE served in the cloud.
- No head-to-head of GALA+ and PRISM/TORAI exists. GALA+'s baselines omit both.

---

## Q4. Fine-grained localization: root-cause indicator/metric, fault type, node vs pod vs service, code- and change-level

### Takeaway
Fine-grained output is where every method, classical or LLM, is still weak, and it is a credible place for Veyltrace to add value. The best published numbers:
- **Fault type:** KRCA 0.79 AC@1 (industrial).
- **Indicator level:** TORAI 0.46–0.59 Top-1 (in the earlier notes).
- **Change level:** ChangeRCA 85% HR@1 on WeChat; DeltaRCA 63% Top-1 using code-change understanding.
- **Code-level from issue reports:** COCA reports only relative gains.

LLM agents identify the right *node* but blame the wrong *pod/service* level, and they score Edge F1 of only about 43% on propagation paths.

### Cited Findings
- **KRCA:** failure-type classification AC@1 **0.79**, against 0.88 for service localization. — [arXiv abs](https://arxiv.org/abs/2607.01788)
- **CCLH (Nov 2025):** formalizes RCL and FTI and argues a **sequential** design (localize, then classify type) is more practical than joint learning. — [arXiv](https://arxiv.org/pdf/2511.17566). A 2026 cascaded GNN does joint localization and fault-type identification for edge computing. — [arXiv 2603.01447](https://arxiv.org/pdf/2603.01447)
- **AgenticOpsEval** scores *Identification* (fault type) and *Reason* (evidence grounding) separately from Localization, across five fault categories (resource, network, runtime, middleware/DB, application logic). — [arXiv abs](https://arxiv.org/abs/2606.29193)
- **OpenRCA 2.0:** Node F1 averages 62.2% but Edge F1 only 43.4% across 11 LLMs, so agents find the involved services more reliably than the propagation edges. — [arXiv HTML](https://arxiv.org/html/2606.27154v2)
- **RCAtlas:** on node-level faults, agents mention the true node in 85–90% of runs but mostly blame a pod or service on it (a granularity-mapping error). — [arXiv HTML](https://arxiv.org/html/2610.35767)
- **COCA [ICSE 2025]:** retrieves relevant code and reconstructs execution paths from issue reports, then prompts an LLM. It reports **+28.3% root-cause localization and +22.0% summarization** (relative, on 5 distributed systems). Removing path reconstruction hurts performance. — [arXiv 2503.23051](https://arxiv.org/abs/2503.23051); [ACM DL](https://dl.acm.org/doi/10.1109/ICSE55347.2025.00234)
- **ChangeRCA [FSE 2024]:** "root cause change analysis" for change-induced incidents, with **85% HR@1 and 96% HR@3** on WeChat plus a simulated dataset. — [FSE'24 page](https://2024.esec-fse.org/details/fse-2024-research-papers/3/ChangeRCA-Finding-Root-Causes-from-Software-Changes-in-Large-Online-Systems) **[search-summary]**
- **DeltaRCA [ASE 2026]:** code-change-aware trace SBFL, 63% Top-1 / 79% Top-3 on 200 injected faults. — [DOI](https://doi.org/10.1145/3832783.3837424) **[search-summary]**
- **ORCA-bench:** source-code access improves RCA accuracy and lowers hallucination for every model tested. — [arXiv abs](https://arxiv.org/abs/2607.28545)
- **EventADL [FSE'26]** (earlier notes) remains the only RCAEval-integrated method for *events* (API calls, config changes). It is now runnable in RCAEval (Jul 2026). — [RCAEval README](https://github.com/phamquiluan/RCAEval)

### Inferences
- RCAEval labels only service and fault type (and indicator for some), so a Veyltrace v2 paper can credibly add three outputs:
  - a **fault-type label** (resource / network / code; CPU / MEM / DISK / SOCKET / DELAY / LOSS / F1–F5) from a deterministic signature table, reporting fault-type accuracy against RCAEval's labelled types;
  - a **root-cause indicator** (metric name), compared with TORAI's 0.46–0.59 and BARO's 0.09–0.40;
  - a **"granularity-consistent" answer** (node → pod → service mapping) to avoid the RCAtlas misattribution.
- **Change-awareness on a laptop:** RCAEval has no deploy or config events. Change-aware RCA could be demonstrated only on a self-built demo (e.g. Online Boutique with a staged bad deploy). That is good for the demo but not benchmarkable against published numbers within a month.

### Gaps
- No public benchmark with both fault injection *and* deployment/config-change ground truth for microservices was found. ChangeRCA's WeChat data is not public.
- DeltaRCA's and COCA's absolute numbers and datasets were not verified from full text.
- No 2025–2026 paper reports fault-type accuracy on RCAEval specifically.

---

## Q5. Usable open-source implementations (repo, licence, language, maintenance) as of Oct 2026

### Takeaway
RCAEval is the central, actively maintained harness: MIT, Python, updated Sep 2026, with Hugging Face Parquet data and the new chance and decomposition flags. It bundles BARO, CIRCA, RCD, MicroCause, ε-Diagnosis, RUN, CausalRCA, MSCRED, TraceRCA, MicroRank, multi-source BARO/RCD/CIRCA, TORAI and EventADL, but **no LLM methods and no PRISM**. DecompRCA (MIT) and SREGym are the main new runnable repos. GALA+, PRISM and OpenRCA 2.0 have **no released code** as of this research.

### Cited Findings
- **RCAEval** — github.com/phamquiluan/RCAEval — [README](https://github.com/phamquiluan/RCAEval)
  - Licence: MIT for the authors' code and the datasets. Bundled code keeps its own licence: BARO MIT, CIRCA BSD-3, ε-Diagnosis BSD-3, MicroCause Apache-2.0, RCD MIT. **CausalRCA and RUN have no licence.**
  - Changelog:
    - Sep 2026: decomposition flags (NeurIPS'26), chance-level baseline, CIRCA/PageRank column-order fix.
    - Aug 2026: all 9 datasets (735 cases) on Hugging Face as Parquet (about 3.4 GB), with `read_metrics/logs/traces` helpers.
    - Jul 2026: multi-source methods runnable via `main.py`; EventADL added.
    - Apr/Jun 2026: TORAI (`fse26` branch).
  - Requirements: at least 8 cores, 16 GB RAM, about 50 GB disk; Ubuntu 22.04/24.04; Python 3.14 recommended (3.12/3.13 work). **Multi-source RCD and TORAI need a separate Python 3.8 environment.** Zenodo zips are about 5.2 GB and expand to about 38 GB.
- **DecompRCA** — github.com/cruiseresearchgroup/DecompRCA — MIT, Python 3.10. It pins RCAEval commit `fb8f20a6…` for BARO and uses `sfr-pyrca==1.0.1`. LLM runs need a Groq API key; baselines need none. — [GitHub](https://github.com/cruiseresearchgroup/DecompRCA)
- **SREGym** — github.com/SREGym/SREGym — a live Kubernetes benchmark with 90 problems, described as actively maintained. The code licence was not stated in the retrieved text. — [arXiv HTML](https://arxiv.org/html/2605.07161v1)
- **OpenRCA 1.0** — github.com/microsoft/OpenRCA — active issue tracker, with a maintainer reply on 12 Oct 2026. — [issue #23](https://github.com/microsoft/OpenRCA/issues/23)
- **OpenRCA 2.0:** release promised "upon acceptance" (data CC-BY-SA 4.0, code Apache 2.0). — [arXiv HTML](https://arxiv.org/html/2606.27154v2)
- **RCAtlas:** case list, labels and code are at ufile.io/5ww9iyfb (a temporary file host); about 11 GB of converted data is planned. — [arXiv HTML](https://arxiv.org/html/2610.35767)
- **ORCA-bench data:** hub.harborframework.com/datasets/orca-bench/orca-bench. — [arXiv abs](https://arxiv.org/abs/2607.28545)
- **AgenticOpsEval data:** aiops.cn/gitlab/aiops-live-benchmark/agenticopseval. — [arXiv abs](https://arxiv.org/abs/2606.29193)
- **GALA+:** source not released (industrial agreement); a technical-report repo is at github.com/EvanTian233/GALA-for-RCA. — [arXiv HTML](https://arxiv.org/html/2608.08968v1)

### Inferences
- **The fastest credible baseline set for a laptop** is RCAEval `main.py` with BARO, multi-source BARO, CIRCA, RCD, TraceRCA, MicroRank and NSigma (ε-Diagnosis and NSigma are in the classical family), plus SimpleRCA and PRISM reimplemented from their papers, with `--report-chance` and `--report-decomposition` turned on.
- Avoid TORAI and multi-source RCD unless someone owns the Python 3.8 environment; they also take 13–21 s per case.
- Use the Hugging Face Parquet copy (3.4 GB), not the 38 GB Zenodo extraction, on laptops.
- Pin the RCAEval commit and cite the Sep 2026 CIRCA/PageRank fix when comparing with pre-fix numbers.

### Gaps
- No licence or maintenance status was verified for MicroRank, TraceRCA, Nezha or Eadro repos in this pass; the earlier notes give their URLs.
- Whether DecompRCA's reranker can be pointed at a local OpenAI-compatible endpoint (e.g. Ollama) was not checked.

---

## Q6. Open gaps a new laptop-scale system could credibly claim (calibration/abstention, multi-fault, unseen systems, missing telemetry, evaluation)

### Takeaway
The clearest unclaimed gap remains **calibrated uncertainty and abstention for RCA**. Targeted searches found no microservice-RCA paper using conformal sets, selective prediction or risk–coverage curves, and RCAtlas scores abstentions as wrong. Other credible claims:
- **retrieval/reranking-decomposed and chance-corrected evaluation** (now supported by RCAEval but rarely reported);
- **robustness to missing telemetry** (mABC undetermined on 42/89 trace-poor cases);
- **multi-fault cases** (RCAtlas excluded 20; OpenRCA 2.0 exact-set accuracy is only 20.7%);
- **generalization to unseen failures** (SREGym E2E 63.7% → 17.9%).

### Cited Findings
- **Calibration and abstention:** searches found conformal *abstention* work for LLM QA, including "Mitigating LLM Hallucinations via Conformal Abstention" and 2026 follow-ups, but **nothing applied to incident triage or RCA**. A 2026 scoping review notes that logit-free conformal methods for black-box LLMs are only partly solved. — [arXiv 2405.01563](https://arxiv.org/pdf/2405.01563); [Phil. Trans. A 2026 review](https://doi.org/10.1098/rsta.2026.0061); [UQ for LLM agents, arXiv 2609.07395](https://arxiv.org/pdf/2609.07395)
- **RCAtlas:** "the paper does not analyse hallucination or calibration, and it reports no confidence scores"; unanswered cases score zero, so abstaining is penalized. — [arXiv HTML](https://arxiv.org/html/2610.35767)
- **Grounding:** outcome-only evaluation hides ungrounded diagnoses (76.0% AnySvc vs 61.5% Path Reachability). — [OpenRCA 2.0](https://arxiv.org/html/2606.27154v2). Correct localization can coexist with wrong causal reconstruction. — [arXiv 2608.21310](https://arxiv.org/abs/2608.21310)
- **Multi-fault:** RCAtlas excluded 20 multi-fault cases. — [arXiv HTML](https://arxiv.org/html/2610.35767). SREGym includes concurrent and correlated failures, and performance "drops on lower-layer and compound failures". — [arXiv HTML](https://arxiv.org/html/2605.07161v1). ORCA-bench varies co-occurring faults. — [arXiv abs](https://arxiv.org/abs/2607.28545). OpenRCA 2.0's exact root-cause set is 6.8–29.4% across models. — [arXiv HTML](https://arxiv.org/html/2606.27154v2)
- **Unseen systems and failures:** Stratus/Sonnet E2E 63.7% on ported problems vs 17.9% on SREGym-only failures. Noise lowers diagnosis for every agent (e.g. Claude Code 72.6 → 62.6). — [arXiv HTML](https://arxiv.org/html/2605.07161v1). DecompRCA retrieval drops from 98–100% (microservices) to 35–64% (industrial control). — [GitHub](https://github.com/cruiseresearchgroup/DecompRCA)
- **Missing telemetry:** mABC was undetermined in 42/89 RCAtlas cases, mostly on sources with few or no traces. — [arXiv HTML](https://arxiv.org/html/2610.35767). TORAI's blind-spot results are in the earlier notes.
- **Benchmark shortcuts:** OpenRCA's no-telemetry constant predictor gets 7.46% vs 11.34% (p = 0.06). — [issue #23](https://github.com/microsoft/OpenRCA/issues/23). On RCAEval, the 5-service prior gives Avg@5 0.488 (earlier notes), and RCAEval now ships Chance@5/Lift@5. — [RCAEval README](https://github.com/phamquiluan/RCAEval)
- **Two-sided deviations:** one-sided scorers miss traffic-drop root causes (RCAtlas). LLMs show "presence bias" toward silent services (OpenRCA 2.0). — [RCAtlas](https://arxiv.org/html/2610.35767); [OpenRCA 2.0](https://arxiv.org/html/2606.27154v2)

### Inferences
Claims a 3-person, 1-month, laptop-only Veyltrace v2 could credibly make, ranked by novelty × feasibility:
1. **"First calibrated RCA."** A conformal top-k̂ candidate set with Mondrian classes per system or fault family, plus a selective-prediction risk–coverage curve and AURC, reported on RCAEval RE1/RE2/RE3. No prior RCA paper reports either.
2. **Decomposed, chance-corrected evaluation.** Report Retrieval@K, Rerank@1, Lift@5, Top-1 and fault-type accuracy, with all baselines in one pinned harness. This addresses the cross-paper variance in Q1 directly.
3. **Recall-first deterministic retriever + deterministic reranker** (PRISM internal/external, onset precedence, two-sided deviations, trace SBFL), with the LLM only as narrator plus an optional logged verifier. The design follows the GALA+/EviRCA/DecompRCA pattern but keeps the decision path deterministic and runs in milliseconds.
4. **Missing-modality robustness.** Leave-one-modality-out curves (metrics only, plus logs, plus traces), using Sock Shop's missing traces as a natural experiment.
5. **Grounded explanation metric.** Check that every claim in the LLM narrative maps to a row in the evidence table (a "grounding rate"). This answers OpenRCA 2.0's and the trajectory study's critique cheaply.

Multi-fault and change-aware RCA are real gaps, but RCAEval has no multi-fault or change ground truth. Claiming them would require building new injected scenarios, which is risky in one month.

### Gaps
- No RCA-specific calibration paper was found, despite targeted searches, so the novelty claim rests on absence of evidence: re-check Google Scholar before submission.
- No benchmark of local ≤14B models for RCA narration or verification quality was found.
- The DecompRCA per-suite numbers, the ThinkFL base model, and EviRCA's two LLMs need the full PDFs.
