# 11 · Research paper plan

> **Status:** v1.0-draft · **Owner:** Aniket Kumar (lead) · **Last updated:** 2026-10-30
> Architecture: [02](02-architecture.md). Evaluation protocol, splits and the experiment matrix: [04-evaluation-protocol](04-evaluation-protocol.md) (04 wins on protocol details; 02 wins on architecture). Requirements and v1.0 targets: [01 §9](01-vision-and-requirements.md).
> Until `bench/results/` exists, every claim below is a **hypothesis** or a **target**. No number in the paper may come from anywhere except `bench/results/` produced by a committed config ([AGENTS.md §4.8](../AGENTS.md)). Literature numbers are quoted with their source and are context, not comparisons, unless we re-ran the method ourselves.

## 1. Working titles and abstract draft

Working titles (pick at M4, when results are known):

1. *Propose Freely, Decide Deterministically: Verifiable and Calibrated Root-Cause Analysis for Microservices on a Laptop* (from the [report][rep]).
2. *Veyltrace: Verifiable, Change-Aware Root-Cause Analysis with Coverage Guarantees* (from [novel_building_blocks §Q10][nb]).
3. *When Should an RCA System Say "I Don't Know"? Code-Verified LLM Proposals and Conformal Candidate Sets for Microservice Incidents.*

Use title 1 if RQ2 (proposer) is the strongest result, title 2 if RQ3 and RQ4 are, title 3 for a workshop or short paper.

**Abstract draft** (bracketed items are filled from `bench/results/` at M4; claims stay hypotheses until then):

> Large language model (LLM) agents now name the faulty service in most cases of some public root-cause analysis (RCA) benchmarks, yet stricter tasks, unseen failures and planted decoys show that their answers cannot be used without checking. We present Veyltrace, an open RCA engine for microservices in which statistical rankers and a local open-weight LLM only *propose* hypotheses and a deterministic verifier *decides*. Every claim the LLM makes is a named predicate that code re-evaluates on stored telemetry for every candidate, so the LLM can surface discriminating evidence but cannot argue for its favourite. The verifier returns a split-conformal candidate set with a target coverage of 90%, may answer *no fault* or *inconclusive*, and seals each verdict in a receipt from which anyone can replay it to the same hash. We hypothesise that (i) the deterministic pipeline is not worse than the best simple baseline on any RCAEval RE2 system, (ii) code-verified proposals from a ≤ 10B local model do not lower accuracy and resist planted decoys, (iii) the candidate sets reach nominal coverage within a benchmark family, and (iv) the design is robust to alert-time shifts, missing telemetry and decoy change events. We evaluate per system with oracle and detected alert times, against chance, N-Sigma, BARO and an alert-count baseline, using clustered paired statistics, and we release all per-case outputs. [Results: RQ1–RQ6 headline numbers.] Veyltrace runs on a 16 GB laptop in [p95] seconds per case without a GPU.

## 2. Contributions

Ranked by evidence per hour of work in the [report][rep] ("Four contributions survive a month on laptops"). C1–C3 form the core paper; C4 is a section if week 3 allows; C5 is a second paper.

| ID | Contribution | Evidence it matters | Novelty status (hedged) | Measured by |
|---|---|---|---|---|
| **C1** | **Propose–verify architecture** with symmetric claim evaluation and replayable receipts. Rankers and an LLM propose; a fixed decision function over code-recomputed predicates decides; every LLM-requested predicate is evaluated for every pool candidate; verdicts replay from an in-toto receipt and a cassette. | LLM verifiers raised Acc@1 by 3.5–35.1 pp in all 14 configurations of one study, but did not fix "semantics misread" errors ([verified_agents §Q2][va]); one false sentence steered models to a decoy in 21–42% of flagged cases ([benchmarks_and_testbed §Q2][bt]) | No paper found isolates a *purely deterministic* verifier over LLM proposals ([verified_agents §Q2][va]); the receipt combination (PROV-style trace, hash chain, in-toto) is a design inference, not prior art ([verified_agents §Q7][va]) | Proposer lift, decoy-rejection rate, permutation invariance, Tier-1 replay rate (RQ2, RQ6) |
| **C2** | **Conformal, set-valued RCA with `NO_FAULT` and abstention.** Split-conformal candidate sets over the verified score, a `NO_FAULT` status calibrated on normal windows, and risk–coverage reporting. | Every PetShop method named false root causes during normal operation ([novel_building_blocks §Q7][nb]); RCAtlas scores abstention as wrong ([sota_methods §Q6][sota]) | **To our knowledge, based on searches up to October 2026, no microservice RCA paper outputs conformal candidate sets with a no-fault option.** This rests on absence of evidence; three close works must be read in full before submission (CONCH/CROC, the OSDI'26 "Abstention Protocol", LM-PACE; see §4.5 and §11) | Coverage, set size, abstention rate, AURC, LOSO coverage gap (RQ3) |
| **C3** | **Decomposed, onset-robust, per-system evaluation with released per-case outputs.** Retrieval@K vs Rerank@1, chance floor, per-system clustered statistics, oracle vs detected alert time, telemetry ablation. | 0 of 23 RCA papers released per-case outputs; pooled leaderboards pick the worse method on up to 5 of 11 subsystems; a 2-minute onset shift dropped N-Sigma from 0.80 to 0.07 AC@1 on RE2 ([benchmarks_and_testbed §Q2][bt]) | The tools exist (RCAEval `--report-decomposition`, `--report-chance`) but are rarely reported together ([report][rep]). Reviewers may call this "just evaluation" unless paired with C1–C2 | All RQs; released `per_case.csv` |
| **C4** | **Change-aware evidence channel stress-tested with decoy changes (RCAEval-C).** Change proximity and changed-vs-peer contrast as evidence; a benchmark extension that adds a true change with probability π plus decoy changes. | Binary and config pushes triggered 68% of Google's 2010–2017 outages; no public microservice RCA benchmark carries change events ([novel_building_blocks §Q5][nb]) | No public microservice RCA benchmark with change events was found. The change logs in RCAEval-C are **synthetic**; live-lab changes are the backup evidence | AC@1 vs π and decoy rate; "blame latest change" baseline (RQ4) |
| **C5** (second paper) | **VeylLab dataset**: laptop-collected, leakage-free, with published injection parameters, impact validation, no-fault and noise controls. | RCAEval's injection parameters were never published; the FSE'26 benchmark kept 1,430 of 9,152 injections after validation ([benchmarks_and_testbed §Q5][bt]) | Fills a reproducibility gap; not on the month-one critical path | Acceptance rate, case count, baseline per-case outputs |

## 3. Research questions and hypotheses

RQ numbering matches [04](04-evaluation-protocol.md). Hypotheses are stated before results; the pre-registration commit (§8) freezes them. "Target" thresholds come from [01 §9](01-vision-and-requirements.md).

| RQ | Question | Hypotheses | Main experiments (rows of [04 §6](04-evaluation-protocol.md)) |
|---|---|---|---|
| **RQ1 Accuracy** | How accurate is the AI-off pipeline per system, against honest floors and reproduced baselines, and where does it fail: retrieval or re-ranking? | **H1a** AI-off AC@1 is not significantly worse than the best reproduced simple baseline on any RE2 system. **H1b** Pooled over RE2, the paired AC@1 difference is positive (MDD ≈ 7 points at 270 cases). **H1c** Retrieval@5 ≥ 0.90 per RE2 system, so most errors are re-ranking errors. | RQ1 rows: RE2 and RE3 per system, oracle and detected protocols; each Causatrix ranker alone; fusion ablation |
| **RQ2 Proposer lift** | Does a ≤ 10B local LLM, restricted to proposing code-verified predicates and candidates, change verified accuracy? Can it be steered by decoys? | **H2a** Proposer lift (AC@1 AI-on minus AI-off) is ≥ 0; its CI is not entirely below 0. **H2b** Planted decoy proposals change the top-1 in ≤ 5% of cases. **H2c** The verdict is invariant to proposal order (100%). Exploratory: `investigate` vs `brief`; 9B vs 4B. | RQ2 rows: `brief` × 3 seeds on RE2; decoy-proposal arm; permutation arm; `investigate` on a stratified subset |
| **RQ3 Calibration** | Do conformal sets reach nominal coverage within a benchmark family, how does coverage degrade across systems, and is abstention informative? | **H3a** Within-family test coverage ≥ 1 − α − 0.05 at α = 0.10. **H3b** Mean set size ≤ 3. **H3c** AURC of the verified score is lower than that of the ranker's fused score. **H3d** (expected negative) Leave-one-system-out coverage falls below nominal; we report the gap. | RQ3 rows: calibration per family; LOSO; `NO_FAULT` on no-fault windows |
| **RQ4 Robustness** | How does accuracy change under alert-time shifts, missing telemetry, decoy changes, and (for the LLM arm) anonymised service names? | **H4a** AC@1 drops ≤ 10 points under ±60/±120 s alert shifts. **H4b** Under telemetry ablation the status moves toward `INCONCLUSIVE` instead of producing wrong `CONFIRMED` verdicts (≥ 90% of `CONFIRMED` correct per cell). **H4c** In RCAEval-C, the change channel raises AC@1 when a true change is present, and decoys alone cost ≤ 5 points. **H4d** Name anonymisation changes LLM-arm accuracy (contamination probe; direction not predicted). | RQ4 rows: shift grid; ablation matrix; RCAEval-C (π × decoy rate); anonymisation |
| **RQ5 Cost** | What do the deterministic and AI paths cost on CPU laptops? | **H5** Deterministic p95 ≤ 30 s and ≤ 3 GB per RE2 case; the AI path adds ≤ 180 s (Relentra `brief`) plus ≤ 60 s (narration) p95 ([02 §9](02-architecture.md)). | RQ5: timings and RSS collected on every run; `llama-bench` per laptop |
| **RQ6 Replay** | Do verdicts replay exactly, and how often does re-generating the LLM output reproduce it? | **H6a** Tier-1 replay reproduces `verdict_hash` on 100% of recorded cases on a second laptop and in CI. **H6b** (measured only) Tier-2 regeneration match rate on a fixed subset. | RQ6 rows: cross-laptop replay; regeneration subset |

## 4. Related-work map

Year, venue/ID and URL are copied from the research notes. Flags: **[preprint]** arXiv or similar, not peer-reviewed; **[search-summary]** numbers seen only in a search-engine summary; **[snippet]** paper seen only as a search snippet; **[v1 notes]** URL from the v1 research notes, which are kept in the team's local archive and not in the repository (verify against the primary source before publication); **[fill]** a field the notes do not give, to be filled from the primary source before writing. Numbers in the "Differs" column are context from the cited paper, not our comparisons.

### 4.1 Statistical and causal RCA

| Work | Year | Venue / ID | URL | Flag | How Veyltrace differs |
|---|---|---|---|---|---|
| BARO | 2024 | FSE'24; arXiv 2405.09330 | https://arxiv.org/html/2405.09330 | [v1 notes] | One of our rankers (`baro_rs`) and a baseline. We add two-sided deviations (BARO and NSigma score only upward deviations, so traffic drops rank last, [sota_methods §Q1][sota]), verification and candidate sets. |
| RCD | [fill] | [fill] | [fill] | not in notes | Discovery-style baseline (≈ 3–12 s per case, [novel_building_blocks §Q4][nb]). We use the observed call graph instead of learning one. |
| CIRCA | 2022 (from arXiv ID) | arXiv 2206.05871; venue [fill] | https://ar5iv.labs.arxiv.org/html/2206.05871 | [v1 notes] | Its numbers are harness-sensitive: 0.67 AC@1 (probably RE2-OB) in GALA+'s harness vs 17.8% PR@1 in RCAtlas; RCAEval fixed a column-order bug in Sep 2026; 3,792 s per Train Ticket case ([sota_methods §Q1][sota], [report][rep]). We re-run in our own pinned harness. |
| RUN | 2024 | AAAI 2024; arXiv 2402.01140 | https://arxiv.org/pdf/2402.01140 | | Neural Granger discovery; 1,078–4,938 s per case and often near random ([novel_building_blocks §Q1, §Q4][nb]). Not used. |
| PRISM | 2026 | arXiv 2601.21359 | https://arxiv.org/html/2601.21359 | [preprint], no code | Our `prism_m` ranker re-implements its internal/external score. PRISM reports 0.68 / 0.91 / 0.87 (Top-1 / Top-3 / Avg@5) on 735 RCAEval cases ([report][rep]). We add verification, sets, abstention and the change channel. |
| N-Sigma | — | RCAEval baseline; no standalone paper in notes | https://github.com/phamquiluan/RCAEval | | Honest floor and a ranker (`nsigma`). 38.9% PR@1 on RCAtlas, best non-LLM ([sota_methods §Q1][sota]). |
| SimpleRCA (alert count) | 2025 | FSE'26 (Fang et al.); arXiv 2510.04711 | https://arxiv.org/abs/2510.04711 | | Floor baseline: matches or beats SOTA on Nezha, Eadro and RCAEval ([benchmarks_and_testbed §Q1][bt]). |
| TORAI | 2026 | FSE 2026; arXiv 2604.13522 | https://arxiv.org/pdf/2604.13522 | | Multi-source RCA for call-graph blind spots; 13–21 s per case; needs a Python 3.8 env. Cited, re-run only if someone owns that env ([sota_methods §Q5][sota]). |
| DecompRCA | 2026 | NeurIPS 2026 Evaluations & Datasets; arXiv 2609.36686 | https://arxiv.org/abs/2609.36686 | | We adopt its Retrieval@K / Rerank@1 decomposition. Its re-ranker is one LLM call; ours is a deterministic verifier with the LLM only proposing. Its candidate pool held the true cause in only 57.8% of RCAtlas cases ([sota_methods §Q3][sota]). |
| ASE'24 causal-inference study ("How far are we?") | 2024 | ASE 2024; arXiv 2408.13729 | https://arxiv.org/html/2408.13729v1 | | Evidence for not doing full causal discovery (F1 0.1–0.54) ([novel_building_blocks §Q4][nb]). |
| IDI (in-distribution interventions) | 2025 | ICLR 2025; arXiv 2505.00930 | https://arxiv.org/abs/2505.00930 | | Basis of trial T8; IDI was evaluated on synthetic data and PetShop, not RCAEval ([novel_building_blocks §Q4][nb]). |
| PetShop | 2024 | CLeaR 2024 (PMLR 236); arXiv 2311.04806 | https://arxiv.org/html/2311.04806v2 | | Motivation for `NO_FAULT`: all methods emitted false root causes in normal operation ([novel_building_blocks §Q7][nb]). |

### 4.2 Trace, log and multi-source RCA

| Work | Year | Venue / ID | URL | Flag | How Veyltrace differs |
|---|---|---|---|---|---|
| MicroRank | [fill] | DOI 10.1145/3442381.3449905 | https://unpaywall.org/10.1145%2F3442381.3449905 ; https://github.com/IntelligentDDS/MicroRank | [v1 notes] | Spectrum scores as PageRank teleportation; our `graph_walk` ranker belongs to this family. |
| TraceRCA | [fill] | IEEE Xplore 9521340 | https://ieeexplore.ieee.org/abstract/document/9521340 | [v1 notes] | Spectrum-based trace RCA. Our `cp_sbfl` weights spectrum counts by critical-path self-time (a new combination, [novel_building_blocks §Q3][nb]). |
| Eadro | 2023 | ICSE 2023; arXiv 2302.05092 | https://arxiv.org/pdf/2302.05092 | [v1 notes] | Learned multi-task model; we train nothing. |
| Nezha | 2023 | ESEC/FSE 2023 | https://github.com/IntelligentDDS/Nezha | | Used as a cross-source dataset (101 cases, MIT) on the same systems as RCAEval ([benchmarks_and_testbed §Q1][bt]). |
| CRISP | 2022 | USENIX ATC 2022 | https://www.usenix.org/conference/atc22/presentation/zhang-zhizhou | | Critical-path analysis we reuse inside Signalyth and `cp_sbfl`; CRISP itself does not do spectrum localisation ([novel_building_blocks §Q3][nb]). |

### 4.3 LLM and agentic RCA

| Work | Year | Venue / ID | URL | Flag | How Veyltrace differs |
|---|---|---|---|---|---|
| RCAgent | [fill] | [fill] | [fill] | not in notes | Re-run in RCAtlas at 49.3% PR@1 ([sota_methods §Q2][sota]). An agent that decides; ours proposes. |
| RCACopilot | [fill] | arXiv 2305.15778; venue [fill] | https://ar5iv.labs.arxiv.org/html/2305.15778 | | Retrieval of similar incidents for root-cause *category*; up to 0.766 accuracy on Microsoft incidents ([novel_building_blocks §Q9][nb]). We use a fixed fault-class rule table. |
| mABC | 2024 (from arXiv ID) | arXiv 2404.12135 | https://arxiv.org/html/2404.12135v1 | [v1 notes] | Multi-agent voting; last or near last in two independent re-runs (15.6 PR@1; 42.6 Acc@1) ([verified_agents §Q1][va]). Avoided. |
| Flow-of-Action | 2025 (from arXiv ID) | arXiv 2502.08224; venue [fill] | https://arxiv.org/pdf/2502.08224 | | SOP-guided agent; its LLM judge declared a wrong root cause "found" after one round ([verified_agents §Q2][va]). We use no LLM judge in the decision path. |
| OpenRCA 1.0 | 2025 | ICLR 2025 | https://proceedings.iclr.cc/paper_files/paper/2025/file/d29b8d53678015079e1d245c023e49d2-Paper-Conference.pdf | | Best original agent 11.34%; a no-telemetry predictor scored 7.46% (p = 0.06) ([sota_methods §Q2][sota]). Our output contract keeps (service, fault class, onset) so it can be scored later. |
| OpenRCA 2.0 | 2026 | arXiv 2606.27154 | https://arxiv.org/html/2606.27154v2 | [preprint] | Exact root-cause set 20.7% mean across 11 LLMs; Edge F1 43.4% vs Node F1 62.2% ([sota_methods §Q2][sota]). Data unreleased. |
| RCAtlas / "Free to Look, Free to Reason" | 2026 | arXiv 2610.35767 | https://arxiv.org/html/2610.35767 | [preprint] | Simple frontier-model harnesses: mean PR@1 72.8% (SQL agent) and 77.2% (Codex harness) over three models, vs 38.9% for NSigma ([sota_methods §Q2][sota]; [verified_agents §Q1][va]). Cloud models only; abstention scored as wrong. Note: our notes disagree on whether model names are disclosed; quote harness-level means only, never model names or per-model runs. |
| DiagGuard (in "Beyond Fault Localization", Lu, Fang et al.) | 2026 | arXiv 2608.21310 | https://arxiv.org/html/2608.21310 | [preprint] | Its Verifier and Grounder are **LLM-based**: +3.5–35.1 pp Acc@1, but "semantics misread" did not improve ([verified_agents §Q2][va]). Our verifier is code. |
| SpecRCA | 2026 | ICSE-NIER'26; arXiv 2601.02736 | https://arxiv.org/html/2601.02736 | preliminary, one dataset | Non-LLM drafter + distilled 3B LLM verifier: R@1 61.34 at 9.89 s ([verified_agents §Q1][va]). The only small-model success; its verifier is still an LLM. |
| EviRCA | 2026 | arXiv 2609.19825 | https://arxiv.org/abs/2609.19825 | [preprint] | Evidence cards: 40.6–43.9% on OpenRCA with 15–26× fewer tokens ([sota_methods §Q2][sota]). Relentra's `brief` mode uses the same idea; we add code verification of the LLM's claims. |
| GALA+ | 2026 | ASE'26; arXiv 2608.08968 | https://arxiv.org/html/2608.08968v1 | code not released; benchmarks inferred | Statistical prior + graph-bounded LLM agent: 74.44 / 73.33 AC@1 on (probably) RE2-OB / RE2-TT ([sota_methods §Q3][sota]). The LLM decides; ours proposes. |
| LATS-RCA | 2026 | arXiv 2605.03505 | https://arxiv.org/html/2605.03505 | [preprint] | MCTS agent: 91.3% on LO2 but 9.1 min and 156K tokens per investigation ([verified_agents §Q1][va]). Not laptop-feasible; not used. |
| ARGUS | 2026 | arXiv 2608.23084 | https://arxiv.org/html/2608.23084 | [preprint]; single company, 10 scenarios | Sufficiency gate, "Unknown" instead of inferred values, confidence computed from tool-success ratios ([verified_agents §Q2][va]). Same spirit; we add symmetric predicate evaluation, conformal sets and replay. |
| KRCA (extra) | 2026 | arXiv 2607.01788 | https://arxiv.org/abs/2607.01788 | [preprint], industrial | LLM *verifies* a skeleton causal graph; 0.88 AC@1 in production ([sota_methods §Q3][sota]). |

### 4.4 Benchmarks and evaluation methodology

| Work | Year | Venue / ID | URL | Flag | Role for Veyltrace |
|---|---|---|---|---|---|
| RCAEval | 2024 (from arXiv ID) | arXiv 2412.17015; venue [fill] | https://arxiv.org/html/2412.17015 ; https://github.com/phamquiluan/RCAEval | [v1 notes] for the paper URL | Primary benchmark (735 cases, MIT); pin the commit; the Sep 2026 changelog added decomposition and chance flags and fixed CIRCA/PageRank ([sota_methods §Q5][sota]). |
| FSE'26 propagation-aware TrainTicket benchmark (Fang et al.) | 2025 | FSE'26; arXiv 2510.04711; Zenodo DOI 10.5281/zenodo.17105974 | https://arxiv.org/abs/2510.04711 | size, format, licence unverified | Hard set: 11 methods average 0.21 Top@1, best 0.37 ([benchmarks_and_testbed §Q1][bt]). Stretch dataset. |
| OpenRCA (1.0 / 2.0) | 2025 / 2026 | see §4.3 | see §4.3 | | Not run in month one (32 GB RAM / 80 GB disk recommended for 1.0; 2.0 unreleased). |
| ORCA-bench | 2026 | arXiv 2607.28545 | https://arxiv.org/abs/2607.28545 | [preprint], CC BY 4.0 | Realistic on-call tasks: best 25.3% medium, 10.0% hard ([sota_methods §Q2][sota]). Context only. |
| SREGym | 2026 | arXiv 2605.07161 | https://arxiv.org/html/2605.07161v1 | [preprint], MIT | Live, mitigation-centric, LLM-judged; 63.7% → 17.9% on unseen failures ([sota_methods §Q2][sota]). Out of scope (needs 16 GB for the cluster). |
| ITBench | 2025 | ICML'25 | https://proceedings.mlr.press/v267/jha25a.html ; ITBench-AA: https://artificialanalysis.ai/evaluations/itbench-aa | | Live SRE scenarios; ITBench-AA pass rates < 42% ([stack_and_market §B1][sm]). Out of scope. |
| AIOpsLab | 2025 | MLSys'25 | https://github.com/microsoft/AIOpsLab | | Live; source of fault-injection recipes (Chaos Mesh) and `noop` controls for the lab ([benchmarks_and_testbed §Q3][bt]). |
| Cloud-OpsBench | 2026 | arXiv 2603.00468 | https://arxiv.org/abs/2603.00468 | [preprint], CC BY 4.0 | Replayable tool snapshots (MiB per case); candidate for a later agent-arm evaluation ([benchmarks_and_testbed §Q1][bt]). |
| Hu, Liu & Fu (extra) | 2026 | arXiv 2606.29159 | https://arxiv.org/abs/2606.29159 | [preprint]; some figures from a PDF snippet | Pooled leaderboards hide system winners; 0 of 23 papers release per-case outputs. Drives C3. |
| Hussain & Farrukh (extra) | 2026 | Research Square; DOI 10.21203/rs.3.rs-11401166/v1 | https://doi.org/10.21203/rs.3.rs-11401166/v1 | [preprint], pre-registered | Our statistics design (cluster bootstrap, sign-flip permutation, McNemar + Holm, MDD) and the onset-shift and decoy results ([benchmarks_and_testbed §Q2][bt]). |
| LLM guidelines for empirical SE (extra) | 2026 | *Empirical Software Engineering* (accepted) | https://llm-guidelines.org/guidelines/ | | Reporting checklist for the LLM arm (§8). |

### 4.5 Uncertainty, calibration and abstention

| Work | Year | Venue / ID | URL | Flag | How Veyltrace differs |
|---|---|---|---|---|---|
| Transductive Conformal Inference for Full Ranking | 2025 | NeurIPS 2025; arXiv 2501.11384 | https://arxiv.org/abs/2501.11384v3 | | Theory for conformal sets over rankings; we use plain split conformal on a verified score ([novel_building_blocks §Q7][nb]). |
| Conformal Ranked Retrieval | 2024 (from arXiv ID) | arXiv 2404.17769 | https://arxiv.org/html/2404.17769v1 | [preprint] | Conformal risk control for two-stage retrieval + ranking; a possible future variant of our set rule. |
| LM-PACE | 2024 | FSE 2024 Industry; arXiv 2309.05833 | https://arxiv.org/pdf/2309.05833 | | **Prior calibration work in RCA**: calibrates LLM root-cause *confidence* (ECE to 31% of direct prompting). We do not use model confidence; we give coverage-targeted sets. Our "first" claim must exclude this ([verified_agents §Q6][va]). |
| CONCH / CROC | 2026 (from arXiv ID) | arXiv 2607.26481 | https://arxiv.org/pdf/2607.26481 | [snippet] | **Closest threat to C2's novelty**: distribution-free confidence sets for which stream changed first, applied to offline root-cause localisation. Must be read in full before any "first" claim ([verified_agents §Q6][va]). |
| "The Abstention Protocol: RCA for Clos Fabrics" | 2026 | OSDI '26 (listing) | https://papers.cool/venue/gaikwad@osdi26@USENIX | [snippet] | Abstention-based RCA for network fabrics; must be read before claiming "first abstaining RCA" ([verified_agents §Q6][va]). |
| Conformal abstention for LLM hallucinations | 2024 (from arXiv ID) | arXiv 2405.01563 | https://arxiv.org/pdf/2405.01563 | | Conformal abstention for LLM QA, not RCA ([sota_methods §Q6][sota]). |

### 4.6 Change-aware RCA

| Work | Year | Venue / ID | URL | Flag | How Veyltrace differs |
|---|---|---|---|---|---|
| Gandalf | 2020 | NSDI 2020 | https://www.usenix.org/conference/nsdi20/presentation/li | | Azure safe deployment: spatial + temporal correlation of faults with rollouts, 92.4–94.9% precision ([novel_building_blocks §Q5][nb]). Gates rollouts; we localise root causes and treat changes as one evidence channel. |
| ChangeRCA | 2024 | FSE 2024 | https://2024.esec-fse.org/details/fse-2024-research-papers/3/ChangeRCA-Finding-Root-Causes-from-Software-Changes-in-Large-Online-Systems | numbers [search-summary] in [sota_methods §Q4][sota] | Finds the defective change among candidates (85% HR@1 on WeChat). Data not public. We test channel robustness to decoys. |
| Meta Service Health Checks | 2026 | arXiv 2608.20513 | https://arxiv.org/html/2608.20513 | [preprint] | Changed-vs-control cohort checks; fleet-wide false positives fell from 12.1% to 2.7% in a year ([novel_building_blocks §Q5][nb]). Basis of our peer contrast (T7). The paper does not show the drop is caused by cohort checks alone; do not imply it. |
| DeltaRCA (extra) | 2026 | ASE 2026; DOI 10.1145/3832783.3837424 | https://doi.org/10.1145/3832783.3837424 | [search-summary] | LLM reads code changes to re-weight trace SBFL; 63% Top-1 is unverified ([sota_methods §Q1][sota]). |
| Google SRE workbook, postmortem analysis (extra) | 2010–2017 data | Book appendix | https://sre.google/workbook/postmortem-analysis/ | | Source of the 68% change-triggered figure ([novel_building_blocks §Q5][nb]). |

### 4.7 Provenance and reproducibility

| Work | Year | Venue / ID | URL | Flag | How Veyltrace uses it |
|---|---|---|---|---|---|
| in-toto Statement v1 | — | specification | https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md | | Receipt envelope; subjects matched by digest. Supply-chain oriented; no precedent found for inference receipts ([verified_agents §Q7][va]). |
| W3C PROV | [fill] | W3C Recommendation | [fill] (no URL in the notes) | not in notes | Vocabulary for activities in the agent trace. |
| PROV-AGENT | 2025 | IEEE e-Science 2025; arXiv 2508.02866 | https://arxiv.org/abs/2508.02866 | abstract only read | Extends PROV to agent prompts, responses and tool calls. We record a subset in `agent_trace.jsonl`. |
| IETF WCA draft (extra) | 2026 | draft-bondar-wca-00 (individual, expired 2 Sep 2026) | https://www.ietf.org/archive/id/draft-bondar-wca-00.html | | Hash-chained attestation of agent tool calls; our trace chain follows the same idea. |
| "Defeating Nondeterminism in LLM Inference" (extra) | — | Thinking Machines blog | https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/ | blog | Why replay re-verifies recorded outputs instead of regenerating them (80 distinct outputs from 1,000 temperature-0 runs) ([verified_agents §Q3][va]). |

## 5. Paper outline, figures and tables

Target structure for a 10-page research paper; scale down for a short or industry paper. Every figure or table marked *data* is generated by a `bench` script from `bench/results/` (§10); hand-drawn items are marked *diagram*.

| § | Section | Content | Figures / tables → source experiment ([04 §6](04-evaluation-protocol.md)) | Writer |
|---|---|---|---|---|
| 1 | Introduction | Cost and trust problem ([01 §1](01-vision-and-requirements.md)); why stricter metrics and decoys matter; propose–verify idea; contributions C1–C4; headline results | Fig. 1 *diagram*: propose–verify pipeline with trust classes | AK |
| 2 | Background and related work | Condensed §4: statistical methods lead on RCAEval; LLM harnesses vs strict metrics; hybrids; verification; calibration gap; change-aware RCA | Table 1: related-work comparison (verifies claims in code? abstains? replayable? local? per-case outputs?) | AK |
| 3 | Veyltrace design | 3.1 pipeline and engine boundaries; 3.2 evidence atoms and predicates; 3.3 rankers and gated RRF; 3.4 proposer (`brief`, closed enums, budgets); 3.5 verifier: trials, decision function, symmetric claim pass; 3.6 conformal sets, `NO_FAULT`, statuses; 3.7 receipts and replay tiers | Fig. 2 *diagram*: claim pass across the pool. Fig. 3 *data*: one verdict card and receipt from `synth-04`. Table 2: trials T1–T10 | AK (3.2, 3.3, 3.5, 3.6), AS (3.1 Observe part), CL (3.4, 3.7) |
| 4 | Evaluation setup | Datasets; alert protocols; splits by cluster; baselines in one pinned harness; metrics; statistics and MDD; pre-registration tag; hardware | Table 3 *data*: datasets (cases, systems, sources) ← dataset manifests. Table 4: baselines and configs | AK, AS (datasets) |
| 5.1 | RQ1 Accuracy | Per-system AC@1/3/5, Avg@5, Retrieval@5, Rerank@1 vs chance, N-Sigma, BARO, alert count, under oracle and detected alerts; failure taxonomy of misses | Table 5 *data* ← RQ1 rows. Fig. 4 *data*: retrieval vs re-ranking decomposition per system ← RQ1 rows | AK |
| 5.2 | RQ2 Proposer | Lift over 3 seeds; decoy-proposal flips; permutation invariance; which predicates the LLM requests; `investigate` vs `brief`; 9B vs 4B | Table 6 *data* ← RQ2 rows. Fig. 5 *data*: predicate-request frequency vs claim pass outcome ← RQ2 rows | CL |
| 5.3 | RQ3 Calibration | Coverage, set size, abstention per family; LOSO gap; `NO_FAULT` on normal windows | Fig. 6 *data*: risk–coverage curves (ranker vs verifier) ← RQ3 rows. Table 7 *data* ← RQ3 rows | AK |
| 5.4 | RQ4 Robustness | Alert-shift curve; telemetry-ablation matrix; RCAEval-C; anonymisation probe | Fig. 7 *data*: AC@1 vs shift ← RQ4 shift rows. Fig. 8 *data*: ablation heatmap (AC@1 and status mix) ← RQ4 ablation rows. Fig. 9 *data*: RCAEval-C (π × decoy rate) ← RQ4 RCAEval-C rows | AS (shift, ablation), AK (RCAEval-C) |
| 5.5 | RQ5 Cost | p50/p95 time, peak RSS, tokens per case; laptop specs; published agent costs as context only | Table 8 *data* ← RQ5 (all runs) + `docs/team/*.md` | AS |
| 5.6 | RQ6 Replay | Tier-1 rate across laptops and CI; Tier-2 regeneration rate | Table 9 *data* ← RQ6 rows | CL |
| 6 | Discussion | Where the verifier abstains (network faults, where onset precedence flips); what the LLM adds; using Veyltrace as an MCP verification tool for other agents; limits of synthetic decoys | — | all |
| 7 | Threats to validity | §6 of this plan | — | AK |
| 8 | Conclusion and data availability | DOI, per-case outputs, reproduction command | — | AK |
| App. | Appendix | Predicate library; config defaults; per-system tables; prompts and JSON schemas; hardware; RCAEval commit | Tables A1–A4 *data* | all |

## 6. Threats to validity

| Type | Threat | Mitigation | Residual |
|---|---|---|---|
| Internal | **Baseline implementation and harness differences.** CIRCA is reported at 0.32 AC@1 on RE2-TT in RCAEval's paper, 0.67 in GALA+'s harness (probably RE2-OB) and 17.8% PR@1 on RCAtlas; RCAEval fixed a CIRCA/PageRank bug in Sep 2026 ([sota_methods §Q1][sota]). | Run every baseline in one harness, pinned RCAEval commit, same input tables and denominators; report reproduction gaps (R-05). | Our numbers may differ from published ones; we compare only against our re-runs. |
| Internal | **We wrote both the predicates and the verifier.** The trials encode our assumptions (e.g., internal onset precedes external, which flips for network faults). | Parameters set a priori in config with cited sources; never tuned on test splits; per-fault-class results including high abstention on network faults reported, not tuned away ([report][rep], Conclusion). | Design choices may favour fault types we understand. |
| Internal | **Leakage between calibration and test.** RCAEval repeats each (system, service, fault) three times; repetitions are not independent ([benchmarks_and_testbed §Q2][bt]). | Splits by cluster, defined in [04](04-evaluation-protocol.md) and tagged before evaluation; scrubbing and isolation tests (P7). | — |
| Internal | **Defaults informed by literature on the same benchmark.** Window sizes and thresholds came from papers evaluated on RCAEval. | Treat RE1 as development data; report RE2/RE3 as test; state which defaults came from which source. | Some optimism remains. |
| External | **Small, injected-fault systems.** RCAEval systems are OB, SS, TT with single injected faults; real incidents differ. Statistical methods' retrieval falls from 98–100% on microservices to 35–64% on industrial control data ([sota_methods §Q6][sota]). | Nezha and (if usable) FSE'26 TT as second sources; VeylLab with no-fault and noise controls. | No production data. |
| External | **Synthetic decoy and true changes in RCAEval-C.** The generated true change encodes the injected service by construction. | Report RCAEval-C as a stress test of channel gullibility, not as evidence of real-world gains; back with real `kubectl rollout` and flag changes in the lab ([novel_building_blocks §Q5][nb]). | Real change logs are noisier. |
| External | **Laptop-collected lab data.** Host contention, the Docker Desktop VM and single-node kind ([benchmarks_and_testbed §Q5][bt]). | Record per-case host CPU/RAM; publish acceptance rate and datasheet. | — |
| Construct | **Service-level AC@1 ignores the propagation path and fault type.** Edge F1 trails Node F1 for LLM agents ([sota_methods §Q2][sota]). | Also report fault-class and indicator accuracy; path grounding where labels exist. | Path ground truth is missing for RCAEval. |
| Construct | **"Proposer lift" depends on the predicate library.** An LLM can only help through predicates we wrote. | Report predicate coverage and requests; treat zero lift as a finding about the library-plus-model pair, not about LLMs in general. | — |
| Construct | **`NO_FAULT` windows are sliced from pre-injection data** and may be shorter than real windows ([ADR conformal-abstention](adr/20261030-ak-conformal-abstention.md)). | Report `NO_FAULT` separately on lab no-fault captures. | — |
| Construct | **Label noise in RCAEval** (e.g., fault `f6` relabelled `f3`; missing logs and traces; non-independent repetitions, [benchmarks_and_testbed §Q5][bt]). | Report per-fault-class results; list known label issues. | — |
| Conclusion | **Low power.** MDD ≈ 7 points on 270 cases and ≈ 14 on 90; clustering raises it ([benchmarks_and_testbed §Q2][bt]). | Paired cluster bootstrap (2,000), cluster sign-flip permutation (10,000), McNemar secondary, Holm correction; "not detected" wording. | Per-system claims will often be inconclusive. |
| Conclusion | **Small calibration strata.** Split conformal needs at least 1/α − 1 = 9 calibration cases per stratum ([novel_building_blocks §Q7][nb]). | Calibrate per family, not per family × modality, in v1.0. | — |
| LLM-specific | **Non-determinism.** Bit-exact regeneration is not portable ([verified_agents §Q3][va]). | Tier-1 replay from cassettes; Tier-2 rate measured; 3 seeds with mean and SD. | Seed variance in the AI arm. |
| LLM-specific | **Contamination.** RCAEval is public and may be in pretraining data; no study measures it ([benchmarks_and_testbed §Q2][bt]). | Service-name anonymisation probe (cost 0.20–0.21 AC@1 on RE3 for one LLM pipeline in prior work); verdict still decided by code. | Cannot rule out. |
| LLM-specific | **Vendor-reported model scores** (BFCL, TAU2) are not independent ([verified_agents §Q4][va]). | Report our own measurements; pin GGUF SHA-256, quant, runtime version. | — |
| Hardware | **Laptop variance.** CPU speed differs across team laptops; published CPU token rates are weak estimates ([verified_agents §Q4][va]). | Verdicts do not depend on speed; timings reported per laptop with `llama-bench` pp512/tg128. | Cost numbers are hardware-specific. |
| Process | **Multi-agent development.** Code was written by three people each using a different AI coding agent; cross-agent PR pairs conflict 41.7% of the time vs 19.8% for same-agent pairs ([multi_agent_dev §Q3][md]). Agent-written code may contain subtle bugs. | Lanes, contracts, golden fixtures, tests-first, determinism gate, human review of every PR; `agent:` labels and conflict counts recorded and reported as a process note. | This is a process threat, not a result; we make no claim about agent productivity. |

## 7. Venue plan and arXiv

[07 §8](07-roadmap.md) links here. Dates are from [multi_agent_dev §Q5][md] and the [report][rep]; "inferred" means estimated from the previous year's cycle and must be confirmed on the official CFP. Already passed: ICSE 2027 research (30 Jun 2026), ICSE SEIP (23 Oct 2026), FSE 2027 research (2 Oct 2026, third-party source), KDD 2027 cycle 1 (26 Jul 2026).

| Deadline | Venue and track | Fit | What we would have by then ([07](07-roadmap.md)) | Verdict |
|---|---|---|---|---|
| 6 Nov 2026 | CAIN 2027 Posters & Demos (ICSE co-located) | Early demo | M0 only (stubs, synthetic case) | **No.** Nothing to show. |
| 13 Nov 2026 | ICSE 2027 workshops (AGENT, AIPerf, others), ACM SRC, Industry Challenge | Short paper or SRC abstract on design + early results | M1 (8 Nov): contracts frozen, RE2 ingested, baselines reproduced; M2 (AI-off scores) is two days *after* the deadline | **Not recommended.** A workshop paper needs results we will not have. An SRC abstract on design plus baseline reproduction is writable in about 1 person-day, but that day falls in week 2, on the critical path (R-08, R-09). Go only if a teammate off the critical path drafts it, eligibility is confirmed on the CFP, and the lead approves by Wed 4 Nov. |
| 16 Nov 2026 | WWW 2027 Demos | Live demo paper | M2 (15 Nov): AI-off verdicts and a console verdict view; the live demo is M3 (22 Nov) | **No.** The live demo does not exist yet, and a web-conference demo track is a weak topical fit. |
| 23 Jan 2027 | FSE 2027 Industry (10+2 pages) | Needs work "applied in an industrial context" or with clearly identified industrial relevance | Full results and draft | **Conditional.** Only if we gain an industrial collaborator or data; otherwise the fit is weak. |
| Feb 2027 (exact date unconfirmed) | KDD 2027 cycle 2 (Research, ADS, D&B) | Method plus evaluation | Full results, revised draft | **Primary target** if RQ1 meets SC-3(b) and RQ3 holds. Research track (ADS expects deployed systems). August-cycle research acceptance was 19% ([multi_agent_dev §Q5][md]). |
| ~Apr 2027 (inferred) | ISSRE 2027 research (Macau, 19–22 Oct 2027) | Natural home for RCA and dependability | Revised paper | **Primary alternative**, and fallback if KDD rejects or results are mixed. |
| ~May 2027 (inferred) | NeurIPS 2027 Evaluations & Datasets | Dataset or evaluation paper (DecompRCA precedent) | VeylLab if ≥ 300 validated cases | **C5 only** (second paper), per [07 §8](07-roadmap.md). Needs Croissant + RAI metadata. |

**Recommendation.**

1. **December 2026:** arXiv preprint (once endorsed) and the Zenodo-archived `v1.0.0` artifact. Check each target venue's anonymity and preprint policy before posting.
2. **February 2027:** submit the method paper (C1–C3, plus C4 if complete) to KDD 2027 cycle 2. If results are mixed, or the date does not fit, target ISSRE 2027 instead.
3. **FSE 2027 Industry** only with industrial data or a partner.
4. **May 2027:** VeylLab (C5) to NeurIPS 2027 E&D if it reaches ≥ 300 validated cases.
5. Skip the November 2026 deadlines unless the SRC conditions above are met.

**arXiv endorsement.** Since 21 Jan 2026, automatic endorsement needs an institutional email **and** prior authorship of an accepted paper in the endorsement domain; otherwise a personal endorsement from an established author in that domain is required. arXiv also added a monthly per-author submission cap (value not confirmed) ([multi_agent_dev §Q5][md]).

| Action | Owner | Due |
|---|---|---|
| Ask a faculty advisor at RV University (or an outside researcher with cs.SE, cs.DC or cs.LG arXiv history) to act as endorser and, if they contribute, co-author | Aniket | M2 (15 Nov) |
| Decide the arXiv category (cs.SE primary, cs.DC or cs.LG cross-list, *proposal*) | Aniket | M4 |
| Record the decision in an ADR at the retrospective (task L-07) | all | M5 |

## 8. Reproducibility and artifact checklist

Built from day one, not at the end ([multi_agent_dev §Q5][md]).

| Item | Requirement and source | Where | Owner | Due |
|---|---|---|---|---|
| ACM *Available* | Permanent archive with a DOI; "GitHub, GitLab, or a similar software-development site is not adequate" (ACM v1.1 as quoted by UPenn AE guidelines, [multi_agent_dev §Q5][md]) | Zenodo DOI per GitHub release (repo must be public) | AK | M5 (L-05) |
| ACM *Functional* | Documented, consistent, complete, exercisable, with evidence of verification | `REPRODUCE.md`, tests, CI | all | M5 |
| ACM *Reusable* | Functional plus documentation and structure that enable reuse | Contracts, engine docs, entry points, examples | all | M5 |
| `CITATION.cff` | At the repo root on the default branch; enables "Cite this repository" | [../CITATION.cff](../CITATION.cff); add DOI and bump version at release | AK | created 30 Oct; DOI at M5 |
| `REPRODUCE.md` | One command reproduces the headline table; verified on a clean clone by a teammate who did not write it ([07 L-06](07-roadmap.md)) | repo root | AS | M5 |
| Pinned environments | `uv.lock`, `pnpm-lock.yaml`, Python 3.12, pinned RCAEval commit, separate envs for any baseline that needs Python 3.8, lab image digests, Ollama / llama.cpp version | repo; `bench/` configs; `lab/` | AK, CL | M4 |
| Per-case outputs | `per_case.csv` for every method and experiment ([03 §13.2](03-contracts.md)); release them so others can recompute every number (C3) | committed under `bench/results/<experiment>/` (CSV, so AGENTS.md §4.6 does not block it; resolved in 03, 2026-10-30) and included in the Zenodo artifact with verdicts, slates and cassettes | AK | M4 |
| Run manifests | Code commit (clean), config hash, `uv.lock` hash, calibration hash, input hashes ([03 §12](03-contracts.md)) | every run directory and `bench/results/<id>/manifest.json` | AK | ongoing |
| Model provenance | GGUF SHA-256, quant type, runtime version or commit, sampler parameters, `llama-bench` pp512/tg128 per laptop ([verified_agents §Q4][va]) | `config/llm.yaml`; `docs/team/<initials>.md` | CL | M0 and M3 |
| Prompts, schemas, cassettes | LLM guidelines require released prompts and interaction logs ([benchmarks_and_testbed §Q2][bt]) | `packages/relentra`; cassettes in the Zenodo artifact | CL | M4 |
| LLM-study reporting | Exact model version and configuration, naive baseline (AI off), repeated runs as distributions, open-model baseline, contamination and non-determinism discussed ([benchmarks_and_testbed §Q2][bt]) | paper §4–6 | AK, CL | M4 |
| Pre-registration | Tagged commit with RQs, hypotheses, splits and analysis plan before any test-split result, as in the pre-registered RCAEval study ([benchmarks_and_testbed §Q2][bt]) | tag `prereg-v1` (*proposal*) | AK | before the first test-split run (≤ M2) |
| Hardware spec | CPU, RAM, OS, WSL2 settings per laptop | `docs/team/<initials>.md` | all | M0 |
| Data licences | RCAEval MIT; Nezha MIT; FSE'26 TT licence unknown; VeylLab CC BY 4.0 (*target*) | `data/LICENSE` or release notes | AS, CL | M5 |
| NeurIPS E&D (C5 only) | Croissant metadata with mandatory Responsible-AI fields; hosting on Dataverse, Kaggle, Hugging Face or OpenML; public by camera-ready ([benchmarks_and_testbed §Q2][bt]) | VeylLab release | CL | 2027 |
| Datasheet | Includes laptop-collection threats (host contention, Docker Desktop VM, single-node kind) | VeylLab release | CL | v1.0 or v1.1 |

## 9. Authorship and contribution statement

**Author order: to decide.** Suggested rule, to be applied at the M4 retrospective and recorded in an ADR:

1. Order by contribution to the paper's claims, measured by the CRediT roles below (writing and analysis weigh most; code counts through the experiments it enables).
2. If two contributions are judged equal, order alphabetically by family name and add an equal-contribution footnote.
3. A faculty advisor or endorser is listed last only if they contribute to at least one CRediT role beyond endorsement; otherwise they are acknowledged.
4. Any change after M4 needs agreement from all authors.

**CRediT roles (provisional, by lane; revise at M4):**

| CRediT role | Aniket Kumar | Annapurna S | C Lakshanaa |
|---|---|---|---|
| Conceptualization | lead | supporting | supporting |
| Methodology | lead (verifier, conformal, evaluation) | equal (signals, anomalies, onsets, change channel) | equal (proposer, receipts, lab protocol) |
| Software | equal (core, FaultLoom, Causatrix, Causentra, bench) | equal (engines 1–5) | equal (Relentra, Causivra, llm, gateway, console, lab) |
| Validation | lead | supporting | supporting |
| Formal analysis | lead (statistics) | supporting | supporting |
| Investigation | equal | equal | equal |
| Resources | — | — | lead (lab testbed) |
| Data curation | supporting | lead (benchmark ingest) | lead (VeylLab) |
| Writing – original draft | lead | supporting | supporting |
| Writing – review & editing | equal | equal | equal |
| Visualization | supporting (tables, figures) | supporting | lead (console, demo) |
| Supervision | lead | — | — |
| Project administration | lead | — | — |
| Funding acquisition | — | — | — |

## 10. Writing workflow

- **Location.** LaTeX in `paper/`, owned by the lead (Reason lane; `paper/` is matched by the catch-all in `.github/lanes.yml`), except `paper/sections/observe-*` and `paper/sections/explain-*`, which those lanes own ([08 §3](08-collaboration-and-git.md)). Venue template chosen at M4.
- **One section per author.** Each section lives in its own file, assigned in §5: the lead's as `paper/sections/<nn>-<slug>.tex`, Observe's as `paper/sections/observe-<slug>.tex`, Explain's as `paper/sections/explain-<slug>.tex`, so each author edits only their own files without the `cross-lane` label. `paper/main.tex` and the preamble stay with the lead.
- **Figures and tables are generated, never hand-edited.** `bench` scripts write tables (`.md` and `.tex`) and figures (vector PDF) from `bench/results/` (R-17). A copy step places them in `paper/generated/`, which nobody edits by hand. Every caption names the experiment config. Diagrams (Fig. 1, Fig. 2) live in `paper/figures/` as source files.
- **Numbers in prose** are `\newcommand` macros generated from `summary.json` (e.g. `\ACOneREtwoOB`), so no number is typed by hand (*proposal*).
- **Citations.** One BibTeX file, `paper/refs.bib`. To avoid a shared-file hot spot, each lane adds entries to `paper/bib/<lane>.bib` and a script concatenates, sorts and de-duplicates them into `refs.bib`, which is generated (*proposal*, set up in R-18). Keys: `familyYEARword` (e.g. `pham2024baro`). Every entry carries a URL or DOI copied from the notes; `[fill]` items in §4 are resolved from the primary source before they are cited.
- **Internal review schedule.**

| Date | Step | Who |
|---|---|---|
| Mon 16 Nov (after M2) | Outline and figure/table list frozen against this plan | lead |
| Sun 22 Nov (M3) | Section drafts v0 for 3.x, 4 and the RQ sections that have data | section owners |
| Thu 26 Nov (bug bash, L-04) | Number audit: every number in the draft traced to `bench/results/` | each author checks a section they did not write |
| Sun 29 Nov (M4) | Draft v1 complete (R-18) | all |
| Dec 2026, week 2 | Review round 1: each author reviews two sections they did not write, using §11 and the [LLM guidelines](https://llm-guidelines.org/guidelines/); full-text novelty search for C2 (§11) | all |
| Dec 2026, week 3 | External read by advisor or endorser; arXiv post if endorsed | lead |
| Jan 2027 | Review round 2; venue formatting; artifact re-check against §8 | all |

## 11. Claim register: what to hedge or avoid

These come from the research notes. Each must be checked again at review round 1.

| Claim | Problem | Allowed phrasing |
|---|---|---|
| "First calibrated RCA" | LM-PACE (FSE 2024 Industry) calibrates LLM root-cause confidence ([verified_agents §Q6][va]). | "To our knowledge, based on searches up to October 2026, the first conformal candidate sets with a no-fault option for microservice RCA." |
| "First conformal RCA" / "first abstaining RCA" | CONCH/CROC (arXiv 2607.26481) gives distribution-free sets for offline root-cause localisation; the OSDI'26 "Abstention Protocol" abstains in network RCA. Both seen only as snippets ([verified_agents §Q6][va]). | Use only after reading both in full and searching ICSE, FSE, ASE and arXiv full text ([report][rep], Conclusion). |
| "Deterministic verification improves accuracy (DiagGuard +3.5–35 pp)" | DiagGuard's verifier is LLM-based ([verified_agents §Q2][va]). [02 §2 P1](02-architecture.md) now hedges this (resolved in 02, 2026-10-30). | "Explicit verification steps, LLM-based in DiagGuard, raised Acc@1 by 3.5–35.1 pp; no paper isolates a purely deterministic verifier." |
| "No paper evaluates a ≤ 10B model as an RCA agent" | ThinkFL (TOSEM'26) fine-tunes lightweight LLMs for failure localisation; its base size was not retrieved ([sota_methods §Q2][sota]). | "We found no paper that evaluates a ≤ 10B model as the investigating agent on RCAEval, OpenRCA or RCABench; ThinkFL's model size is unconfirmed." |
| "Cohort checks cut Meta's false positives from 12.1% to 2.7%" | The note reports the fleet-wide drop over a year, not its cause ([novel_building_blocks §Q5][nb]). | "Meta reports fleet-wide false positives falling from 12.1% to 2.7% in a year with changed-vs-control checks." |
| RCAtlas per-model names and runs (e.g. the 88.9% best single run) | The notes disagree on whether models are named or anonymised. | Quote harness-level means only (72.8% SQL agent, 77.2% Codex harness, 65.3% one-shot; 38.9% NSigma). |
| GALA+ results "on RE2-OB/TT" | Benchmark identity is inferred from 1/90 granularity ([sota_methods §Q1][sota]). | "On two 90-case benchmarks, probably RE2-OB and RE2-TT." |
| DeltaRCA 63% Top-1; ChangeRCA numbers; SBES 96.1% human resolution | Search-summary only. | Cite only after reading the paper, or omit. |
| "Simple alert counting matches SOTA on existing benchmarks" | True for the benchmarks named (Nezha, Eadro, RCAEval); the fourth is unnamed ([benchmarks_and_testbed §Q1][bt]). | Name the three benchmarks. |
| Onset-shift, decoy and MDD figures | From a Research Square preprint, not peer-reviewed ([benchmarks_and_testbed §Q2][bt]). | Cite as a pre-registered preprint. |
| Vendor accuracy, outage-cost and trust-survey numbers | Self-reported or vendor-sponsored ([01 §1](01-vision-and-requirements.md)). | Always label "vendor survey" or "self-reported". |
| Qwen3.5 BFCL / TAU2 scores | Vendor-reported ([verified_agents §Q4][va]). | Label as vendor-reported; report our own measurements. |
| Google "68% of outages from pushes" | 2010–2017 postmortems; dated ([novel_building_blocks §Q5][nb]). | Always give the period. |

[rep]: ../reports/Veyltrace%20v2%20SOTA%20root%20cause%20analysis.md
[sota]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/sota_methods_2026.md
[bt]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md
[va]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/verified_agents_local_llms.md
[nb]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/novel_building_blocks.md
[sm]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/stack_and_market.md
[md]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/multi_agent_dev_and_sdlc.md
