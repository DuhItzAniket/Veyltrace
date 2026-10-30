# Benchmarks, Evaluation Protocol and Laptop Testbed for Veyltrace v2 (state as of 30 Oct 2026)

Scope note: this file deliberately does **not** repeat RCAEval internals (layouts, ground-truth encoding, AC@k code, window sizes, quirks, baseline tables). Those are in `research_notes/Veyltrace outage diagnosis research/rcaeval_benchmark.md` (verified 22 Oct 2026, RCAEval v1.8.1). Numbers labelled "my computation" were computed in this session from the cited files (OTel demo 3.1.0 compose files, Online Boutique v0.10.7 manifest, WSL kernel config); no URL exists for the arithmetic itself, but the input file is cited. Prior notes for the v1 hackathon assumed "AI may only explain, never decide" (`_hackday-v1/AGENTS.md`); inferences below assume v2 keeps a deterministic ranker plus an LLM explanation layer.

---

## Q1. Which offline benchmarks/datasets exist beyond RCAEval (size, telemetry, systems, faults, licence, download size, ground truth, known flaws), and what is new in 2025–2026?

### Takeaway
The field moved a lot in 2025–2026. Three findings matter most:
- **Existing public benchmarks are "too easy".** A simple rule-based alert count matches or beats SOTA on Nezha, Eadro and RCAEval. The FSE'26 propagation-aware TrainTicket benchmark (1,430 cases) drops 11 SOTA methods to 0.21 mean Top@1.
- **LLM-agent benchmarks multiplied.** New since 2025: OpenRCA 2.0, Cloud-OpsBench, SREGym, ORCA-bench, AgenticOpsEval (AIOps2025 + RCA100) and ITBench-AA.
- **Only a few benchmarks are laptop-friendly and fit a deterministic multi-modal ranker:**
  - RCAEval
  - Nezha (101 cases, in-repo)
  - PetShop (metrics only, AWS)
  - AIOps2025 (400 cases, 11.9 GB Parquet)
  - the FSE'26 TrainTicket benchmark (size on Zenodo unverified)
  - Cloud-OpsBench (tool-replay snapshots of a few MiB per case, but agent-style)

### Cited Findings

**A. Offline benchmarks with raw telemetry (usable by a deterministic ranker)**

- **"Rethinking the Evaluation of Microservice RCA with a Fault Propagation-Aware Benchmark"** (Fang et al., Pinjia He's group, CUHK-SZ). FSE'26, "directly accepted", arXiv 2510.04711 (v2 23 Dec 2025). Contents:
  - **1,430 validated failure cases from 9,152 fault injections**, 25 fault types in 6 categories, with dynamic workloads.
  - Hierarchical ground truth from service down to code-level function.
  - Each case was validated to have a "discernible impact on user-facing SLIs".
  - 11 re-evaluated SOTA models average **Top@1 0.21**, best **0.37**. Execution times grow "from seconds to hours".
  - Dataset on Zenodo, DOI 10.5281/zenodo.17105974. Paper licence CC BY-NC-ND 4.0; dataset licence not stated on the abstract page.

  Sources: [arXiv 2510.04711](https://arxiv.org/abs/2510.04711); [FSE'26 listing](https://conf.researchr.org/details/fse-2026/fse-2026-research-papers/171/Rethinking-the-Evaluation-of-Microservice-RCA-with-a-Fault-Propagation-Aware-Benchmar)
  - The project page names Train Ticket (50+ services) as the "system foundation". It gives metrics, logs and traces as telemetry and mentions fault types such as DNS, TimeSkew, Network Corrupt and PodKill.
  - Its preliminary study says simple rule-based methods match or beat SOTA on public benchmarks. It names only three of the four benchmarks: **Nezha, Eadro and RCAEval**.
  - Code: AegisLab backend, `rca-algo-contrib` reproduction algorithms. [Project page](https://operationspai.github.io/revisiting-rca-evaluation/)
  - The AegisLab repo is **archived** (last push 2026-04-19) ([GitHub API, OperationsPAI/AegisLab](https://github.com/OperationsPAI/AegisLab)).
  - A later paper identifies the simple method as "SimpleRCA, a rule-based count of metric, trace and log alerts per service", which "performs comparably to or better than state-of-the-art methods on four public benchmarks, including RCAEval RE2 and RE3" ([Hussain & Farrukh 2026, Research Square, DOI 10.21203/rs.3.rs-11401166/v1](https://doi.org/10.21203/rs.3.rs-11401166/v1)).
  - A separate trajectory-level study uses this benchmark under the name "RCABench" (500 cases randomly sampled from the 1,430) ([arXiv 2608.21310](https://arxiv.org/html/2608.21310v1)).

- **AgenticOpsEval: AIOps2025 + RCA100.** "A Multi-Dataset Benchmark for Evaluating LLM Agents in Microservice Failure Diagnosis", arXiv 2606.29193, 28 Jun 2026, no venue. Source for this item: [arXiv 2606.29193 HTML](https://arxiv.org/html/2606.29193v1)

  | | AIOps2025 | RCA100 |
  |---|---|---|
  | Cases | **400** | **103** |
  | System | HipsterShop (≈13 services, 33 pods, TiDB storage tier + Redis) on self-hosted Kubernetes, 8 VMs | OpenTelemetry Demo on Alibaba Cloud ACK, with managed RDS/Redis/message bus |
  | Faults | **Chaos Mesh**: 9 categories / 18 fault types (node stress, network delay/loss/corruption, pod failure/kill, JVM, CPU/mem stress, I/O, erroneous code change, DNS, port misconfig). Levels: 195 service, 123 pod, 82 node | "Chaos Drills": 28 root-cause types in 6 groups; 13 composite cases |
  | Telemetry | Prometheus metrics, Filebeat logs, Jaeger traces | 6 modalities (metrics, logs, traces, events, alerts, topology) |
  | Size | **2,835 Parquet files, ≈269M rows, 11.9 GB**, over 18 days | 721 files, ≈116M rows, 3.4 GB |
  | Licence | not stated | CC BY-NC-SA 4.0 |

  - Labels: detectors propose evidence, 3 SREs confirm, and a senior SRE adjudicates. Each scenario was re-injected several times. The data was validated through competitions with 6,093 teams.
  - RCA100 ground truth has 4 layers: fault type, target entities, a 3–4-step causal chain, and 661 observability checkpoints. Answers ship in a separate answer-key package.
  - Download: aiops.cn GitLab `aiops-live-benchmark/agenticopseval`.
  - Scoring:
    - AIOps2025: `Final_A = 0.4·LocationAcc + 0.4·TypeAcc + 0.1·Explainability + 0.1·Efficiency`. Location uses exact string match on component; type uses keyword match with an embedding fallback.
    - RCA100: `Final_B = 0.4·Entity + 0.3·Fault + 0.3·Process`.
  - AIOps2025 localization must be at one prescribed layer (service, pod or node). That is "harder than the service-level scoring used on RCABench", and about half of the faults sit below the service tier and raise no SLO ([arXiv 2608.21310](https://arxiv.org/html/2608.21310v1)).

- **Nezha datasets** (ESEC/FSE 2023, MIT). Two systems: OnlineBoutique (`hipster`) **56 faults** and TrainTicket (`ts`) **45 faults**, 101 in total.
  - Metrics, logs and traces, plus fault-free "construct" data. Collection dates are 2022-08-22/23 and 2023-01-29/30.
  - Faults: code-level `return`/`exception` and resource-level `network_delay`, `cpu_contention`, `cpu_consumed`.
  - Ground truth: service-level `*-fault_list` files, plus inner-service JSON (`root_cause_hipster.json`, `root_cause_ts.json`) mapping each fault to a log-template span or a metric (e.g. `CpuUsageRate(%)`).
  - Hosted inside the GitHub repo (`rca_data/`, `construct_data/`). The injection tool is not stated. One README link has a date typo (2022-01-29).

  Source: [Nezha GitHub](https://github.com/IntelligentDDS/Nezha)

- **Eadro data** (ICSE'23, arXiv 2302.05092). TrainTicket and SocialNetwork (DeathStarBench), with logs, KPIs and traces. ChaosBlade injection (e.g. CPU hog): **162 injections on TT and 72 on SN**. Fault-free collection ran 7 h (TT) and 1.2 h (SN). Source: [Eadro arXiv](https://arxiv.org/pdf/2302.05092). The download location was not found in this session (see Gaps).

- **PetShop** (Amazon; CLeaR 2024, PMLR 236:957–978). Latency, request and availability **metrics** from a 41-component AWS application (databases, load balancers, queues, storage, containers), with **68 injected performance issues**. Test cases are "low", "high" and "temporal" latency, with target node PetSite. Code and data are at `amazon-science/petshop-root-cause-analysis`. Sources: [PMLR](https://proceedings.mlr.press/v236/hardt24a.html); [arXiv 2311.04806](https://arxiv.org/pdf/2311.04806). It is used as a third system next to Online Boutique and Sock Shop in 2026 work, e.g. an ICML'26 Bayesian RCD paper ([ICML 2026 poster](https://icml.cc/virtual/2026/poster/65359)).

- **LEMMA-RCA** (accepted CIKM 2026, arXiv 2406.05375v4). Four sub-datasets:

  | Sub-dataset | Domain | Faults | Entities | Telemetry | Size |
  |---|---|---|---|---|---|
  | Product Review | IT (OpenShift) | 4 fault types (OOM, high CPU, storage full, DDoS) | 216 pods on 6 nodes | Prometheus metrics, Elasticsearch logs, JMeter latency KPI | **765 GB** |
  | Cloud Computing | IT (AWS CloudWatch) | 6 fault types (cryptojacking, GitOps mistakes, configuration change failure, …) | — | CloudWatch metrics and logs | **540 GB** |
  | SWaT | OT (water treatment) | 16 | — | sensor data | 4.47 GB |
  | WADI | OT (water distribution) | 15 (Table 2 says 9) | — | sensor data | 5.67 GB |

  - Metrics are **PR@k and MRR**. Example: on Product Review, BARO reaches PR@1 0.75 and MRR 0.775 offline. PC, CIRCA and Nezha exceeded 24 h per case online.
  - Licence is inconsistent: CC BY-ND 4.0 in Appendix F vs by-nc-nd in the header.
  - Hosted at lemmarca.info, Zenodo DOI 10.5281/zenodo.20516735.

  Sources: [arXiv abs](https://arxiv.org/abs/2406.05375); [arXiv HTML v4](https://arxiv.org/html/2406.05375v4)

- **GAIA (CloudWise "Generic AIOps Atlas")**. MicroSS business simulation (QR-code login), continuously collected for two weeks (July–Aug 2021).
  - More than 6,500 metrics (Metricbeat CSV per node/indicator) and about 7M log items. OpenTracing traces with trace_id/span_id/parent_id.
  - Anomaly-injection records live in the "run" folder. Companion data adds 406 detection/forecasting series.
  - Licence is inconsistent: GPL-2.0 badge vs "Apache 2.0" in the README text. The promised Sept 2021 update is not evident.

  Source: [GAIA GitHub](https://github.com/CloudWise-OpenSource/GAIA-DataSet)

- **AnoMod** (MSR 2026 data showcase, arXiv 2601.22881, CC BY 4.0).
  - Systems and cases: SocialNetwork and TrainTicket, **24 injected cases** covering 12 anomaly types in 4 levels: performance, service, database, code.
  - Injection: Chaos Mesh for performance, service and DB faults; the ChaosBlade JVM sandbox for code faults (bytecode instrumentation).
  - Five modalities: logs, Prometheus metrics, Jaeger/SkyWalking traces, API responses, and **code coverage** (Gcov/JaCoCo).
  - Workload: EvoMaster black-box tests.
  - Hosting: Zenodo 10.5281/zenodo.18342898, scripts in the EvoTestOps/AnoMod repo.
  - Labels are folder names, with activation boundaries at workload start and end.

  Sources: [arXiv abs](https://arxiv.org/abs/2601.22881); [arXiv HTML](https://arxiv.org/html/2601.22881v1)

- **LO2** (PROMISE'25, not MSR). Light-OAuth2: 7 microservices + MySQL, exercised with Locust using correct and erroneous API calls, labelled by the error triggered.
  - About 657k log files (more than 2B log lines) and more than 45M metric files (485 unique metrics). Traces are limited.
  - Hosted on the University of Helsinki data catalogue.

  Source: [arXiv 2504.12067](https://arxiv.org/pdf/2504.12067). A 2026 multi-agent method reports 91.3% diagnostic accuracy on LO2 vs 39.8% for single-agent ReAct ([arXiv 2605.03505](https://arxiv.org/html/2605.03505v1)).

- **TrainTicketTrace** ("A Multi-Fault Distributed Dataset for Microservice Fault Detection"), SANER 2026 workshops track. Only the title was found ([SANER 2026 listing](https://conf.researchr.org/details/saner-2026/saner-2026-workshops-tutorials-track/43/TrainTicketTrace-A-Multi-Fault-Distributed-Dataset-for-Microservice-Fault-Detection-)).

**B. LLM-agent RCA benchmarks (offline, query-style)**

- **OpenRCA** (ICLR 2025, MIT).
  - Contents: **335 failures** from 3 enterprise systems — Telecom 51, Bank 136, Market 148 (Market has cloudbed-1 and cloudbed-2). The failures cover 73 unique components and 28 failure reasons.
  - **68.5 GB, more than 523M lines** of metrics, logs and traces.
  - Task: output a (time, component, reason) triple. "Perfect" requires all three to be correct.
  - Repo recommends **≥80 GB storage and 32 GB RAM**. Data is on Google Drive. Faults are recorded in **UTC+8**. Ground truth is in `record.csv`/`query.csv` per system.

  Sources: [OpenRCA GitHub](https://github.com/microsoft/OpenRCA); [ICLR paper](https://proceedings.iclr.cc/paper_files/paper/2025/file/d29b8d53678015079e1d245c023e49d2-Paper-Conference.pdf); [Kim et al., AIOps'26 workshop](https://cloudintelligenceworkshop.org/papers/aiops26-Kim.pdf)
  - Original best: RCA-agent with Claude 3.5 at 11.34% ([ICLR paper](https://proceedings.iclr.cc/paper_files/paper/2025/file/d29b8d53678015079e1d245c023e49d2-Paper-Conference.pdf)).
  - 2026 re-run, baseline agent, perfect/partial %: Gemini 2.5 Pro 12.5/22.4, GPT-5 mini 8.4/21.5, GPT-OSS-120B 6.9/12.2, Solar Pro 2 5.7/15.8, Claude Sonnet 4 3.9/14.3 ([Kim et al.](https://cloudintelligenceworkshop.org/papers/aiops26-Kim.pdf)).
  - An unverified GitHub write-up claims Claude Opus 4.6 at 117/335 (35%) with a different harness (search snippet only, not primary).
  - With mined rules on a held-out Market cloudbed, "Full Score" rose from 14.10 to 35.90 ([Gopal & Krishnan, arXiv 2607.13548](https://arxiv.org/abs/2607.13548)).

- **OpenRCA 2.0** (arXiv 2606.27154, Jun 2026, "work in progress", paper CC BY-NC-SA 4.0). **500 instances**, "the first cross-system RCA benchmark with step-wise causal annotations for LLM agents" (PAVE protocol, forward verification from known injections).
  - Across 11 frontier LLMs, the exact root-cause set is recovered in only **20.7%** of cases.
  - At least one correct service is found in 76.0%, but only 61.5% have that service grounded in a verified causal path ("ungrounded diagnosis").
  - The number of systems and the repo link are not on the abstract page.

  Source: [arXiv 2606.27154](https://arxiv.org/abs/2606.27154)

- **Cloud-OpsBench** (arXiv 2603.00468, v2 22 Aug 2026, CC BY 4.0). **754 runtime-verified cases, 57 fault types in 8 categories**:

  | Category | Cases |
  |---|---|
  | Admission Control | 58 |
  | Scheduling | 164 |
  | Startup | 86 |
  | Runtime | 141 |
  | Service Routing | 91 |
  | Performance | 76 |
  | Infrastructure | 40 |
  | Application Code Defect | 98 |

  - Systems: OnlineBoutique (11 services) and TrainTicket (41) on a 4-node Kubernetes v1.31 cluster on Huawei Cloud, with Locust load.
  - Injection: ChaosBlade for infrastructure faults, kubectl for config faults, mutated images for code faults. A Generator/Executor/Verifier agent loop rejected 46 of 800 plans.
  - Reproducibility: 12 diagnostic tools are **pre-executed and the responses stored as JSON**, then replayed through a mocked interface. Snapshots average 3.46 MiB (OB) and 8.75 MiB (TT).
  - Metrics: Joint RCA Accuracy (JRA) and Evidence Closure Rate (ECR). Best JRA is 0.76 (OB, DeepSeek-V4-Flash) and 0.68 (TT, GPT-5).
  - The abstract's "best ECR 0.38 / 0.15" matches the ECR of those best-JRA models. The table's maximum ECR is 0.46 (OB, Gemini-2.5-Pro) and 0.25 (TT, Qwen3.5-Plus), so ECR and JRA leaders differ.
  - Repo: github.com/LLM4Ops/Cloud-OpsBench.

  Sources: [arXiv abs](https://arxiv.org/abs/2603.00468); [arXiv HTML v2](https://arxiv.org/html/2603.00468v2)

- **ORCA-bench** (arXiv 2607.28545, v3 29 Sep 2026, CC BY 4.0).
  - **1,079 RCA tasks** over 6 days of metrics, logs and traces from one OpenTelemetry-instrumented microservice system under simulated load. Agents get Prometheus/Jaeger/OpenSearch (via Grafana) and source code.
  - Size: "curated 50 GB" testbed.
  - Results: best RCA accuracy is **25.3% (Medium) and 10.0% (Hard)**. Removing source-code access lowered accuracy for every model.
  - Hosted at hub.harborframework.com/datasets/orca-bench.

  Source: [arXiv 2607.28545](https://arxiv.org/abs/2607.28545)

**C. Live (interactive) agent benchmarks**

- **AIOpsLab** (Microsoft, MIT, MLSys'25).
  - Scope: four task types (detection, localization, analysis, mitigation). Clusters are local `kind` (x86 and ARM configs) or remote via Ansible/Terraform. Setup is Linux-oriented; no RAM figures are given ([AIOpsLab README](https://github.com/microsoft/AIOpsLab)).
  - The current registry has **89 active problems** ([registry.py](https://github.com/microsoft/AIOpsLab/blob/main/aiopslab/orchestrator/problems/registry.py)):
    - k8s target-port misconfig 12
    - MongoDB auth revoke and unregistered-user faults 4 + 8 + 8
    - scale-to-zero 4
    - non-existent node 4
    - pod/container kill and failure, network loss and delay (2 each)
    - **23 Astronomy Shop feature-flag faults**
    - noop 3
    - others
- **ITBench** (IBM, Apache-2.0, ICML'25 oral).
  - The open repo lists 6 SRE scenarios and 21 mechanisms.
  - **ITBench-AA** (with Artificial Analysis, 27 May 2026) starts with **59 SRE tasks, where every model scores below 50%** ([ITBench README](https://github.com/itbench-hub/ITBench)).
  - SRE scenarios deploy Prometheus, Clickhouse + OpenSearch, Jaeger and OTel k8s-event collection ([ITBench scenarios README](https://github.com/itbench-hub/ITBench/blob/main/scenarios/README.md)).
  - The old ITBench-Scenarios repo was archived on 24 Feb 2026 ([ITBench-Scenarios](https://github.com/itbench-hub/ITBench-Scenarios)).
- **SREGym** (arXiv 2605.07161, MIT, release 1.1 on 4 Oct 2026).
  - Scale: **90 problems**, 50 fault primitives across 139 services in 5 apps (DeathStarBench SocialNetwork/HotelReservation, Train Ticket, Astronomy Shop, plus two in-house apps), giving 3,623 fault-component pairs.
  - **Ambient noise**: two random 2-minute noise patterns every 5 minutes.
  - Diagnosis is judged by a 9-question checklist LLM judge (pass ≥7/9; Claude Sonnet 4.6 judge, **Cohen's κ 0.90** vs a human expert). Diagnosis success is 38.9–72.6%.
  - Noise lowers diagnosis for every agent-model pair. On SREGym-unique failures, Stratus + Sonnet 4.6 falls from 63.7% to 17.9%.
  - **SREGym-Lite (17 problems) on kind suggests 8 vCPU / 16 GB**, and "not all problems are supported" on kind.

  Sources: [SREGym paper](https://arxiv.org/html/2605.07161v1); [SREGym GitHub](https://github.com/SREGym/SREGym); [GitHub API](https://api.github.com/repos/SREGym/SREGym)

**D. Repo status (GitHub API, 30 Oct 2026)**

Source: [GitHub REST API](https://api.github.com/repos/microsoft/AIOpsLab)

| Repo | Status / last push | Latest release | Licence |
|---|---|---|---|
| microsoft/OpenRCA | pushed 2026-10-22 | — | MIT |
| microsoft/AIOpsLab | pushed 2026-10-28 | — | MIT |
| itbench-hub/ITBench | pushed 2026-10-29 | v1.4.1 (2026-01-13) | Apache-2.0 |
| SREGym/SREGym | — | 1.1 (2026-10-04) | MIT |
| EvoTestOps/AnoMod | pushed 2026-08-19 | — | MIT |

### Inferences
- **Recommended offline evaluation suite for Veyltrace v2** (deterministic multi-modal ranker):
  1. **RCAEval RE2 (OB/SS/TT) + RE3**: the comparability anchor.
  2. **The FSE'26 propagation-aware TrainTicket benchmark (1,430 cases, Zenodo 17105974)**: the "hard" set where SOTA averages 0.21 Top@1. It is also where the authors already re-ran 11 methods, so it is good for a "beyond-too-easy-benchmarks" claim. Verify the download size and format first.
  3. **Nezha (101 cases, OB + TT, in-repo, MIT)**: a cheap second-source cross-dataset test on the same two systems as RCAEval.
  4. Optional third system:
     - **PetShop** (metrics only, a different cloud architecture: AWS managed services), or
     - **AIOps2025** (400 cases, 11.9 GB, pod/node-level labels, TiDB). It is the most "industrial-looking" laptop-sized set, but its licence is unstated.
- **Skip or only mention:**
  - LEMMA-RCA IT data (765 GB + 540 GB is impossible on a laptop).
  - GAIA (single 2021 system, licence conflict).
  - AnoMod (24 cases is too few for RCA statistics; it is a modality and code-coverage dataset).
  - LO2 (API-error anomaly detection, not RCA).
  - Live agent benchmarks (AIOpsLab/ITBench/SREGym): mitigation-centric, LLM-judge scored, and need ≥16 GB just for the cluster.
- **If Veyltrace v2 adds an agentic or LLM mode**, Cloud-OpsBench is the most laptop-friendly agent benchmark (MiB-scale replay snapshots, no cluster). OpenRCA's 32 GB RAM and 80 GB disk recommendation makes it borderline on 16 GB laptops; a subset or streaming would be needed.
- A ranker that only outputs a service list cannot be scored on OpenRCA/OpenRCA 2.0/AIOps2025/RCA100 without a time and fault-type output. Plan a **(service, fault-type, onset-time)** output contract so these benchmarks become usable.

### Gaps
- The FSE'26 benchmark's Zenodo size, file format, the list of 25 fault types, the injection tool and the dataset licence were not verified (the abstract and project page omit them). The 4th "simple method wins" benchmark is unnamed.
- Eadro dataset hosting (Zenodo record) was not found. A survey (arXiv 2407.01710) lists a "TrainTicket-Eadro" dataset, but its HTML returned 404 here.
- AIOps2025 licence and exact download size per file were not confirmed. No baseline numbers for AIOps2025/RCA100 were on the fetched page.
- OpenRCA 2.0: repo/data link, systems and licence not found. ORCA-bench: names of evaluated models (other than "Claude Fable 5") not given on the abstract page.
- Original AIOps Challenge datasets (2020–2022, aiops.cn) were not researched individually.
- No 2026 "RE4" or new RCAEval suite was found (consistent with the 22 Oct notes).

---

## Q2. Evaluation methodology best practice: metrics, statistics, cross-system generalization, ablations, cost/latency, LLM pitfalls, and what reviewers expect

### Takeaway
A credible 2026 RCA paper needs:
- **Metrics:** AC@1 as the headline (with AC@3/Avg@5), **always reported per system** and never only pooled. Add a chance floor plus naive baselines: N-Sigma/BARO and a SimpleRCA-style alert count.
- **Paired, clustered statistics:** bootstrap CIs and permutation/McNemar tests with Holm correction, clustered by (system, service, fault), because RCAEval repetitions are not independent.
- **Robustness:** sensitivity to the onset time (oracle inject time is a major hidden advantage).
- **Diagnostics:** a retrieval-vs-ranking failure decomposition.
- **Process/evidence metrics** if any explanation or agent is claimed.

For LLM components, follow the 2026 *Empirical Software Engineering* LLM guidelines:
- exact model versions
- prompts and traces released
- an open-model baseline
- repeated runs with distributions
- contamination and non-determinism discussed

Release per-case outputs and an archival DOI artifact, plus Croissant + RAI metadata for NeurIPS E&D.

### Cited Findings

**Metrics in use (2025–2026)**
- AC@k/Avg@k (RCAEval; see prior notes).
- PR@k and MRR (LEMMA-RCA) ([arXiv HTML](https://arxiv.org/html/2406.05375v4)).
- "Perfect" vs "partial" (time, component, reason) triple accuracy (OpenRCA) ([Kim et al.](https://cloudintelligenceworkshop.org/papers/aiops26-Kim.pdf)).
- Joint RCA Accuracy + Evidence Closure Rate (Cloud-OpsBench) ([arXiv](https://arxiv.org/abs/2603.00468)).
- Weighted location/type/explainability/efficiency scores (AIOps2025) and entity/fault/process scores (RCA100) ([arXiv 2606.29193](https://arxiv.org/html/2606.29193v1)).
- Checklist LLM-judge pass rate (SREGym, κ 0.90 vs a human) ([SREGym](https://arxiv.org/html/2605.07161v1)). ORCA-bench re-scored its judge against humans, κw 0.91 ([arXiv 2607.28545](https://arxiv.org/abs/2607.28545)).
- **Process metrics.** Node F1 and Edge F1 over propagation graphs: "Edge F1 never exceeds 0.67 even when localization succeeds". Failed runs lose 43–67% Edge F1 but only 16–32% Node F1 ([arXiv 2608.21310](https://arxiv.org/html/2608.21310v1)). OpenRCA 2.0's grounded-path rate (61.5% vs 76.0% service hit) shows the same gap ([arXiv 2606.27154](https://arxiv.org/abs/2606.27154)).
- **Retrieval-reranking decomposition** (NeurIPS 2026, Muhammad, **Pham** et al.). Top-k hides two failures: the cause never retrieved vs. retrieved but mis-ranked. Statistical baselines mis-rank the true cause 78–100% of the time on complex-fault benchmarks ([NeurIPS 2026 poster](https://neurips.cc/virtual/2026/poster/139698)). RCAEval now exposes this as `--report-decomposition K` (prior notes).

**Reporting-protocol failures documented in 2026**
- **Pooled leaderboards hide system-specific winners** (Hu, Liu & Fu, arXiv 2606.29159; audit of OpenRCA, RCAEval and PetShop; 11 subsystems; 16 released implementations) ([arXiv 2606.29159](https://arxiv.org/abs/2606.29159)):
  - Leave-one-system-out selection picks the worse method on up to 5 of 11 held-out subsystems, with regret up to **24.8 pp on RCAEval/Sock Shop** ([PDF snippet](https://arxiv.org/pdf/2606.29159)).
  - Of 8 leads whose margin is below the cross-subsystem spread, 6 reverse. About a third of comparisons change sign on a second data release.
  - **None of 23 RCA papers released per-case outputs.**
  - Changing only which input table the runner reads reverses a published comparison.
- **Onset/inject-time sensitivity** (Hussain & Farrukh, pre-registered study on RCAEval RE2/RE3, posted 19 Oct 2026) ([DOI 10.21203/rs.3.rs-11401166/v1](https://doi.org/10.21203/rs.3.rs-11401166/v1)):
  - Shifting the onset 2 min late drops **N-Sigma from 0.80 to 0.07 AC@1** and a SimpleRCA-style heuristic from 0.81 to 0.23 on RE2.
  - Their LLM pipeline went from 0.87 to 0.27.
- **Where LLM accuracy comes from** (same study):
  - The LLM agent (AC@1 0.44 on RE2) trailed its own detector count (0.60) and N-Sigma (0.80).
  - Crossing evidence and prompts showed the **evidence shown accounts for +0.30 and the prompt for +0.05**.
  - **One false "NOTE" sentence made models name a decoy first in 21–42% of flagged RE2 cases** (about 4% without it; 62% for gpt-oss-120b in a generic pipeline).
  - Recommendation: compare the model to a label-free ranking of its own input, and stress-test the text with decoys, ablations and onset shifts.

**Statistical design actually used by a 2026 pre-registered RCAEval study** ([DOI 10.21203/rs.3.rs-11401166/v1](https://doi.org/10.21203/rs.3.rs-11401166/v1))
- Confirmatory statistic: the **paired difference in AC@1** on the same cases.
- Inference is clustered by (system, root service, fault): 90 clusters on RE2, about 30 on RE3, "because the three repetitions … are not independent". It uses:
  - a 95% **cluster-bootstrap CI** (2,000 resamples);
  - a two-sided **cluster sign-flip permutation test** (10,000 permutations), seeded;
  - exact **McNemar** as an unclustered secondary analysis;
  - **Holm** correction within families.
- **Power:** assuming 30% discordant cases, the smallest detectable difference at p<0.05 is about **7 points on 270 cases**, 10 points after Holm over 13 comparisons, and **14 points on 90 cases**. "Smaller differences are reported as not detected, not as absent."
- Pre-registration was done via a tagged commit before any fault window was seen, with GitHub server logs as the timeline proof.

**LLM-specific evaluation pitfalls**
- **2026 guidelines** for empirical SE studies involving LLMs (Baltes, Wagner et al.; accepted at *Empirical Software Engineering*; site v2026.09). Each guideline below is MUST or SHOULD ([llm-guidelines.org summary](https://llm-guidelines.org/summary/); [guidelines](https://llm-guidelines.org/guidelines/)):
  - report the exact model version, date, configuration and defaults
  - describe the architecture, prompts and tools
  - share interaction logs and traces
  - justify benchmarks and metrics, and "do not claim more than the evaluation verified"
  - **include a naive baseline** and isolate confounders
  - **repeat experiments and report the distribution**
  - **include an open LLM as a baseline**
  - validate LLM judges against humans (inter-rater reliability)
  - discuss **data leakage (contamination)** and **non-determinism**
- **Reproducibility.** A study of 640 LLM4SE papers (2017–2025) found that badges "do not consistently guarantee execution fidelity". It proposes a Reproducibility Maturity Model ([arXiv 2512.00651](https://arxiv.org/abs/2512.00651)).
- **Run-to-run variance in practice:**
  - Trajectory study: validation runs ×5, reported as mean ± SD (baseline Acc@1 43.5 ± 0.6; DiagGuard 52.5 ± 1.1) plus pass@k. Characterization runs were single-run and labelled "indicative" ([arXiv 2608.21310](https://arxiv.org/html/2608.21310v1)).
- **Cost and latency must be reported:**
  - OpenRCA full re-run: 5 models × 335 = **1,675 runs, 609.9 h wall clock, ≈1.38 B tokens, ≈$1,394** ([Kim et al.](https://cloudintelligenceworkshop.org/papers/aiops26-Kim.pdf)).
  - Per-case agent cost ranges from about $0.04 (mABC, 163k tokens) to about $4.64 (ThinkDepth.ai + Sonnet, about 1.47M tokens) ([arXiv 2608.21310](https://arxiv.org/html/2608.21310v1)).
  - FSE'26 benchmark: method runtimes span "seconds to hours" ([arXiv 2510.04711](https://arxiv.org/abs/2510.04711)).
- **Memorisation / contamination probes.** Anonymising or permuting service names, with a strict leak detector, did **not** lower accuracy on RE2 but cost 0.20–0.21 on RE3 ([DOI 10.21203/rs.3.rs-11401166/v1](https://doi.org/10.21203/rs.3.rs-11401166/v1)). Sleuth-style log lines leaked original Sock Shop names in 86 of 90 prompts until a stricter scrub was used (same source).
- **Agent pitfalls are framework-level.** Kim et al. classify 12 pitfall types; "hallucinated data interpretation and incomplete exploration" persist across all models, and prompt engineering alone does not fix them ([Kim et al.](https://cloudintelligenceworkshop.org/papers/aiops26-Kim.pdf)).

**What venues and reviewers expect**
- **NeurIPS 2026 "Evaluations and Datasets" track** (renamed from D&B):
  - **Croissant metadata with mandatory Responsible-AI fields**. Submissions missing RAI metadata are flagged in review ([NeurIPS blog, 4 May 2026](https://blog.neurips.cc/2026/05/04/responsible-ai-metadata-requirements-for-the-evaluations-and-datasets-track-neurips-2026/)).
  - Hosting is on one of Harvard Dataverse, Kaggle, Hugging Face or OpenML ([NeurIPS 2026 hosting page](https://neurips.cc/Conferences/2026/EvaluationsDatasetsHosting), via search snippet).
  - In 2025, the most common metadata failures were missing licence (11.9%), description (4.9%) and URL (3.5%) ([NeurIPS blog Dec 2025](https://blog.neurips.cc/2025/12/05/neurips-datasets-benchmarks-track-from-art-to-science-in-ai-evaluations/)).
- **ACM SE venues (FSE-style artifact tracks)** offer Available / Functional / Reusable badges ([FSE 2025 call for artifacts](https://conf.researchr.org/track/fse-2025/fse-2025-artifacts), via search snippet):
  - "Available" needs a DOI or a persistent repository.
  - "Functional" means reviewers exercised the artifact.
  - "Reusable" is a higher bar for repurposing.
  - The ACM badging policy page returned HTTP 403 in this session.
- **Benchmark-paper reviewers in 2026 cite these weaknesses:** oversimplified benchmarks (FSE'26), pooled leaderboards (Hu et al.), outcome-only metrics (Cloud-OpsBench, OpenRCA 2.0, trajectory study), single-failure clean environments without noise (SREGym), and brittle exact-label matching (SREGym) ([SREGym](https://arxiv.org/html/2605.07161v1); [arXiv 2510.04711](https://arxiv.org/abs/2510.04711); [arXiv 2603.00468](https://arxiv.org/abs/2603.00468)).

### Inferences
- **Protocol for Veyltrace v2:**
  - **Primary metric:** service-level AC@1 per (benchmark, system). Secondary: AC@3, Avg@5, MRR. Fine-grained: fault-type accuracy (RCAEval indicator; AIOps2025-style type). Add an onset-time error (|predicted onset − inject|) if v2 detects its own onset.
  - **Always report:** the chance floor, N-Sigma, BARO, a SimpleRCA-style alert count, and 2–3 published methods re-run in *your* pipeline. Use one runner and one input table, and state the denominator and the handling of failed outputs (Hu et al.).
  - **Statistics:** paired cluster bootstrap CI + cluster permutation test vs each baseline, Holm-corrected. Pre-state the minimum detectable difference: ≈7 pp on 270 cases, ≈14 pp on 90.
  - **Generalisation:**
    - leave-one-system-out for any tuned weight
    - tune on RE2-OB/SS and test on RE2-TT, the FSE'26 benchmark and Nezha
    - report per-system winners, not just pooled scores
  - **Robustness:**
    - onset shift ±60/±120 s
    - detected onset vs oracle inject time
    - modality ablation (metrics only, +logs, +traces)
    - missing-modality cases (Sock Shop has no traces)
    - service-name anonymisation
  - **Diagnostics:** retrieval@K vs rerank@1 decomposition; a failure taxonomy over the misses.
  - **Cost:** wall-clock per case (p50/p95), peak RSS, and CPU-only hardware spec. With no LLM in the decision path, the cost table is a strong selling point vs agents ($0.04–$4.64 and minutes to hours per case).
- **LLM explanation layer** (if v2 keeps "AI explains only"):
  - Evaluate faithfulness separately: claim-level support rate against evidence atoms, decoy/false-NOTE robustness, and a human-validated judge with κ reported.
  - Run ×3–5 runs per case and report variance and token cost.
  - Include an open-weight model baseline, per the LLM guidelines.
  - Because the ranker is deterministic, contamination affects only the narration evaluation. Still run the service-name anonymisation probe and report it.
- **Venue fit:**
  - FSE/ICSE/ASE favour the "too-easy benchmarks + new hard labelled dataset + deterministic method + artifact badges" story.
  - ISSRE fits a dependability angle (fault injection + RCA).
  - NeurIPS E&D needs the dataset to be the main contribution, with Croissant RAI metadata on HF/Kaggle/Dataverse/OpenML.

### Gaps
- No primary source found for current ICSE 2027 / FSE 2027 / ASE 2026 reviewer guidelines specific to benchmark papers. Expectations above are inferred from 2026 critiques and artifact-track calls.
- No study was found that directly measures training-data contamination of RCAEval/OpenRCA in frontier LLMs; only indirect name-anonymisation probes exist.
- No authoritative source on "Exam score" / PR@k conventions for multi-root-cause cases beyond the LEMMA-RCA and RCAEval definitions.
- The full text of the NeurIPS 2026 decomposition paper (exact numbers per benchmark) was not retrieved; only the abstract.

---

## Q3. Live testbed on a 16 GB Windows laptop: which demo systems fit, which fault-injection tools work locally, and how do RCAEval/AIOpsLab-style faults reproduce

### Takeaway
On a 16 GB Windows laptop (Docker Desktop on WSL2), two demo systems fit with telemetry:
- **Online Boutique on kind/k3d**: requests ≈1.6 CPU / 1.3 GiB.
- **OpenTelemetry Demo 3.1.0 via Docker Compose** (minimal mode ≈3 GB; full app 6 GB plus about 2.7 GB of observability limits).

**Train Ticket does not fit** (≥24 GB RAM per its own guide). SREGym-Lite wants 8 vCPU / 16 GB for the cluster alone. Sock Shop is archived.

Fault injection by tool:
- **Chaos Mesh 2.8.7 via Helm on kind** (set `chaosDaemon.runtime=containerd`) reproduces AIOpsLab's and AIOps2025's faults.
- **stress-ng + `tc netem` inside containers** reproduces RCAEval's faults.
- **OTel demo flagd flags** give 18+ app-level faults with zero tooling.
- The WSL kernel ships `sch_netem` as a loadable module, so netem-based network faults are feasible but must be verified on the actual laptops.

### Cited Findings

**Resource footprints of demo systems**
- **OpenTelemetry Demo (Astronomy Shop):**
  - Latest release **3.1.0 (2026-09-18)** ([GitHub releases API](https://github.com/open-telemetry/opentelemetry-demo/releases)).
  - Docker requirements: Docker Compose v2.0.0+, **6 GB RAM for the application, 14 GB disk**.
  - `make start-minimal` drops Kafka, accounting and fraud-detection and "reduces memory use to about 3 GB". There are also `*-no-o11y` variants.
  - UIs on :8080: `/jaeger/ui/`, `/grafana/`, `/loadgen/`, `/feature`.

    Source: [OTel demo Docker deployment](https://opentelemetry.io/docs/demo/docker-deployment/)
  - Kubernetes: K8s 1.24+, **6 GB free RAM**, Helm 3.14+, chart ≥0.11.0. Upgrades are not supported ([OTel demo Kubernetes deployment](https://opentelemetry.io/docs/demo/kubernetes-deployment/)).
  - **Per-container memory limits at tag 3.1.0** (my computation from the compose files; source [compose.yaml @3.1.0](https://github.com/open-telemetry/opentelemetry-demo/blob/3.1.0/compose.yaml); [Makefile @3.1.0](https://github.com/open-telemetry/opentelemetry-demo/blob/3.1.0/Makefile)):

    | Compose file | Services | Sum of limits | Main items |
    |---|---|---|---|
    | `compose.yaml` (core) | 20 | **4,155 MB** | load-generator 1,500M, recommendation 500M, otel-collector 400M, ad 300M, frontend 250M, flagd-ui 200M; most Go services 20M |
    | `compose.full.yaml` adds | 3 | **1,080 MB** | kafka 620M, fraud-detection 300M, accounting 160M |
    | `compose.observability.yaml` | 5 | **2,664 MB** | jaeger 1,200M, opensearch 1G, prometheus 200M, grafana 175M, opamp-server 65M |
    | `compose.agent.yaml` (new AI-agent services) | 3 | 1,500 MB | — |

    - `make start-minimal` = core + observability + extras.
  - The 3.1.0 load generator is **Locust with browser traffic enabled** (`LOCUST_BROWSER_TRAFFIC_ENABLED=true`) ([compose.yaml @3.1.0](https://github.com/open-telemetry/opentelemetry-demo/blob/3.1.0/compose.yaml)). The live feature-flag docs say k6 restarts when `loadGeneratorVUs` changes, which suggests the docs track a newer load generator than 3.1.0 ([feature flags doc](https://opentelemetry.io/docs/demo/feature-flags/)). This is a version discrepancy.
- **Online Boutique** (latest **v0.10.7, 2026-09-18**, Apache-2.0, actively maintained) ([GitHub API](https://api.github.com/repos/GoogleCloudPlatform/microservices-demo)):
  - minikube: ≥4 CPUs, 4.0 GiB, 32 GB disk
  - Docker Desktop Kubernetes: ≥3 CPUs, 6.0 GiB, 32 GB disk
  - kind: `kind create cluster`, with no figures given

    Source: [OB development guide](https://github.com/GoogleCloudPlatform/microservices-demo/blob/main/docs/development-guide.md)
  - My computation from the v0.10.7 release manifest ([kubernetes-manifests.yaml @v0.10.7](https://github.com/GoogleCloudPlatform/microservices-demo/blob/v0.10.7/release/kubernetes-manifests.yaml)):
    - 12 Deployments (10 services + loadgenerator + redis-cart)
    - total requests **1.57 CPU / 1,368 MiB**, limits **2.7 CPU / 2,286 MiB**
    - loadgenerator defaults `USERS=10`, `RATE=1`
- **Sock Shop**: `microservices-demo/microservices-demo` is **archived** (last push 2023-12-05) ([GitHub API](https://api.github.com/repos/microservices-demo/microservices-demo)). The RCAEval author could not get its tracing to work (prior notes, issue #70).
- **Train Ticket** (41 microservices; latest release v1.0.0 from 2022-08-09; last push 2025-11-21) ([repo](https://github.com/FudanSELab/train-ticket); [GitHub API](https://api.github.com/repos/FudanSELab/train-ticket)):
  - Docker Compose needs "**at least 24G memory 50G disk** in Linux".
  - Kubernetes needs roughly **4 Linux servers**.

    Source: [Train Ticket installation wiki](https://github.com/FudanSELab/train-ticket/wiki/Installation-Guide)
- **DeathStarBench SocialNetwork**: single-machine `docker-compose up -d`, Thrift RPCs, Jaeger on :16686, wrk2 workload (do not build on ARM). No resource figures are given. Last push was 2024-07-09 ([DSB socialNetwork](https://github.com/delimitrou/DeathStarBench/tree/master/socialNetwork); [GitHub API](https://api.github.com/repos/delimitrou/DeathStarBench)).
- **SREGym-Lite on kind**: "8 vCPU and 16 GB of memory" suggested. Full SREGym needs SSH/root to nodes; managed Kubernetes won't work ([SREGym GitHub](https://github.com/SREGym/SREGym)).

**Kubernetes-in-Docker and Windows plumbing**
- **WSL2 defaults** ([MS Learn, updated 2026-10-16](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)):
  - VM `memory` = **50% of Windows RAM** (8 GB on a 16 GB laptop)
  - `swap` = 25% of RAM
  - `processors` = all logical CPUs
  - `[experimental] autoMemoryReclaim` default `dropCache`
  - `loadKernelModules` loads extra kernel modules at boot
- **K3s minimums** ([K3s requirements](https://docs.k3s.io/installation/requirements)): server 2 cores / 2 GB RAM; agent 1 core / 512 MB.
- **netem on WSL2**:
  - A 2020 Microsoft Q&A thread reported "Module sch_netem not found" on WSL kernel 4.19 ([MS Q&A](https://learn.microsoft.com/en-us/answers/questions/48142/wsl2-qdisc-netem-support)).
  - Current WSL kernel configs build it as a module: **`CONFIG_NET_SCH_NETEM=m`**, plus HTB/INGRESS/IFB/U32 =m, in `linux-msft-wsl-6.6.y` and in the latest release **`linux-msft-wsl-6.18.58.1` (2026-10-27)** ([WSL2-Linux-Kernel config-wsl](https://github.com/microsoft/WSL2-Linux-Kernel/blob/linux-msft-wsl-6.18.58.1/arch/x86/configs/config-wsl); [releases](https://github.com/microsoft/WSL2-Linux-Kernel/releases)).

**Fault-injection tools usable locally**
- **Chaos Mesh**:
  - Latest **v2.8.7 (2026-10-28)**, Apache-2.0 ([GitHub API](https://api.github.com/repos/chaos-mesh/chaos-mesh)).
  - Supports **kind, minikube, K3s, MicroK8s**. The `install.sh` script is deprecated since 2.8.2/2.9, and **Helm is recommended** ([Chaos Mesh quick start](https://chaos-mesh.org/docs/quick-start/)).
  - Chaos types: PodChaos, NetworkChaos (latency/loss/reorder/partition), DNSChaos, HTTPChaos, StressChaos (CPU/mem), IOChaos, TimeChaos, KernelChaos, JVMChaos, AWS/GCP chaos ([Chaos Mesh basic features](https://chaos-mesh.org/docs/basic-features/)).
  - Helm values default to `chaosDaemon.runtime: docker`, `/var/run/docker.sock`. Commented alternatives are containerd `/run/containerd/containerd.sock` and crio. No resources are set by default ([values.yaml @v2.8.7](https://github.com/chaos-mesh/chaos-mesh/blob/v2.8.7/helm/chaos-mesh/values.yaml)).
- **How AIOpsLab injects faults** ([inject_symp.py](https://github.com/microsoft/AIOpsLab/blob/main/aiopslab/generators/fault/inject_symp.py)):
  - Helm-installs **Chaos Mesh chart 2.6.2**, auto-detecting the runtime (containerd → `chaosDaemon.runtime=containerd`, socket `/run/containerd/containerd.sock`).
  - Writes CRDs to `/tmp/<name>.yaml` and runs `kubectl apply`/`delete`, selecting targets by the `io.kompose.service` label.
  - Faults:
    - PodChaos pod-failure, default **200 s**
    - container-kill
    - NetworkChaos **loss 99%**, correlation 100%
    - NetworkChaos **delay 10 s**, jitter 0
    - KernelChaos, marked untested
  - Other families use kubectl misconfigurations (target port, scale to zero, non-existent node), MongoDB auth revocation, and OTel-demo flags ([registry.py](https://github.com/microsoft/AIOpsLab/blob/main/aiopslab/orchestrator/problems/registry.py)).
- **How other 2026 benchmarks inject faults:**
  - SREGym: pod/process kill, stress-ng, **eBPF syscall failures**, **dm-dust** disk-sector corruption, config/deploy/K8s changes, buggy code and operators, load surges, network latency/drops. Each injector has a Python API, and the authors deliberately avoid "symptom" chaos tools ([SREGym](https://arxiv.org/html/2605.07161v1)).
  - Cloud-OpsBench: ChaosBlade + kubectl + mutated images ([arXiv HTML](https://arxiv.org/html/2603.00468v2)).
  - AIOps2025: Chaos Mesh ([arXiv 2606.29193](https://arxiv.org/html/2606.29193v1)).
  - AnoMod: Chaos Mesh + ChaosBlade JVM ([arXiv HTML](https://arxiv.org/html/2601.22881v1)).
  - RCAEval: stress-ng and `tc` inside the target container, 12-min faults, Locust `--users 10` (prior notes; parameters unpublished, issue #67).
- **OTel demo built-in failure flags** (flagd; toggle at `http://localhost:8080/feature` in a Basic or Advanced JSON view) ([OTel demo feature flags](https://opentelemetry.io/docs/demo/feature-flags/)):

  | Flag | Effect |
  |---|---|
  | `adFailure` | ~1/10 `GetAds` calls error |
  | `adHighCpu` | high CPU load in Ad |
  | `adManualGc` | full manual GCs in Ad |
  | `cartFailure` | % of `EmptyCart` calls go to a failing store |
  | `emailMemoryLeak` | memory leak in Email, variant sets size |
  | `failedReadinessProbe` | Cart readiness probe fails (Kubernetes only) |
  | `imageSlowLoad` | Envoy fault delay on product images |
  | `intlShippingSlowdown` | non-US shipping requests delayed |
  | `kafkaConsumerDead` | fraud-detection leaves the consumer group, so lag builds |
  | `kafkaQueueProblems` | per-record consumer delay |
  | `paymentFailure` | % of `charge` calls error |
  | `paymentUnreachable` | bad Payment address set in Checkout |
  | `productCatalogFailure` | errors for one product ID |
  | `productCatalogLockContention` | exclusive DB table lock |
  | `recommendationCacheFailure` | exponentially growing cache (memory leak) |
  | `aiRunawayAgent`, `aiSlowResponse` | new agent-service faults |
  | `loadGeneratorTraffic`, `loadGeneratorVUs` | load on/off, concurrency |

- **Container-level tools without Kubernetes:**
  - **Pumba 1.4.0** (2026-10-29, Apache-2.0) ([Pumba README](https://github.com/alexei-led/pumba); [GitHub API](https://api.github.com/repos/alexei-led/pumba)):
    - kill/stop/pause containers
    - **netem delay/loss/duplicate/corrupt/rate** (needs `tc` in the image, or a `--tc-image` sidecar)
    - iptables loss
    - **stress-ng** CPU/memory/IO in the target cgroup
    - supports containerd
    - **README states Windows is not supported, even with Docker Desktop's WSL2 backend**
  - **Toxiproxy v2.13.0** (2026-10-14, MIT): a TCP proxy for latency, timeout and bandwidth toxics ([GitHub API](https://api.github.com/repos/Shopify/toxiproxy)).
  - **LitmusChaos 3.33.0** (2026-10-15, Apache-2.0) ([GitHub API](https://api.github.com/repos/litmuschaos/litmus)).

### Inferences
- **Memory budget on a 16 GB Windows laptop** (estimates; Windows plus Docker Desktop overhead is unsourced):
  - Raise the WSL2 VM to about **11–12 GB** in `.wslconfig`. The default 8 GB is too tight once telemetry is on.
  - Use `swap=4GB`, `autoMemoryReclaim=gradual`, and `loadKernelModules=sch_netem` (verify the module loads with `modprobe sch_netem; tc qdisc add … netem`).
- **Option A, recommended demo: OpenTelemetry Demo 3.1.0 on Docker Compose** ("minimal" + observability).
  - About 3 GB of app use; worst case about 6.8 GB of limits (core 4.16 GB + observability 2.66 GB), dominated by the Locust browser load generator (1.5 GB), Jaeger (1.2 GB) and OpenSearch (1 GB).
  - Cut the load generator to HTTP-only users and drop OpenSearch if Veyltrace pulls logs elsewhere. Pin the 3.1.0 tag.
  - Upside: 15+ built-in, semantically meaningful app faults plus resource faults via `docker exec … stress-ng` / `tc netem` with `cap_add: NET_ADMIN`. No Kubernetes is needed, which is the most reliable choice on Windows.
- **Option B, recommended for RCAEval-comparable data: Online Boutique on a single-node kind (or k3d) cluster plus Chaos Mesh (Helm, containerd runtime) plus Prometheus/cAdvisor plus Jaeger.**
  - App requests are only about 1.3 GiB, leaving room for the kind node (about 1–2 GB, inferred from the K3s 2 GB server minimum) and telemetry.
  - The same system as RCAEval-OB and Nezha-OB enables same-system transfer experiments.
  - Istio (which RCAEval used for latency metrics) adds sidecars. Prefer OTel instrumentation or Envoy-free latency from traces (inference).
- **Do not plan on Train Ticket or full SREGym/AIOpsLab locally.** Train Ticket alone needs ≥24 GB. Use their offline data instead.
- **Faithfully reproducing RCAEval's faults locally** is possible but the exact parameters are unpublished:
  - CPU: `stress-ng --cpu N --timeout 12m`
  - memory: `stress-ng --vm`
  - disk: `stress-ng --hdd`/`--iomix`
  - socket: `stress-ng --sock`
  - `tc qdisc add dev eth0 root netem delay Xms` and `… loss Y%`
  - Run each inside the target container for 12 min after 12 min of normal load (protocol from prior notes).
  - Use Chaos Mesh StressChaos/NetworkChaos as the Kubernetes equivalent.
  - Document your own parameters; this alone is a contribution, given RCAEval issue #67.
- **Label-leak risk with flagd.** OTel demo services evaluate flags through OpenFeature/flagd, and flagd is itself an instrumented service. Flag keys and variants may appear in spans or logs. Scrub `feature_flag.*` attributes and flagd telemetry from engine inputs, mirroring Veyltrace's v1 no-leakage rule. This is an inference to verify on real telemetry.

### Gaps
- Not verified on the team's laptops:
  - whether Docker Desktop's WSL2 distro actually loads `sch_netem`
  - whether Chaos Mesh NetworkChaos/StressChaos work inside kind nested in Docker Desktop on Windows
- No measured idle or steady RSS for OB-on-kind or OTel demo on Windows. Compose limits are ceilings, not usage. Measure with `docker stats` / `kubectl top`.
- DeathStarBench SocialNetwork and Sock Shop memory requirements were not found in primary sources.
- LitmusChaos ChaosCenter resource requirements were not retrieved. Chaos Mesh's chart sets no default resources, so its footprint is unmeasured.
- Pumba's "Windows not supported" note may refer to the Windows binary. Running Pumba as a Linux container against the Docker socket was not verified.

---

## Q4. Load generation and telemetry pipeline on a laptop (Locust, k6, OTel Collector, Prometheus, Jaeger/Tempo, Loki) with memory footprints

### Takeaway
Use the load generator that ships with the system (Locust in OB and the OTel demo). Cap it to HTTP-only users, because browser traffic is what makes the OTel demo's Locust container 1.5 GB.

For the telemetry backend, the OTel demo's own limits are the best published laptop numbers:

| Component | Memory limit |
|---|---|
| OTel Collector | 400 MB |
| Prometheus | 200 MB |
| Grafana | 175 MB |
| Jaeger | 1.2 GB |
| OpenSearch | 1 GB |

`grafana/otel-lgtm` (v0.38.1) is a one-container OTel Collector + Prometheus + Loki + Tempo + Grafana (+ Pyroscope) backend built for laptops, but it publishes no RAM figure.

### Cited Findings
- **Locust 2.47.0** (2026-10-21, MIT) and **k6 v2.3.0** (2026-09-21, **AGPL-3.0**) are the current releases ([GitHub API Locust](https://api.github.com/repos/locustio/locust); [GitHub API k6](https://api.github.com/repos/grafana/k6)).
- k6 sizing ([k6 large tests guide](https://grafana.com/docs/k6/latest/testing-guides/running-large-tests/)):
  - "Simple tests use ~1-5MB per VU" (about 1–5 GB per 1,000 VUs); tests with file uploads or large JS modules use "tens of megabytes per VU".
  - Keep at least 20% CPU idle, because CPU saturation inflates response times.
  - One instance handles 30–40k VUs.
- **Load levels used by benchmarks:**
  - RCAEval TT: Locust `--users 10`; the paper describes random load of 10–200 RPS (prior notes).
  - OB loadgenerator defaults: `USERS=10`, `RATE=1` ([OB manifest @v0.10.7](https://github.com/GoogleCloudPlatform/microservices-demo/blob/v0.10.7/release/kubernetes-manifests.yaml)).
  - OTel demo 3.1.0: Locust with browser users ([compose.yaml @3.1.0](https://github.com/open-telemetry/opentelemetry-demo/blob/3.1.0/compose.yaml)).
  - Cloud-OpsBench: Locust ([arXiv HTML](https://arxiv.org/html/2603.00468v2)).
  - LO2: Locust ([arXiv 2504.12067](https://arxiv.org/pdf/2504.12067)).
  - AnoMod: EvoMaster ([arXiv HTML](https://arxiv.org/html/2601.22881v1)).
  - FSE'26 benchmark: state-machine workflows ([project page](https://operationspai.github.io/revisiting-rca-evaluation/)).
- **OTel demo 3.1.0 telemetry container memory limits:** otel-collector 400M, jaeger 1,200M, prometheus 200M, grafana 175M, opensearch 1G, opamp-server 65M (my computation; [compose.yaml](https://github.com/open-telemetry/opentelemetry-demo/blob/3.1.0/compose.yaml), [compose.observability.yaml](https://github.com/open-telemetry/opentelemetry-demo/blob/3.1.0/compose.observability.yaml)).
- **Jaeger v2.22.0** is current (2026-10-06) ([GitHub API](https://api.github.com/repos/jaegertracing/jaeger)).
- **grafana/otel-lgtm** bundles the OTel Collector, Prometheus, Tempo, Loki, Grafana and Pyroscope. It is "intended for development, demo, and testing environments" and runs "on your laptop with a single command" ([Grafana docs](https://grafana.com/docs/opentelemetry/docker-lgtm/); [launch blog](https://grafana.com/blog/2024/03/13/an-opentelemetry-backend-in-a-docker-image-introducing-grafana-otel-lgtm/)). The latest tag is v0.38.1 (2026-10-26) ([GitHub API](https://api.github.com/repos/grafana/docker-otel-lgtm)). No published memory figure was found.
- **SREGym's lightweight profile:** the `svelte` profile removes OpenSearch, Grafana, Jaeger, Alertmanager, Pushgateway and OpenEBS NDM, and cuts Prometheus retention to 2 h ([SREGym GitHub](https://github.com/SREGym/SREGym)).
- **Pipeline choices and their consequences** (from the prior engineering notes, not repeated here):
  - RCAEval metrics are Prometheus 15 s scrapes queried at `step=1`.
  - Tempo search is non-deterministic, so snapshot every pull to Parquet with a sha256.

### Inferences
- **Laptop pipeline for Veyltrace v2 data capture:**
  - apps emit OTLP → **one OTel Collector** (≈400 MB budget) → fan out:
    - metrics to Prometheus (≈200 MB, scrape 5–15 s, retention 6–24 h)
    - traces to Jaeger (memory or Badger store, ≈1.2 GB cap)
    - logs to a **file exporter** (JSONL/Parquet) instead of OpenSearch/Loki
  - Then a deterministic exporter per case: Prometheus `query_range`, the Jaeger API, and log files → Parquet plus `cases.parquet`. This mirrors RCAEval's layout (prior notes) and Veyltrace's snapshot-and-hash connector rule.
- **Estimated total:**
  - telemetry ≈2–2.5 GB without OpenSearch, Loki or Grafana
  - app 1.3–3 GB
  - k8s node 1–2 GB
  - so roughly 5–7.5 GB inside WSL2. This leaves headroom on 16 GB if WSL2 is set to 11–12 GB.
- **Load generator choice.** Locust keeps comparability with RCAEval, OB and Cloud-OpsBench. If k6 is adopted, note its AGPL-3.0 licence for anything redistributed (using it as a tool is generally fine; legal judgement not sourced). Keep load at 10–50 users; on a laptop, CPU saturation by the load generator itself is the main confounder (k6 guide: keep ≥20% idle).
- **Record laptop CPU/RAM utilisation per case** as metadata. Host contention is a realistic but uncontrolled noise source that reviewers will ask about.

### Gaps
- No primary memory figures were found for Loki, Tempo or the otel-lgtm container on a laptop. Prometheus memory per active series was not retrieved.
- No head-to-head Locust vs k6 laptop memory comparison was found (the k6 doc gives no figures for other tools).

---

## Q5. How can a 3-person team produce a new, credible, labelled dataset as a paper contribution (fault catalog, case count, ground truth, release format)?

### Takeaway
A credible small dataset in 2026 should fix what reviewers now criticise in RCAEval-style data:
- **Validate impact.** Keep only cases with measurable user-facing SLI impact; the FSE'26 benchmark kept 1,430 of 9,152 injections.
- **Publish exact injection parameters and the injector code** (the answer to RCAEval's unanswered issue #67).
- **Make repetitions independent.** Restart between cases, check that the baseline has recovered, and record deployment IDs.
- **Include noise, no-fault control cases and multi-fault cases** (SREGym, AIOpsLab noop).
- **Label more than the service:** fault type, onset/offset in ns, injection parameters, and, if feasible, a verified propagation path (OpenRCA 2.0, RCA100).
- **Release per-case results** (Hu et al.) in Parquet + a `cases.parquet` index on HF/Zenodo with a DOI and Croissant-RAI metadata.

At about 25 min per case, three laptops running unattended make about 170 injection attempts per day. Validated yield depends on the acceptance rate, which is unknown for laptops. About 150–300 validated cases is realistic within a week of background runs, and supports system-level statistics only if the fault × service grid is balanced.

### Cited Findings
- **Validation and filtering precedents:**
  - FSE'26 benchmark: 9,152 injections → 1,430 validated cases with "discernible impact on user-facing SLIs" ([arXiv 2510.04711](https://arxiv.org/abs/2510.04711)).
  - Cloud-OpsBench: Generator/Executor/Verifier loop, 46 of 800 plans rejected ([arXiv HTML](https://arxiv.org/html/2603.00468v2)).
  - AIOps2025: each scenario "re-injected several times before admission"; three SREs confirm labels and a senior SRE adjudicates ([arXiv 2606.29193](https://arxiv.org/html/2606.29193v1)).
- **Known flaws to avoid**, from RCAEval's own issues (prior notes):
  - non-independent repetitions (shared deployments and DB state, 4 resource-limit configs across 27 deployments)
  - the next case starting about 1.5 min after the previous fault with no baseline check
  - unpublished `tc`/`stress-ng` parameters
  - label noise (`f6` relabelled `f3`)
  - missing logs and traces
  - pods not restarted between cases
- **Richer ground truth precedents:**
  - RCA100: four-layer labels (fault type, target entities, 3–4-step causal chain, 661 observability checkpoints), with the answer key shipped separately ([arXiv 2606.29193](https://arxiv.org/html/2606.29193v1)).
  - OpenRCA 2.0: step-wise causal paths reconstructed from the known injection by forward verification ([arXiv 2606.27154](https://arxiv.org/abs/2606.27154)).
  - FSE'26 benchmark: service → code-function labels ([project page](https://operationspai.github.io/revisiting-rca-evaluation/)).
  - Nezha: log-template/metric indicator per fault ([Nezha GitHub](https://github.com/IntelligentDDS/Nezha)).
- **Realism additions:**
  - SREGym ambient noise: two random 2-min patterns every 5 min. Noise reduced diagnosis for every agent ([SREGym](https://arxiv.org/html/2605.07161v1)).
  - AIOpsLab includes `noop` problems (no fault) for three apps ([registry.py](https://github.com/microsoft/AIOpsLab/blob/main/aiopslab/orchestrator/problems/registry.py)).
  - RCA100 includes 13 composite cases with no single alert entity ([arXiv 2606.29193](https://arxiv.org/html/2606.29193v1)).
- **Scale of recent small datasets:** AnoMod 24 cases (MSR'26) ([arXiv HTML](https://arxiv.org/html/2601.22881v1)); Nezha 101 ([GitHub](https://github.com/IntelligentDDS/Nezha)); RCA100 103 ([arXiv 2606.29193](https://arxiv.org/html/2606.29193v1)); PetShop 68 issues ([PMLR](https://proceedings.mlr.press/v236/hardt24a.html)).
- **Release requirements:**
  - NeurIPS 2026 E&D: Croissant + RAI fields, hosted on Dataverse, Kaggle, HF or OpenML ([NeurIPS blog](https://blog.neurips.cc/2026/05/04/responsible-ai-metadata-requirements-for-the-evaluations-and-datasets-track-neurips-2026/)).
  - ACM "Available" badge: a DOI or persistent repository ([FSE 2025 artifacts](https://conf.researchr.org/track/fse-2025/fse-2025-artifacts)).
  - Hu et al.: ship per-case outputs, the input table and the denominator ([arXiv 2606.29159](https://arxiv.org/abs/2606.29159)).
- **Detection power** with about 30% discordance: ≈14 pp minimum detectable difference at 90 cases and ≈7 pp at 270 ([DOI 10.21203/rs.3.rs-11401166/v1](https://doi.org/10.21203/rs.3.rs-11401166/v1)).

### Inferences
- **Proposed "Veyltrace-Laptop" dataset (VL-RCA) design.**
  - **Systems:**
    - S1 = Online Boutique v0.10.7 on kind + Chaos Mesh. Same system as RCAEval-OB/Nezha/Cloud-OpsBench, which enables transfer tests.
    - S2 = OpenTelemetry Demo 3.1.0 on Compose. Polyglot, Kafka, built-in app faults; same system family as RCA100/ORCA-bench/ITBench/AIOpsLab.
  - **Fault catalog (≈12 types):**
    - **resource**: CPU hog, memory leak, disk I/O, socket/FD exhaustion (stress-ng / StressChaos)
    - **network**: delay, loss, corrupt (netem / NetworkChaos)
    - **pod/K8s**: pod kill/crash-loop, readiness failure, scale-to-zero, wrong target port (kubectl, AIOpsLab-style)
    - **application** (OTel flags): error-rate (payment/cart/ad/productCatalog), memory leak (email/recommendation), lock contention, Kafka consumer lag, upstream unreachable
    - **DNS / time skew** (DNSChaos/TimeChaos) as stretch goals
  - **Grid:** about 5 target services per system × about 10 applicable faults × 3 repetitions ≈ 150 per system, about 300 total.
  - **Controls:** add about 10% `noop` cases and about 10% noisy cases (a transient benign disturbance on a non-root service).
  - **Optional:** ≈20 two-fault cases.
- **Per-case protocol (scripted, seeded, deterministic order):**
  1. Fresh deploy, or rolling restart of the target namespace.
  2. Warm-up 3 min.
  3. Baseline-recovered check: SLI p95 and error rate within the pre-defined band.
  4. 10 min normal.
  5. Fault 10 min.
  6. 2 min cool-down.
  7. Export.

  That is about 25 min per case, so about 57 cases per laptop running 24 h (computed), or about 24 per 10-hour overnight run. Approximate attempt counts:
  - three laptops running 24 h: about 170 attempts per day, so about 6 days gives about 1,000 attempts, enough to filter to about 300 validated cases;
  - overnight only: about 430 attempts over 6 nights.
- **Validation rule:** keep a case only if the user-facing SLI (frontend p95 latency or error rate) deviates beyond k·MAD of the baseline within N minutes, and log rejected attempts. Report the acceptance rate as Fang et al. do.
- **Ground truth per case (`cases.parquet`):**
  - identity: `case_id` (opaque hash), system, `root_cause_service`, `root_cause_pod`, `fault_type`, `fault_family`
  - injection: `injector` (tool + version), `params` (JSON: e.g. delay_ms, loss_pct, workers, bytes, flag variant), `inject_start_ns`, `inject_end_ns`
  - context: load profile, seed, `deployment_id`, host spec, `sli_impact` (Δp95, Δerr), `validation_passed`
  - optional: `propagation_path` (services observed to deviate, ordered by onset), `noise_events`
  - The answer key lives in a separate file from the telemetry, and the case directory name stays opaque. This deliberately fixes RCAEval's folder-name leakage.
- **Release:**
  - Parquet per modality (metrics long format; OTLP-derived spans with parent IDs; logs with ns timestamps)
  - injector scripts + Helm/compose files + exact image digests
  - Croissant JSON-LD with RAI fields
  - CC BY 4.0 data / MIT code
  - Zenodo DOI + HF mirror
  - per-case outputs of all baselines
  - a datasheet including "laptop-collected" threats: host contention, Docker Desktop VM, kind single node

  Expected size (inference from RCAEval per-case HF sizes of about 1–23 MB for RE2): about 300 cases × ~10–20 MB ≈ 3–6 GB raw, or less after dropping browser-load spans.
- **Paper positioning:** "A reproducible, laptop-scale, leakage-free RCA testbed and dataset with published injection parameters, validated impact, noise and no-fault controls". It complements the FSE'26 "hard" benchmark, and the methodology section answers Hu et al. and the onset-sensitivity critique.

### Gaps
- No source quantifies how many cases reviewers consider "enough" for an RCA dataset paper. The precedents range from 24 (AnoMod, MSR data track) to 1,430 (FSE'26).
- The acceptance rate of injections on a laptop testbed is unknown. FSE'26's 15.6% (1,430/9,152) came from a full cluster with harder fault types and may not transfer.
- The leakage of OTel demo flag names into telemetry is unverified (see Q3).
- Exact NeurIPS 2026 E&D call text and FSE/ICSE 2027 artifact calls were not retrieved; requirements may tighten.
