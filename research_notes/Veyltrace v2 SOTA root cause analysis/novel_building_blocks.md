# Novel technical building blocks (2024 – Oct 2026) for a publishable, laptop-feasible microservice RCA system (Veyltrace v2)

Scope note: this file **extends** `research_notes/Veyltrace outage diagnosis research/novel_techniques.md` (robust z / BARO / PRISM scoring, onset precedence, trace SBFL, Drain3 statistics, split-conformal top-k, RRF/DS fusion, latency-accounting counterfactuals, DELAY-vs-LOSS network mode). Those are **not repeated** here except as one-line pointers. Everything below is new or deeper material: time-series foundation models (TSFMs), LLM log parsing, critical-path traces, causal-RCA benchmarks, change-aware RCA, missing telemetry / multi-fault / transfer, conformal *ranking*, fusion, fault typing and remediation. Each key question ends with "Inferences" that hold my technique cards (CPU estimates, paper framing, risk); the last section is the ranked shortlist. Numbers labelled "estimate" are my arithmetic, not sourced.

Project-rule flag (from the repo's CLAUDE.md: "no AI or network in the decision path, determinism"): TSFMs, LLM log parsers and LLM re-rankers below would put learned/AI components into the decision path if they feed ranking. Each card says whether it can be kept offline/deterministic (pinned weights, cached outputs recorded in receipts) or narration-only. The team must decide whether v2 keeps that rule.

---

## Q1. Time-series foundation models (Chronos-2/Bolt, TimesFM 2.5/3.0, Moirai 2.0/MoE, MOMENT, Toto 1/2, Time-MoE, Sundial) for anomaly detection in RCA — accuracy, CPU speed, licences, RCA use

### Takeaway
Forecasting TSFMs improved a lot in 2025–26 (Chronos-2, Toto 2.0, TimesFM 3.0), but on the main anomaly-detection benchmark (TSB-AD-U) **zero-shot TSFMs only tie classical detectors** (best zero-shot VUS-PR 0.319 vs Sub-PCA 0.332 and SAND 0.353); they need fine-tuning to pull ahead (Time-MoE 0.392). I found **no paper that uses a TSFM as the anomaly scorer inside microservice RCA**, so a careful "do TSFMs help RCA?" study with small CPU-friendly models (Chronos-Bolt-tiny 9M, Chronos-2-small 28M, Toto 2.0 4M/22M — all Apache-2.0) is an open, publishable question. The honest expected result is "modest or no gain over robust-z, but better calibrated tail probabilities".

### Cited Findings
**Anomaly-detection evidence**
- TSB-AD (NeurIPS 2024 Datasets & Benchmarks): 1,070 series from 40 datasets, 40 algorithms; VUS-PR named the most reliable measure; results "challenge the assumption that advanced neural architectures are superior" — "simpler architectures and statistical methods often yield better performance"; neural nets look promising on multivariate cases and foundation models on point anomalies; the authors urge caution about data contamination for foundation models. Code Apache-2.0. — [TSB-AD GitHub](https://github.com/TheDatumOrg/TSB-AD); [NeurIPS 2024 poster page](https://nips.cc/virtual/2024/poster/97690)
- Adaptation study on TSB-AD-U (23 univariate datasets), zero-shot VUS-PR / AUC-PR: Chronos-Bolt-small 0.319 / 0.346; Moirai-small 0.318 / 0.335; Time-MoE-base 0.318 / 0.339; classical Sub-PCA 0.332 / 0.293, SAND 0.353 / 0.299, IForest 0.234 / 0.187; neural LSTMAD 0.323 / 0.332. Fine-tuned Time-MoE-base reaches 0.392 VUS-PR (LoRA 0.372, OFT 0.365); Moirai-base OFT 0.361 vs full FT 0.354. Section 4.2: zero-shot TSFMs "do not consistently surpass the strongest task-specific models across all metrics" (the conclusion is more upbeat). No runtimes reported. Moirai-MoE-small activates ~11M parameters per forward pass. — [arXiv 2601.00446](https://arxiv.org/html/2601.00446)
- TimeRCD, a zero-shot anomaly-detection foundation model pre-trained on synthetic data with "relative context discrepancy" (compare a query window to its context), claimed to beat MOMENT/TimesFM/Chronos/Time-MoE zero-shot on TSB-AD — **the manuscript was withdrawn** (v5, 29 May 2026: "withdrawn, as the authors intend to further extend… the work"). — [arXiv 2509.21190](https://arxiv.org/abs/2509.21190)
- THEMIS uses frozen Chronos encoder embeddings for zero-shot anomaly detection without dataset-specific training (seen via search snippet only). — [arXiv 2510.03911](https://arxiv.org/pdf/2510.03911)

**Model facts (forecasting)**
- Chronos-2 (Amazon, released 20 Oct 2025): 120M-parameter encoder, Apache-2.0, context 8,192 / horizon 1,024, 21 quantiles from 0.01 to 0.99, past and known-future covariates. — [beri.net comparison (secondary, Oct 2026)](https://www.beri.net/article/timesfm-vs-chronos-vs-moirai-time-series-foundation-model-licence-bigquery-sagemaker-cost-2026); params/licence confirmed — [chronos-forecasting GitHub](https://github.com/amazon-science/chronos-forecasting)
- Chronos-2 paper: "group attention" enables in-context learning across related series / variates / covariates; ICL gives "only modest gains" on multivariate tasks and the largest gains with covariates. Throughput "300 time series per second" on one NVIDIA A10G GPU (batch 1,024, context 2,048, horizon 64); **no CPU throughput reported** — the 28M Chronos-2-small is suggested for "CPU-only settings", ~2× faster with a GIFT-Eval skill score "as little as 1% points" lower. fev-bench win rate 90.7% / skill 47.3% (next best TiRex 80.8% / 42.6%); GIFT-Eval WQL 81.9% / 51.4%, MASE 83.8% / 30.2%. Anomaly detection is mentioned only as a motivation for the extreme 0.01/0.99 quantiles; no AD experiments. — [arXiv 2510.15821](https://arxiv.org/html/2510.15821)
- A Chronos-2 paper table (per a search summary) lists win rate / skill 81.5% / 26.5% for Chronos-2 vs 71.6% / 23.3% for TimesFM-2.5, 53.5% for Moirai-2.0 and 21.8% for Sundial; the HTML fetch labels the 81.5%/26.5% figures as Chronos Benchmark II (MASE) rather than GIFT-Eval — benchmark attribution uncertain. — [arXiv 2510.15821](https://arxiv.org/pdf/2510.15821)
- Chronos-Bolt: Tiny 9M, Mini 21M, Small 48M, Base 205M; "can also be used on the CPU"; "up to 250 times faster and 20 times more memory-efficient" than original Chronos (direct multi-step quantile output instead of autoregressive decoding); Bolt-Base beats Chronos-Large accuracy while "over 600 times faster". — [AWS ML blog](https://aws.amazon.com/tw/blogs/machine-learning/fast-and-accurate-zero-shot-forecasting-with-chronos-bolt-and-autogluon/); sizes also in [GitHub](https://github.com/amazon-science/chronos-forecasting)
- Toto 1.0 (Datadog, May 2025): 151M parameters, Apache-2.0; BOOM CRPS 0.375 / MASE 0.617, GIFT-Eval CRPS 0.517 / MASE 0.750; example code hard-codes CUDA and recommends xFormers/flash-attention; no CPU guidance. — [HF model card](https://huggingface.co/Datadog/Toto-Open-Base-1.0). BOOM = 350M observations across 2,807 real production observability series (vendor-reported). — [Datadog blog](https://www.datadoghq.com/blog/ai/toto-boom-unleashed/)
- **Toto 2.0** (released 14 May 2026): 4M, 22M, 313M, 1B, 2.5B parameters, Apache-2.0; pretrained only on Datadog observability data + synthetic series (no public forecasting data); single-pass decoding (Toto 1.0 needed up to 16 autoregressive steps for a 1,024-step forecast); the 313M runs at roughly Chronos-2 (120M) latency; 4M called "a strong option for edge deployment"; quick-start falls back to CPU; training context 4,096. BOOM CRPS rank (lower better): 2.5B 3.88, 1B 3.96, 313M 4.25, 22M 5.52, Toto 1.0 6.94, 4M 7.17, Chronos-2 7.39. GIFT-Eval foundation-model CRPS rank: 2.5B 19.5, 313M 20.5, Chronos-2 22.4, 22M 25.7. Anomaly detection is not evaluated; RCA is listed as a future goal. Vendor-reported. — [Datadog Toto 2.0 blog](https://www.datadoghq.com/blog/ai/toto-2/); [arXiv 2605.20119](https://arxiv.org/pdf/2605.20119)
- Moirai 2.0 (Salesforce, Nov 2025): small variant 11.4M parameters; **CC BY-NC 4.0** (non-commercial); 5th on MASE and 6th on CRPS on GIFT-Eval in its own paper. — [arXiv 2511.11698](https://arxiv.org/pdf/2511.11698); licence/size via [beri.net (secondary)](https://www.beri.net/article/timesfm-vs-chronos-vs-moirai-time-series-foundation-model-licence-bigquery-sagemaker-cost-2026)
- TimesFM 3.0 (Google Research blog, 31 Aug 2026): 330M decoder-only, >1 trillion pretraining points, weights under a **non-commercial, non-production licence**; Google claims best average rank on GIFT-Eval / FEV-Bench / TIME (launch material, no peer-reviewed task tables). TimesFM 2.5 weights are Apache-2.0. — [beri.net (secondary)](https://www.beri.net/article/timesfm-vs-chronos-vs-moirai-time-series-foundation-model-licence-bigquery-sagemaker-cost-2026)
- Sundial is reported as Apache-2.0 with CPU support not stated on its card (secondary summary only). — [beri.net / search summary](https://www.beri.net/article/timesfm-vs-chronos-vs-moirai-time-series-foundation-model-licence-bigquery-sagemaker-cost-2026)

**TSFMs in RCA**
- Searches for TSFM-based microservice RCA found none; the closest is ServiceGraph-FM, a self-supervised **graph** foundation model pretrained on production cluster traces that keeps 78.3% of its fully fine-tuned performance when deployed zero-shot on unseen architectures. — [Univ. of Bristol record](https://research-information.bris.ac.uk/en/publications/servicegraph-fm-a-graph-based-model-with-temporal-relational-diff/)
- RUN (AAAI 2024) uses a forecasting model for neural Granger causal discovery in RCA (not a foundation model); in the ASE'24 benchmark it took 1,078–4,938 s per case and often performed like random (see Q4). — [arXiv 2402.01140](https://arxiv.org/pdf/2402.01140); [ASE'24 study](https://arxiv.org/html/2408.13729v1)

### Inferences
**Technique card N1 — "Foundation-model residual scoring" as a drop-in anomaly channel**
- *What:* for each metric, forecast the post-onset window from the pre-onset context with a small TSFM; score = how far observed values fall outside predicted quantiles, e.g. `u_t = F̂_t(x_t)` (predictive CDF from the 21 Chronos-2 quantiles, or 9 Toto quantiles) → tail probability `p_t = 2·min(u_t, 1−u_t)`; per-metric score `S = −log10(min_t p_t)` or a quantile-exceedance count. Plug S into PRISM-style internal/external pooling in place of robust z.
- *Why it could help:* handles seasonality/trends that make median/IQR baselines brittle; gives probabilistic per-metric p-values that feed the conformal/abstention layer directly.
- *CPU cost (estimate):* weights in fp32 ≈ 4 bytes/param → Bolt-tiny ≈ 36 MB, Chronos-2-small ≈ 112 MB, Chronos-2 ≈ 480 MB, Toto-2.0-22M ≈ 88 MB, Toto-2.0-2.5B ≈ 10 GB (too big for 16 GB laptops alongside everything else). GPU throughput of Chronos-2 is 300 series/s on an A10G; assuming CPU is 10–30× slower, Chronos-2 base would score ~10–30 series/s and ~1,000 series in ~0.5–2 min per incident; Bolt-tiny/Toto-4M should be far faster. **Must be measured** — no CPU benchmark was found.
- *Paper framing:* "Do time-series foundation models help microservice RCA? A controlled zero-shot study on RCAEval" — first such study (none found); report accuracy *and* calibration (p-value uniformity on normal windows) *and* CPU latency; include contamination check (BOOM-trained Toto vs public-data Chronos).
- *Risks:* (1) TSB-AD evidence says zero-shot TSFMs ≈ classical, so gains may be nil; (2) RCAEval windows are short — the ASE'24 study varied data length from 60 to 600 points — so forecast context may be too short for seasonality to matter; (3) non-determinism is avoidable (pinned weights, CPU, fixed seeds) but it is still learned AI in the decision path; (4) licence: avoid Moirai 2.0 and TimesFM 3.0 (non-commercial) — use Chronos-2/Bolt, Toto 2.0, TimesFM 2.5 (Apache-2.0).
- *Recommendation:* keep robust-z as the primary scorer; run N1 as an ablation arm ("+TSFM channel") — publishable whether positive or negative.

### Gaps
- No CPU latency numbers for any TSFM were found (only "can run on CPU" claims and GPU throughput).
- Exact TSB-AD leaderboard VUS-PR for MOMENT/TimesFM/Lag-Llama could not be extracted (PDF unreadable; leaderboard page not fetched).
- No independent verification of Toto 2.0 / TimesFM 3.0 claims; MOMENT, Lag-Llama, TimeGPT and Sundial were not separately examined (TimeGPT is a paid API → unsuitable for offline laptops anyway; not sourced here).

---

## Q2. Log representation: Drain/Drain3 vs LLM log parsers (LILAC, LogBatcher, LUNAR, LibreLog, CelerLog); log anomaly detection SOTA; CPU cost

### Takeaway
LLM parsers are now clearly more accurate than Drain on Loghub-2.0 (template accuracy FTA 0.70–0.77 vs Drain 0.28), but are 5–13× slower and need an LLM. The 2026 state of the art (CelerLog) is a **hybrid**: a statistical parser handles ~98.7% of logs and the LLM only sees the ~1.3% "sparse" groups, giving better-than-LLM accuracy at near-Drain speed on a laptop. For Veyltrace, logs matter more for evidence/explanations than accuracy (prior notes), so a "Drain3 + cached LLM refinement of rare templates" is the right level of novelty; deep log anomaly detectors remain unconvincing.

### Cited Findings
- CelerLog (arXiv May 2026) averages over 14 Loghub datasets — GA / PA / FGA / FTA: Drain 0.843 / 0.481 / 0.554 / 0.278; LILAC (label-free) 0.789 / 0.639 / 0.800 / 0.643; LogBatcher 0.914 / 0.786 / 0.909 / 0.722; LUNAR 0.888 / 0.830 / 0.816 / 0.703; CelerLog 0.927 / 0.875 / 0.873 / 0.773. Average parsing time per dataset: Drain 89.6 s, LILAC 771.7 s, LogBatcher 477.1 s, LUNAR 1,126.2 s, CelerLog 110.0 s (60.5 s with 8-core parallelism) — on a MacBook Pro M4 Pro, 24 GB, with GPT-5.2 via API. Router sends 98.7% of logs ("dense groups") to a statistical processor and 1.3% to the LLM; ~33.8 LLM calls and 12,236 tokens per dataset (80.2–94.1% fewer tokens than LLM baselines). — [arXiv 2605.26005](https://arxiv.org/html/2605.26005)
- LogBatcher (demonstration-free, batching): better average GA and message-level accuracy than LILAC, edit distance ~0.4% lower; 173 tokens per invocation, 44.0% fewer than LILAC. — [arXiv 2406.06156](https://arxiv.org/pdf/2406.06156)
- LUNAR (unsupervised LLM parser): on par with LILAC on Loghub-2.0 and efficiency "comparable" to Drain (authors' claim; CelerLog's timings above show LUNAR much slower in its setup — conflicting). — [arXiv 2406.07174](https://arxiv.org/html/2406.07174)
- LibreLog (ICSE 2025): unsupervised, uses **local open-source Llama3-8B** (privacy, no API cost); variable-focused grouping + self-reflection + template memory; 25% higher parsing accuracy and 2.7× faster than SOTA LLM parsers (LILAC, LLMParser) over >50M Loghub-2.0 logs; code at GitHub `zeyang919/LibreLog`. — [arXiv 2408.01585](https://arxiv.org/html/2408.01585v3); [ICSE 2025 listing](https://conf.researchr.org/details/icse-2025/icse-2025-research-track/75/LibreLog-Accurate-and-Efficient-Unsupervised-Log-Parsing-Using-Open-Source-Large-Lan)
- A configuration-free statistic-based parser paper (2025): Drain average GA 0.840, ~1.6 h to parse all 14 Loghub-2.0 datasets; a preprocessed Drain variant is "statistically on the same performance level as LogBatcher" on PA and FTA. — [arXiv 2508.09366](https://arxiv.org/pdf/2508.09366)
- LogLLM: BERT embeddings + Llama classifier with a projector, regex preprocessing instead of a parser; claims SOTA on four public datasets (mirror summary). — [arXiv 2411.08561](https://arxiv.org/pdf/2411.08561)
- LogEval warns that on imbalanced logs a detector can reach accuracy 0.97 with F1 = 0. — [arXiv 2407.01896](https://arxiv.org/pdf/2407.01896)
- An April 2026 benchmark compares Drain/Spell/AEL + ML classifiers, fine-tuned BERT/RoBERTa and prompted GPT-3.5/4/LLaMA-3 on HDFS/BGL/Thunderbird/Spirit across accuracy, latency, cost and label needs (tables not retrieved). — [arXiv 2604.12218](https://arxiv.org/pdf/2604.12218)
- (Prior notes already cite: ICSE 2024 — KNN beats deep log AD ~1,000× faster; Drain3 `change_type` events; RCAEval has no logs for Sock Shop.)

### Inferences
**Technique card N2 — Hybrid deterministic log parsing with an "LLM template oracle" offline**
- *What:* Drain3 online; templates that stay rare (e.g., < k occurrences) or contain many wildcards are batched to a local small LLM (LibreLog-style, or a quantized 3–8B model) **once, offline**, and the refined template map is frozen into a versioned file → runtime parsing is a deterministic lookup; receipts store the template-map hash.
- *CPU cost (estimate):* only ~1–2% of lines (CelerLog's 1.3% sparse share) reach the LLM; with dedupe of identical messages, an RCAEval RE3 case window should produce tens to low hundreds of unique sparse templates → minutes of local 4-bit 7–8B inference on a 16 GB laptop (unmeasured).
- *Paper framing:* minor contribution ("template quality vs RCA accuracy": does better FTA change root-cause accuracy?) — a clean ablation nobody has published for RCA. Risk: probably small effect because PRISM-class metric methods already do well on code faults; logs mainly add explanations.
- *Not recommended:* deep/LLM log anomaly detectors (LogLLM etc.) — expensive, label-hungry, unconvincing vs simple baselines.

### Gaps
- No study found linking log-parsing accuracy to downstream RCA accuracy.
- CPU-only timings for LibreLog's Llama3-8B pipeline were not found.
- "Log foundation models" (pretrained log encoders) were not specifically located beyond LogLLM-style BERT/Llama pipelines.

---

## Q3. Trace analysis: critical path, span-level anomaly detection, trace-based causal inference, GNNs on traces — do simple methods win?

### Takeaway
No 2024–26 head-to-head showing GNNs beat simple trace statistics on a public RCA benchmark was found; GNN papers compare mostly against other learned models. The most transferable recent result is GALA's TWIST trace score, which raised BARO's AC@1 on RCAEval RE2-OB from 14.4% to 36.7% on a 8-CPU/16 GB/no-GPU VM. Critical-path analysis (Uber CRISP) is a mature, open-source, deterministic tool that has **not** been combined with spectrum-based localization in the RCA literature I found — a cheap novelty.

### Cited Findings
- CRISP (USENIX ATC 2022, Uber): critical-path analysis over large numbers of Jaeger traces; top-down mode (per endpoint, for drilling into latency root causes), bottom-up mode (ranks interior APIs by latency impact across endpoints), and on-the-fly anomaly detection; diffing P50 vs P95 critical paths to root-cause tail latency; applied to ~40K endpoints; open source at `github.com/uber-research/CRISP`. — [USENIX ATC'22](https://www.usenix.org/conference/atc22/presentation/zhang-zhizhou); [Uber blog](https://uber.com/blog/crisp-critical-path-analysis-for-microservice-architectures/)
- Critical-path caveat: speeding up a service on the critical path may not speed up the request proportionally because of overlap; the path must be recomputed. — [Uber blog](https://uber.com/blog/crisp-critical-path-analysis-for-microservice-architectures/)
- GALA (arXiv Aug 2025): combines a metric ranker (BARO / CausalRCA / Granger) with a trace module TWIST and an LLM re-ranking loop; on RCAEval RE2-OB (90 incidents), AC@1 / Avg@3 / Avg@5 (%): BARO 14.44 / 61.48 / 74.22; TraceRCA 13.19 / 41.39 / 61.32; GALA(BARO, GPT-4.1-mini) 42.22 / 67.78 / 77.33; **TWIST alone raised BARO AC@1 from 14.4% to 36.7%**; hardware 8 CPU cores, 16 GB RAM, no GPU; mean 5.54 agent rounds; evaluated on one dataset. — [arXiv 2508.12472](https://arxiv.org/html/2508.12472v1). Note: GALA's BARO AC@1 (14.4%) is far below BARO figures in other RCAEval reports (e.g., 0.67 AC@1 on RE2-TT in the RCAEval paper, per prior notes), suggesting a different granularity or setup — numbers are not directly comparable across papers.
- Sleuth (ASPLOS 2024) uses a GNN over spans and a pre-trained model can transfer to other microservice applications without retraining or with few-shot fine-tuning (survey description; Sleuth's own numbers not retrieved). — [Failure-diagnosis survey, arXiv 2407.01710](https://arxiv.org/pdf/2407.01710)
- GTrace (FSE 2023 industry): group-wise trace anomaly detection (cluster traces by shared sub-structure + group-wise VAE), 21.9–28.2× speedup over point-wise methods; code `github.com/netmanaiops/gtrace`. — [FSE'23 listing](https://2023.esec-fse.org/details/fse-2023-industry/2/From-Point-wise-to-Group-wise-A-Fast-and-Accurate-Microservice-Trace-Anomaly-Detecti); [GitHub](https://github.com/netmanaiops/gtrace)
- A comparative study (venue/peer review unverified) on Train Ticket (106,312 traces, 35 services) reports graph-based models up to F1 0.954 vs ~0.741 for LSTM sequence models — learned vs learned, no statistical baseline. — [KazNU journal](https://jpcsit.kaznu.kz/index.php/kaznu/en/article/view/304)
- RCLAgent analyses each request in a time window separately and majority-votes per-request root causes. — [arXiv 2508.20370](https://arxiv.org/pdf/2508.20370)
- (Prior notes already cite: TraceRCA ≈ metric BARO on RE2-TT; MicroRank weak; head sampling cut TraceRCA A@1 from 0.656 to 0.25; parent IDs not listed in RCAEval traces.)

### Inferences
**Technique card N3 — Critical-path-weighted spectrum localization (CP-SBFL)**
- *What:* reconstruct each trace's critical path (CRISP algorithm; needs parent links or time-containment reconstruction from prior notes T3b). Weighted spectrum counts: `e_f(s) = Σ_{failing traces} w_s(trace)` where `w_s` = share of the trace's critical-path time spent in s's self-time (0 if s is off-path); same for `e_p`. Then Ochiai/DStar as before. Also compute "critical-path excess" = post-onset P95 minus baseline P95 critical-path self-time per service (CRISP's P50-vs-P95 diff).
- *Why:* plain SBFL penalizes ubiquitous services and cannot separate a slow callee from its blocked callers; weighting by critical-path *self-time* attributes latency to the service actually on the path. Off-path parallel calls stop polluting scores.
- *CPU:* critical path per trace is O(spans log spans); with ≤50k sampled traces per window, seconds in vectorized pandas/numba (estimate).
- *Paper framing:* "critical-path-aware trace spectra" as an evidence channel + ablation vs plain Ochiai and TraceRCA on RCAEval RE2/RE3 (TT/OB). Risk: if RCAEval lacks parent IDs, containment reconstruction errors propagate; async calls.
- *GNN verdict:* skip GNNs — no evidence they beat statistics on public RCA benchmarks, they need training data, and a 1-month laptop build can't tune them.

### Gaps
- No public head-to-head of statistical trace baselines vs GNN trace RCA found.
- TWIST's exact formula was not extracted (described as CIRCA-inspired delay scoring).
- CRISP's handling of clock drift and async spans not reviewed.

---

## Q4. Causal discovery and causal inference for RCA (PC/FCI/PCMCI/Granger, NOTEARS-family, RCD, DoWhy-GCM attribution, Shapley, CIRCA, IDI, LLM priors) — what is fast enough for 10–50 services / 1000s of series on CPU?

### Takeaway
Benchmarks are damning for **full causal discovery**: on synthetic 10–50-node graphs F1 is only 0.1–0.54, PC/FCI run out of memory at 50 nodes in one generator, PCMCI is worst (F1 0.04–0.12), and most graph-learning RCA methods perform "similarly to Dummy". Each causal method wins mainly on its own synthetic generator (RCD Avg@5 0.89 on RCD10 but 0.28 on CIRCA10; BARO the reverse). On PetShop, simple ranked correlation beats all graph-free causal methods. The defensible, novel use of causality on a laptop is **hypothesis verification** — given a known call graph (from traces), test the top-k candidates with cheap local mechanism tests (IDI in-distribution interventions, Smooth Traversal / Score Ordering, CIRCA regression) — not graph learning over thousands of series.

### Cited Findings
- ASE'24 "How far are we?" (Pham, Ha, Zhang) — causal discovery on synthetic data, F1 / SHD: PC 0.49/16 (CIRCA10), 0.38/104 (CIRCA50), 0.24/120 (RCD50); FCI 0.43/19, 0.33/115; Granger 0.46/26, 0.18/463; **PCMCI 0.12/32, 0.04/986, 0.06/1223 (RCD50)**; DirectLiNGAM 0.40/22, 0.22/249; NTLR (NOTEARS low-rank) 0.32/21, 0.14/131. "F1 values for all methods fall from 0.1 to 0.54". GES, DirectLiNGAM and NTLR were excluded for >1 h per case on some data; PC and FCI ran **out of memory on RCD50**. — [arXiv 2408.13729](https://arxiv.org/html/2408.13729v1)
- Same study, RCA runtime (s per case): NSigma and BARO 0.01 everywhere; RCD 0.06–3.08 on synthetic/SS/OB and 12.44 on Train Ticket; CIRCA 0.06–7 but **3,792 s on Train Ticket**; PC-PageRank 129.65 s on TT; CausalAI 643 s on TT; CausalRCA 51–1,326 s; MicroCause up to 1,900 s; RUN 1,078–4,938 s; NTLR-PageRank up to 6,180 s. Avg@5 (perfect failure time): BARO 0.22 (RCD10), 0.05 (RCD50), 0.92 (CIRCA10), 0.87 (CIRCA50); RCD 0.89, 0.62, 0.28, 0.05; NSigma 0.21/0.06/0.88/0.85; CIRCA 0.34/0.08/0.34/0.06; random "Dummy" 0.3/0.06/0.3/0.06. PC/FCI/Granger/LiNGAM/fGES/NTLR-based PageRank/random walk, CausalAI, RUN, MicroCause "mostly perform similarly to Dummy". RCD's Avg@5 on Online Boutique rose from 0.13 to 0.79 as data length grew from 60 to 600 points. Conclusion: "no method stands out in all situations"; synthetic performance "may not accurately reflect" real systems. — [arXiv 2408.13729](https://arxiv.org/html/2408.13729v1); [ASE 2024 listing](https://conf.researchr.org/details/ase-2024/ase-2024-research/57/Root-Cause-Analysis-for-Microservice-System-based-on-Causal-Inference-How-Far-Are-We)
- PetShop (CLeaR 2024, Amazon): 41 components, 68 injected latency/availability issues; top-1 / top-3 recall — traversal (graph given) 0.57/0.57 low latency, 1.00/1.00 temporal latency, 0.33/1.00 high availability; CIRCA (graph) 0.36/0.86 low latency, 0.00/0.00 high availability; DoWhy counterfactual attribution (graph) 0.36/0.71 low latency, 0.00/0.42 low availability, 0.00/0.00 high availability; RCD (no graph) 0.07/0.21 low latency; ε-diagnosis ~0; **plain ranked correlation (no graph) 0.43–0.83 top-1**. Authors: without the graph "none of the proposed approaches outperform the basic ranked correlations"; the Shapley-based counterfactual method had the longest run-time; **all methods produced false root causes during normal operation**. Data/code: amazon-science petshop repo (uses PyRCA and DoWhy). — [arXiv 2311.04806](https://arxiv.org/html/2311.04806v2); [PMLR v236](https://proceedings.mlr.press/v236/hardt24a.html)
- IDI — "Robust Root Cause Diagnosis using In-Distribution Interventions" (ICLR 2025): a node is a root cause if it is anomalous **and** setting it to usual values makes the target non-anomalous; instead of SCM counterfactuals (unreliable because anomalies are out-of-distribution), IDI queries the fitted SCM only at in-distribution inputs (interventional estimates), with error bounds for both; beats nine RCD baselines on synthetic data and PetShop; code `github.com/nlokeshiisc/IDI_release`. — [arXiv 2505.00930](https://arxiv.org/abs/2505.00930)
- "Root Cause Analysis of Outliers with Missing Structural Knowledge" (NeurIPS 2025, Orchard, Okati, Garrido Mejia, Blöbaum, Janzing): **Smooth Traversal** uses jumps in marginal (information-theoretic) anomaly scores along causal paths and needs no anomaly cut-off (requires the graph); **Score Ordering** needs only the ordering of anomaly scores and no graph, justified for polytrees. — [arXiv 2406.05014](https://arxiv.org/html/2406.05014v3); [NeurIPS 2025](https://papers.nips.cc/paper_files/paper/2025/hash/ec87ccda449e853c2876093d682cf3a5-Abstract-Conference.html). (Prior notes: PRISM reports Smooth-Traversal 0.05 Top-1 on RCAEval with an instrumented graph.)
- DoWhy-GCM (JMLR 2024) supports root causes of outliers and distribution changes and Shapley-based attribution of mechanisms; Amazon's "distribution change attribution" identifies a defective service. — [JMLR v25](https://jmlr.org/papers/v25/22-1258.html); [Amazon Science blog](https://www.amazon.science/blog/aws-contributes-novel-causal-machine-learning-algorithms-to-dowhy)
- LLM priors for causal discovery: running PC/Exact Search/DirectLiNGAM, converting LLM confidence into prior constraints and re-running "consistently improved" accuracy on benchmark datasets — [arXiv 2402.01454 (alphaXiv overview)](https://alphaxiv.org/overview/2402.01454v5); a position paper reports LLM predictions as PC priors beat LLM-only and statistics-only — [arXiv 2510.16530](https://arxiv.org/abs/2510.16530v1); LLMs as conditional-independence oracles give conservative answers vs experts — [arXiv 2406.07378](https://arxiv.org/html/2406.07378v1); LLMs may reproduce benchmark graphs verbatim (memorization complicates evaluation) — [arXiv 2602.16481](https://arxiv.org/html/2602.16481v1)
- LagRCA (FSE 2026 industry, Alibaba): lag-aware spatio-temporal causal inference, 88.3% top-5 localization, deployed in production. — [FSE 2026 listing](https://conf.researchr.org/details/fse-2026/fse-2026-industry-papers/18/Bridging-the-Delay-Lag-Aware-Spatio-Temporal-Causal-Inference-for-Microservice-Root-)

### Inferences
**Technique card N4 — "Verification trials" = local interventional tests on top-k hypotheses (IDI-lite on the trace call graph)**
- *What:* for each top-k candidate X (k ≤ 5) and each anomalous downstream symptom Y (e.g., frontend latency), fit a small per-node mechanism on baseline data only (linear/robust regression of each node's latency on its callees' latencies and its own internal metrics, along the trace-derived call graph). **Trial:** replace X's post-onset values by in-distribution values (its baseline median or baseline quantile-matched resample), propagate through fitted mechanisms to Y, and measure `Δ_Y(X) = z(Y_obs) − z(Y_do(X=normal))`. Accept X if it is anomalous and Δ restores Y below threshold (IDI's two criteria). Report the "trial receipt" (before/after z per node).
- *Why novel for RCA:* turns causal inference into a **hypothesis-verification stage** with an interpretable, replayable test, rather than a ranker that must learn a graph from thousands of series (which benchmarks say fails). IDI was evaluated on PetShop/synthetic only — applying it as a verifier on RCAEval with trace-derived graphs is untested (novel).
- *CPU:* k × (#nodes ≤ 50) small regressions on a few hundred points → milliseconds to <1 s per incident (estimate).
- *Alternatives:* Score Ordering (no graph, O(n log n), polytree assumption) as a cheap prior; Smooth Traversal when the graph is trusted; CIRCA regression-based hypothesis testing for its descendant adjustment (avoid its graph-building cost: 3,792 s on TT).
- *Avoid:* PCMCI/NOTEARS/Granger graph learning over all series; LLM-prior discovery (memorization confound, little RCA evidence). RCD (≈3–12 s per case) is the only discovery-style RCA method fast enough to include as a baseline.
- *Risks:* mechanism fits on short baselines; call graph wrong under sampling; network faults (DELAY/LOSS) are not "node values" — model them as edge mechanisms.

### Gaps
- No RCAEval numbers for IDI, Smooth Traversal or DoWhy anomaly attribution found (PRISM's Smooth-Traversal figure is the only one).
- Causal-discovery runtimes on synthetic data are in a supplementary table not retrieved.
- No LLM-prior causal discovery paper evaluated on microservice RCA was found.

---

## Q5. Change-aware RCA: correlating deployments, config changes, feature flags, k8s events with anomalies — and evidence that most incidents are change-induced

### Takeaway
Industrial evidence that changes dominate outage triggers is strong (Google 2010–2017: binary pushes 37% + configuration pushes 31% = 68% of outages; vendor trackers 32–55%), and industrial systems (Azure Gandalf, Meta SHC, WeChat ChangeRCA) localize bad changes with simple spatial–temporal correlation and changed-vs-control cohort comparison. Yet **the public RCA benchmarks (RCAEval, PetShop, OpenRCA) used by academic methods contain no change events**, so change-awareness is almost absent from academic microservice RCA. This is the largest "novelty per hour" gap for Veyltrace.

### Cited Findings
- Google SRE workbook, Appendix C (thousands of postmortems, 2010–2017) — top outage triggers: binary push 37%, configuration push 31%, user behavior change 9%, processing pipeline 6%, service provider change 5%, performance decay 5%, capacity management 5%, hardware 2%. Root-cause categories: software 41.35%, development process failure 20.23%, complex system behaviors 16.90%, deployment planning 6.74%, network failure 2.75%. — [sre.google workbook](https://sre.google/workbook/postmortem-analysis/)
- Google's SRE book states "roughly 70% of outages are due to changes in a live system" (verified only through reader highlights of the book). — [Goodreads highlights](https://www.goodreads.com/notes/29619107-site-reliability-engineering/1190636-paul)
- Control Plane's cloud outage tracker (62 major AWS/Azure/GCP/Cloudflare outages since 2020, updated 21 Oct 2026): configuration or deployment change is the most common cause (20/62, 32%); changes plus code 55% (vendor source). — [Control Plane](https://controlplane.com/blog/post/cloud-outage-tracker)
- Uptime Institute 2025: IT and networking issues were 23% of impactful outages in 2024, linked to complexity and "the resulting increase in change-management failures and misconfigurations". — [Uptime Institute 2025 report](https://uptimeinstitute.com/uptime_assets/d7c049ef5b02a6e0a15540a3e5cb8fbf742c7fa54a1af6caeaaab32b7c15d443-GA-2025-05-annual-outage-analysis.pdf)
- Meta Service Health Checks (arXiv Aug 2026): checks compare the **changed cohort against a control cohort** from the unchanged fleet (absorbing diurnal/weekly seasonality), or a control time window for single-host services; dependency-aware checks use an offline dataset of cross-service correlations; fleet-wide false-positive rate cut from 12.1% to 2.7% in a year; cites ThousandEyes that configuration and deployment changes are "the single largest category of outage triggers across cloud providers"; distributed tracing for causal attribution is future work. — [arXiv 2608.20513](https://arxiv.org/html/2608.20513)
- Gandalf (NSDI 2020, Azure): correlates each fault signal against all ongoing rollouts with a spatial + temporal correlation algorithm and decides go/stop; 92.4% precision / 100% recall (data-plane) and 94.9% / 99.8% (control-plane) over 1,200+ region-level deployments; >70% of rollouts span multiple clusters and >20% last 1,000+ minutes. — [USENIX NSDI'20](https://www.usenix.org/conference/nsdi20/presentation/li); [paper PDF](https://web.eecs.umich.edu/~ryanph/paper/gandalf-nsdi20.pdf)
- ChangeRCA (FSE 2024, WeChat): defines "root cause change analysis" — localize the defective change among several candidate changes behind a change-inducing incident; argues existing abnormal-change detection fails "due to their disregard for the propagation of faults"; real WeChat data + 81 simulated defective changes; **Top-1 hit rate 85%**. — [FSE 2024 listing](https://2024.esec-fse.org/details/fse-2024-research-papers/3/ChangeRCA-Finding-Root-Causes-from-Software-Changes-in-Large-Online-Systems)
- FSE 2025 industry: multimodal LLM-based change assessment for microservices covering erroneous-change detection, failure triage and root-cause change analysis with RAG. — [FSE 2025 listing](https://conf.researchr.org/details/fse-2025/fse-2025-industry-papers/33/A-Multimodal-Intelligent-Change-Assessment-Framework-for-Microservice-Systems-Based-o)

### Inferences
**Technique card N5 — Change-event channel + "decoy change" benchmark extension (RCAEval-C)**
- *Channel math:* for each change event c (deploy, config, flag flip, k8s rollout/restart/HPA scale, with timestamp t_c and target set T_c): `Temporal(c) = exp(−max(0, τ_onset − t_c)/λ) · 1[t_c ≤ τ_onset + δ]`; `Spatial(c, s) = 1` if s ∈ T_c, decaying with call-graph distance from T_c (blast radius); **Cohort test** (Meta/Gandalf style): if c touched only some replicas/pods, compare anomaly scores of changed vs unchanged replicas (Mann–Whitney or difference of medians) → p-value. Change score for service s = max_c Temporal·Spatial·(1 − p_cohort). Feed as one channel to fusion; produce a receipt "deployment v1.42 to cartservice 38 s before onset; changed pods z=7.1 vs unchanged z=0.4".
- *Benchmark extension (the contribution):* RCAEval has injection timestamps but no changes. Synthesize change logs per case: one **true change** aligned with the injected fault (e.g., "deploy cartservice" at t_inj − U(0, 120 s)) with probability π, plus Poisson **decoy changes** on random services in the window. Report how accuracy varies with π and decoy rate, and compare a naive "blame most recent change" heuristic vs fused evidence. Also run the live demo with real `kubectl rollout`/config changes in the team's own Online Boutique deployment.
- *Why publishable:* industrial evidence says changes are the dominant trigger, but no academic RCA benchmark models them; quantifying "how much change metadata helps, and how badly decoys hurt" is new and cheap.
- *CPU:* trivial. *Risks:* synthetic change logs are an assumption reviewers will attack — mitigate with the live, real-change demo cases and by reporting the decoy-robust regime; avoid over-claiming real-world gains.

### Gaps
- No peer-reviewed 2024–2026 figure isolating the share of microservice incidents that are change-induced (Google 2010–2017 workbook is the best primary source).
- Gandalf/ChangeRCA code availability not confirmed; ChangeRCA's algorithm details and baselines not retrieved.
- No public microservice RCA dataset with real deployment/config events was found.

---

## Q6. Multi-fault and cascading failures; unseen-system generalization; robustness to missing telemetry

### Takeaway
All three are recognized as open problems in 2025–26 papers, but solutions are heavy learned models (hierarchical RL + GAT for multi-root-cause, self-supervised missing-aware fusion in ARMOR, graph foundation models for transfer). Evidence on generalization is sobering: causal methods excel only on their own data generators, and LLM agents on real production telemetry (OpenRCA) remain at 11–21% exact accuracy. A cheap, deterministic, publishable angle is an **evaluation protocol** — a telemetry-ablation matrix and leave-one-system-out testing with calibrated abstention — rather than a new model.

### Cited Findings
- ARMOR (ASE 2026): self-supervised RCA under missing modality; argues data absence is driven mainly by observability-infrastructure vulnerabilities (not the faulty services) and that complete modality blackouts occur; uses modality-specific encoders + missing-aware gated fusion with learnable placeholders; anomaly detection and localization need no fault labels (triage uses failure-type labels); claims robust accuracy "even with severe modality loss" (numbers not in the abstract; no code link found). — [arXiv 2603.25538](https://arxiv.org/abs/2603.25538)
- RCAEval: 735 failure cases, 11 fault types; notes that public datasets often provide incomplete telemetry. — [arXiv 2412.17015](https://arxiv.org/pdf/2412.17015) (prior notes: no logs/traces for Sock Shop in RE2/RE3)
- Multi-root-cause localization via an active-intervention framework (hierarchical RL to infer root causes + graph attention network predicting which fault scenarios a cause triggers); argues passive rule/graph-propagation methods struggle when root causes interact (DOI 10.1145/3808180, ISSN 2994-970X — the PACMSE/FSE series; venue/year unverified). — [CiteDrive record](https://www.citedrive.com/en/discovery/towards-the-localization-of-multi-root-cause-failures-in-microservice-systems-an-active-intervention-framework/)
- TORAI (FSE 2026): multi-source RCA for "blind spots" in the service call graph — clusters services by symptom severity, ranks within clusters, aggregates across clusters because the root cause may sit in the second-highest severity cluster. — [FSE 2026 listing](https://conf.researchr.org/details/fse-2026/fse-2026-research-papers/64/TORAI-Multi-Source-Root-Cause-Analysis-for-Blind-Spots-in-the-Microservice-Service-C); [arXiv 2604.13522](https://arxiv.org/pdf/2604.13522)
- AMER-RCL (ICSE-SEIP 2026) notes cascading failures can only be reliably detected by analysing aggregate patterns across multiple alerts. — [arXiv 2601.02732](https://web3.arxiv.org/pdf/2601.02732)
- HyperODE RCA (2026) argues pairwise service graphs miss coordinated multi-service failures and uses hypergraphs with adaptive modality routing over logs/traces/metrics/events. — [arXiv 2605.00351](https://arxiv.org/pdf/2605.00351)
- Transfer: ServiceGraph-FM retains 78.3% of fine-tuned performance zero-shot on unseen architectures — [Bristol record](https://research-information.bris.ac.uk/en/publications/servicegraph-fm-a-graph-based-model-with-temporal-relational-diff/); Sleuth transfers with zero/few-shot fine-tuning — [survey 2407.01710](https://arxiv.org/pdf/2407.01710)
- Generator dependence: BARO Avg@5 0.92 on CIRCA10 but 0.22 on RCD10; RCD 0.89 on RCD10 but 0.28 on CIRCA10 — [ASE'24](https://arxiv.org/html/2408.13729v1)
- OpenRCA (ICLR 2025, Microsoft): 335 failure cases from real production-like telemetry; answer must match time, component and reason; Claude 3.5 with the RCA-agent baseline solved 11.34% — [ICLR 2025 paper](https://proceedings.iclr.cc/paper_files/paper/2025/file/d29b8d53678015079e1d245c023e49d2-Paper-Conference.pdf); oracle-KPI Claude 3.5 ~5.37%, random-sampling ~3.88% (press summary) — [36Kr](https://www.36kr.com/p/3261133011681417). "OpenRCA 2.0" (500 instances): 11 frontier LLMs average 20.7% exact match, 34.1% F1 (summary; venue unverified) — [Emergent Mind](https://www.emergentmind.com/papers/2606.27154). A 2026 study on OpenRCA finds the required evidence is present in most failures — the bottleneck is reasoning/domain knowledge, and both classical causal discovery and LLM multi-agent systems "fail to reliably identify root causes". — [arXiv 2607.13548 abstract](https://tldr.takara.ai/p/2607.13548)
- New multimodal datasets: AnoMod (Train Ticket + SocialNetwork) — [arXiv 2601.22881](https://arxiv.org/pdf/2601.22881)

### Inferences
**Technique card N6 — Telemetry-ablation matrix + leave-one-system-out (LOSO) protocol with graceful degradation**
- *What:* for every RCAEval case, re-run Veyltrace with modality masks {metrics only, +traces, +logs, all}, with service-level masks (drop 10/30/50% of services' metrics), with trace sampling rates {100, 10, 1%}, and with clock-skew noise. Report accuracy, conformal set size and abstention rate per cell, and calibrate thresholds on systems A,B → test on C (LOSO).
- *Engine design for robustness:* every channel outputs "no evidence" (not zero) when its input is absent; fusion re-normalizes over available channels; the conformal layer is Mondrian by "available-modality pattern" so set sizes grow honestly when data are missing.
- *Multi-fault:* output a set, not a single answer, and test "explanatory coverage" (prior notes T7b: fraction of anomalous services explained by the hypothesis' blast radius); flag a second fault when coverage < threshold, then greedily add the next hypothesis (hitting-set). Evaluating on synthetic overlays of two RCAEval cases would be non-physical — prefer a few genuine two-fault injections in the live demo cluster.
- *Paper framing:* "How gracefully does RCA degrade?" — the robustness curves are the contribution; cheap (re-runs of a ~10 ms–1 s pipeline) and nobody reports them for statistical RCA (ARMOR does it for its learned model).
- *Risk:* the matrix multiplies runtime (e.g., 4 modality × 4 service-drop × 3 sampling = 48 runs × 735 cases ≈ 35k runs — fine at ≤1 s each, ~10 h CPU; estimate).

### Gaps
- ARMOR's quantitative missing-modality results and datasets were not retrieved.
- No 2024–26 public benchmark with genuine concurrent multi-fault injections was found.
- OpenRCA 2.0 venue/date unverified.

---

## Q7. Uncertainty: conformal prediction for rankings / top-k sets, calibration, abstention

### Takeaway
A fresh 2026 search again found **no application of conformal prediction to microservice RCA** — the novelty claim from the prior notes still stands. New methodological support exists: conformal guarantees for full rankings (NeurIPS 2025), conformal risk control for ranked retrieval, and monotone score refinement that shrinks sets at equal coverage. PetShop's finding that *all* methods emit false root causes during normal operation is a strong, citable motivation for a "no-fault" abstention option.

### Cited Findings
- Transductive Conformal Inference for Full Ranking (NeurIPS 2025): given n items with known relative ranks and m new items ranked by a black box, gives valid prediction sets for each new item's rank and controls the false coverage proportion; experiments with RankNet and LambdaMART. — [NeurIPS 2025](https://papers.neurips.cc/paper_files/paper/2025/hash/0922ceebb39f1c76e64ef03d0885fa82-Abstract-Conference.html); [arXiv 2501.11384](https://arxiv.org/abs/2501.11384v3)
- Conformal Ranked Retrieval: conformal risk control on a two-stage retrieval + ranking pipeline with separate risks, tested on MSLR-WEB, Yahoo LTRC, MS MARCO. — [arXiv 2404.17769](https://arxiv.org/html/2404.17769v1)
- Score refinement: a simple monotone transformation of retrieval scores gives significantly smaller conformal sets with the same guarantee (BEIR). — [arXiv 2410.02914](https://arxiv.org/html/2410.02914v1)
- PetShop: all evaluated methods produced false root causes during normal operation (authors leave reduction to future work). — [arXiv 2311.04806](https://arxiv.org/html/2311.04806v2)
- (Prior notes already cite: Angelopoulos & Bates; MAPIE Top-K; Cresswell et al. user study; selective classification; Mondrian split-conformal top-k̂ card.)

### Inferences
**Technique card N7 — Conformal risk control for "set-valued RCA with a no-fault option"**
- *What:* add a pseudo-candidate ∅ ("no actionable root cause / not an incident") to every ranking. On calibration cases include **normal-period windows** (PetShop-style false alarms) whose true label is ∅. Choose a score threshold λ via conformal risk control so that `E[miss(true cause ∉ C_λ)] ≤ α` while minimizing set size; Mondrian strata = fault family × available-modality pattern (N6).
- *Paper framing:* first coverage-guaranteed RCA output, measured with coverage, mean set size, abstention rate and risk–coverage curves; demonstrates calibrated behaviour under telemetry loss (ties to N6) and under unseen systems (LOSO, where exchangeability breaks — report the empirical coverage gap honestly).
- *CPU:* trivial. *Code:* ~50 LOC; MAPIE/crepes optional.
- *Risk:* exchangeability across systems; small per-stratum calibration n (≥ 1/α − 1 needed).

### Gaps
- No empirical precedent of conformal methods in RCA (novelty, but no baseline to compare to): an Oct 2026 web search for conformal prediction + AIOps/RCA/incidents returned only vendor AIOps pages and general reviews — a search negative, not proof of absence; a targeted arXiv/ICSE/FSE/ASE full-text search should confirm before claiming "first".
- Conformal risk control for joint "set + abstain" losses in ranking was not located as a ready-made method; would be an adaptation.

---

## Q8. Rank fusion / ensembles across evidence channels (RRF, Bayesian fusion, learning-to-rank with tiny data)

### Takeaway
Recent RCA systems do aggregate rankings (TORAI aggregates per-severity-cluster rankings; an RCA paper merges symptom-clustering and causal rankers; RCLAgent majority-votes per request; GALA's LLM re-ranking lifted BARO AC@1 from 14.4% to 42.2% on RE2-OB) but **none isolates the fusion rule's contribution with ablations**, and I found no source on learning-to-rank from tiny RCA datasets. With ~735 labelled RCAEval cases, a "fusion-rule shoot-out" (RRF vs Bayesian vs tiny LTR) under leave-one-system-out is a small but solid contribution.

### Cited Findings
- TORAI ranks services within symptom-severity clusters then aggregates, since the root cause may be in the second-highest cluster (no single-method ablation seen). — [arXiv 2604.13522](https://arxiv.org/pdf/2604.13522)
- A 2026 anomaly-detection + RCA paper merges ranked lists from a symptom-clustering method and a causal ranker into one coarse-grained root-cause list. — [arXiv 2606.09942](https://arxiv.org/pdf/2606.09942)
- RCLAgent: per-request analysis with majority vote. — [arXiv 2508.20370](https://arxiv.org/pdf/2508.20370)
- GALA: BARO 14.44% → TWIST fusion 36.7% → LLM re-ranking 42.22% AC@1 on RE2-OB (single dataset, LLM API). — [arXiv 2508.12472](https://arxiv.org/html/2508.12472v1)
- (Prior notes already cite: RRF k=60 (Cormack 2009); RCAEval multi-source variants do not automatically improve — multi-source CIRCA 0.13 Avg@5 on RE2-TT.)

### Inferences
**Technique card N8 — Fusion-rule shoot-out with ≤10 parameters**
- *Arms:* (a) RRF (k=60, no learning); (b) gated RRF (prior notes); (c) naive-Bayes log-likelihood-ratio fusion: per channel j, estimate `P(rank_j = r | root)` vs `P(rank_j = r | not root)` from calibration cases (rank histograms with Laplace smoothing), sum log-ratios — interpretable "each channel adds X bits"; (d) pairwise logistic LTR over ~8–10 channel features (rank and normalized score per channel) with strong L2 — trained LOSO.
- *Evaluation:* Top-1/Top-3/Avg@5 + calibration, per fault family; show when learned fusion overfits (per-system variance).
- *CPU:* seconds. *Risk:* learned fusion = ML in the decision path (rule conflict); tiny data → overfitting; keep RRF as the deterministic default and report learned variants as ablations.

### Gaps
- No published learning-to-rank-with-tiny-data study for RCA was found.
- No ablation isolating fusion gains in TORAI/GALA was retrieved.

---

## Q9. Fault-type classification and remediation suggestion (runbooks, similar-incident retrieval)

### Takeaway
Industrial systems classify root-cause *categories* by retrieving similar historical incidents (RCACopilot: up to 0.766 accuracy on Microsoft incidents), and recent academic work splits RCA into localization then failure-type identification. For a laptop build, deterministic signature rules (prior notes T6b) plus kNN over incident "fingerprints" from RCAEval give fault types; runbook text should come from a fixed fault-type → action table, with the LLM only narrating. A measurable novelty is **receipt-grounded narration evaluation**: GALA shows BLEU is useless for RCA summaries and that expert-judged causal soundness differs sharply between systems.

### Cited Findings
- RCACopilot (Microsoft): collection stage runs incident handlers; prediction stage uses an LLM with retrieved similar historical incidents (temporal-aware similarity, parameters K and decay α); root-cause **category** accuracy up to 0.766 on a year of Microsoft incidents (653 email-service incidents per a secondary blog); collection component in use >4 years. — [ar5iv 2305.15778](https://ar5iv.labs.arxiv.org/html/2305.15778); [Microsoft Research](https://www.microsoft.com/en-us/research/publication/automatic-root-cause-analysis-via-large-language-models-for-cloud-incidents)
- Juniper adapts the RCACopilot idea for network incidents with few-shot retrieval instead of fine-tuning. — [arXiv 2507.03224](https://web3.arxiv.org/pdf/2507.03224)
- CCLH does root-cause localization first and failure-type identification second ("sequential diagnosis"). — [arXiv 2511.17566](https://arxiv.org/html/2511.17566v1)
- TVDiag locates culprit instances and identifies failure types from multimodal data (gains on HR@1 and F1 on two datasets); DiagFusion targets robust diagnosis under failure-type class imbalance. — [arXiv 2407.19711](https://arxiv.org/abs/2407.19711v3); [DiagFusion](https://ar5iv.labs.arxiv.org/html/2302.10512)
- GALA's Remediation Agent writes incident summaries/actions; expert SURE-Score (1–5): causal soundness 4.42 vs 3.41 baseline, incident specificity 4.30 vs 3.10, clarity 3.55 vs 3.65; BLEU 0.0068 vs 0.0090 — authors conclude standard NLG metrics are not effective for RCA summaries (co-author raters = validity threat). — [arXiv 2508.12472](https://arxiv.org/html/2508.12472v1)
- ARMOR jointly does detection, triage (failure-type labels) and localization. — [arXiv 2603.25538](https://arxiv.org/abs/2603.25538)

### Inferences
**Technique card N9 — Fingerprint kNN fault typing + receipt-grounded narration check**
- *Fault typing:* fingerprint = vector of per-channel evidence for the top candidate (internal/external z by metric family, onset Δ, latency quantile-shape ratio Δq50/Δq99, error-code rate, new-template count, change-channel score). Predict fault type by the signature table (deterministic) and report kNN agreement from labelled RCAEval cases (LOSO) as confidence; output "similar past incidents" as the retrieval explanation.
- *Remediation:* static fault-type → runbook map (CPU → scale/throttle; MEM → restart/limit; DELAY/LOSS → check network policy/node; code → roll back latest change of the service — links to N5).
- *Narration check (contribution):* the LLM may only cite facts present in the receipt JSON; an automatic checker extracts every number/service/metric mentioned in the narration and verifies it against receipts → "claim precision" and "hallucination rate" metrics, replacing BLEU. Small local LLM or API; narration stays outside the decision path (rule-compliant).
- *CPU:* kNN over 735 vectors trivial; narration cost depends on the LLM.

### Gaps
- FLASH and other remediation-recommendation systems were not found in searches.
- No public dataset of runbooks aligned with RCAEval fault types exists (would have to be authored).

---

## Q10. Shortlist: which building blocks give Veyltrace v2 a genuinely novel, publishable edge within a 1-month, laptop-only build?

### Takeaway
The strongest paper is **not** a new learned model; it is a **trustworthy, change-aware, telemetry-robust statistical RCA pipeline with verification trials and coverage guarantees**, evaluated more rigorously than prior work (LOSO, telemetry ablation, decoy changes, CPU latency). Rank: (1) conformal set-valued RCA with no-fault abstention, (2) change-event channel + decoy-change benchmark extension, (3) IDI-style verification trials on the trace call graph, (4) telemetry-ablation robustness protocol, (5) critical-path-weighted trace spectra, (6) TSFM residual scoring as an ablation study; lower: hybrid LLM log parsing, fusion shoot-out, receipt-grounded narration metric; avoid: GNNs, full causal discovery, LLM-prior discovery, LLM agents in the decision path.

### Cited Findings
- Headroom and baselines: PRISM 0.68 Top-1 on RCAEval; BARO/NSigma run in 0.01 s per case, RCD 3–12 s, CIRCA up to 3,792 s, RUN up to 4,938 s. — [ASE'24](https://arxiv.org/html/2408.13729v1); PRISM figures in prior notes ([arXiv 2601.21359](https://arxiv.org/html/2601.21359))
- Changes trigger ~68% of Google outages (binary + config pushes). — [sre.google](https://sre.google/workbook/postmortem-analysis/)
- Zero-shot TSFMs ≈ classical on TSB-AD-U (0.319 vs 0.332–0.353 VUS-PR). — [arXiv 2601.00446](https://arxiv.org/html/2601.00446)
- All methods emit false root causes on normal periods (PetShop). — [arXiv 2311.04806](https://arxiv.org/html/2311.04806v2)
- LLM agents on real telemetry reach only 11–21% exact accuracy (OpenRCA / 2.0). — [ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/file/d29b8d53678015079e1d245c023e49d2-Paper-Conference.pdf); [Emergent Mind](https://www.emergentmind.com/papers/2606.27154)

### Inferences
| # | Building block (card) | Evidence of effectiveness | CPU cost (16 GB laptop) | Code / licence | Paper contribution framing | Main risk |
|---|---|---|---|---|---|---|
| 1 | **Conformal set-valued RCA + no-fault abstention (N7 + prior T5)** | No RCA precedent (novel); conformal ranking theory (NeurIPS 2025); PetShop false-alarm problem | ms per incident | ~50 LOC numpy; MAPIE/crepes (BSD) optional | "First RCA with finite-sample coverage guarantees and calibrated abstention; risk–coverage curves" | exchangeability across systems; small strata |
| 2 | **Change-event channel + RCAEval-C decoy benchmark (N5)** | Google 68% push-triggered; Gandalf 92–95% precision; ChangeRCA 85% Top-1; Meta cohort FP 12.1%→2.7% | ms | own code; RCAEval data (check licence) | "Change-aware RCA: benefit of change metadata and robustness to decoy changes" | synthetic change logs — back with live-cluster real changes |
| 3 | **Verification trials via in-distribution interventions (N4)** | IDI beats 9 baselines (ICLR 2025, PetShop); Smooth Traversal/Score Ordering (NeurIPS 2025) | < 1 s for k ≤ 5 candidates (estimate) | IDI_release (GitHub; licence unchecked); DoWhy (MIT) | "Hypothesis verification stage with replayable intervention receipts, on RCAEval" (untested there) | wrong/missing call-graph edges; network faults |
| 4 | **Telemetry-ablation + LOSO robustness protocol (N6)** | ARMOR (ASE'26) shows the problem matters; ASE'24 generator dependence | ~10 h CPU for full matrix (estimate) | own scripts | "How gracefully does statistical RCA degrade?" robustness curves | runtime of full matrix; reviewers may call it 'just evaluation' — pair with #1 |
| 5 | **Critical-path-weighted trace spectra (N3)** | CRISP (Uber, 40K endpoints); TWIST lifted BARO AC@1 14.4→36.7% on RE2-OB | seconds per incident (estimate) | uber-research/CRISP (open source; licence unchecked) | "Critical-path-aware SBFL" ablation vs Ochiai/TraceRCA | RCAEval parent IDs may be absent |
| 6 | **TSFM residual scoring ablation (N1)** | No RCA precedent; TSB-AD says ≈ classical zero-shot | Bolt-tiny/Toto-4M fast; Chronos-2 ~0.5–2 min per 1,000 series (estimate, unmeasured) | Chronos-2/Bolt, Toto 2.0, TimesFM 2.5: Apache-2.0; avoid Moirai 2.0 & TimesFM 3.0 (non-commercial) | "Do observability foundation models help RCA?" (positive or negative result) | likely nil gain; AI in decision path |
| 7 | Hybrid Drain3 + offline LLM template refinement (N2) | CelerLog FTA 0.773 vs Drain 0.278 at near-Drain speed | LLM on ~1% of lines; minutes (estimate) | Drain3 (MIT), LibreLog (GitHub) | "Does template quality matter for RCA?" | small effect on accuracy |
| 8 | Fusion-rule shoot-out (N8) | Aggregation used in TORAI/GALA, never ablated | seconds | own code | "RRF vs Bayesian vs tiny-LTR under LOSO" | overfitting; ML in decision path |
| 9 | Receipt-grounded narration metric + fingerprint kNN typing (N9) | GALA: BLEU useless, expert causal soundness 4.42 vs 3.41; RCACopilot 0.766 category accuracy | LLM-dependent | own code | "Claim precision / hallucination rate for RCA narratives" | LLM cost/latency on laptop |
| ✗ | GNN trace models, full causal discovery (PCMCI/NOTEARS/Granger over 1000s of series), LLM-prior discovery, LLM agents as rankers | F1 0.1–0.54; PCMCI ≤0.12; most ≈ Dummy; OpenRCA ≤21% | minutes–hours per case | — | — | cost, no evidence, non-determinism |

**Suggested paper story (synthesis):** "Veyltrace: verifiable, change-aware root-cause analysis with coverage guarantees" — contributions: (i) set-valued, abstaining RCA with conformal guarantees (#1); (ii) change-event evidence and the RCAEval-C decoy benchmark (#2); (iii) intervention-based verification trials with replayable receipts (#3); (iv) a robustness protocol (#4) showing graceful degradation; ablations #5–#6 as secondary findings. All core engines run on CPU in ≤ seconds per incident (except optional TSFM/LLM arms), which itself is a selling point against CIRCA/RUN-class methods (hours per case on Train Ticket).

**1-month allocation (estimate):** week 1 — data loaders, robust scorer baseline, conformal layer (#1); week 2 — change channel + decoy generator (#2), CP-SBFL (#5); week 3 — verification trials (#3), ablation matrix runs (#4) overnight; week 4 — TSFM arm (#6) if time, narration checker (#9), writing.

### Gaps
- None of the shortlisted combinations has published RCAEval numbers; all expected gains are judgement.
- CPU timings for TSFMs and local LLMs must be measured on the team's laptops before committing.
- Licences of IDI_release, CRISP and RCAEval data were not checked.
