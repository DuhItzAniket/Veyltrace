# Verified agents and local LLMs for Veyltrace v2 ("AI proposes, code decides; every verdict is replayable")

Research date: 30 Oct 2026. Scope: what is new compared with `research_notes/Veyltrace outage diagnosis research/llm_explanation_layer.md`. That note covered the "LLM only narrates" design: Bedrock and Claude prices, the evidence-ID and slot schema, FActScore and ALCE, LLM-judge bias (Zheng et al.), and the OpenRCA, ITBench and Flow-of-Action headline numbers. This note covers LLMs and ML models that **propose hypotheses and choose tools/queries**, the **deterministic verifier** that decides, **replay**, and **laptop-local models**.

Caveat: many arXiv IDs here are from 2026 (2601–2610). Numbers come from the papers' HTML versions where I could fetch them. Where only a search snippet or a secondary blog was available, the finding is marked "(secondary)".

---

## Q1. Agent architectures for RCA: what measurably works, on which benchmarks, with which model sizes?

### Takeaway
2026 evidence has shifted. On pooled benchmarks, **simple, free-form harnesses** (a ReAct loop over SQL or DuckDB, or a coding agent) **beat hand-crafted SOP and multi-agent RCA agents** such as Flow-of-Action, mABC, RCAgent and OpenRCA's RCA-Agent, often by 20–60 points. Two kinds of structure still pay off: **hypothesis-then-verify** loops (SpecRCA, DiagGuard, LATS-RCA's reflection) and **ML-drafted candidate lists** checked by an LLM. Every strong result uses a frontier API model. No paper evaluates a ≤10B local model as the main RCA agent. The only small-model success is a **fine-tuned 3B verifier** checking candidates drafted by an ML model.

### Cited Findings
**Simple harness vs hand-crafted agents (the most important new result)**
- "Free to Look, Free to Reason" (arXiv 2610.35767, Oct 2026) evaluates on **RCAtlas**: 8 public RCA datasets (OpenRCA 1.0/2.0, RCA-100, RCAEval RE1–3, AIOps 2022/2025, ITBench-SRE, LEMMA-RCA) pooled into one format. Of 542 screened cases, 348 were valid and 90 form the core set across 23 scenarios. — [arXiv 2610.35767](https://arxiv.org/html/2610.35767)
- Mean PR@1 over three models: **Codex CLI 77.2, SQL agent (ReAct over DuckDB) 72.8, one-shot over an evidence package 65.3**. Published agents scored lower: **FoA 53.3, RCAgent 49.3, RCA-Agent 43.3, DecompRCA 28.5, mABC 15.6**. The best non-LLM methods were NSigma 38.9 and TORAI 33.3, with BARO at 22.2. Random was 5.5. — [arXiv 2610.35767](https://arxiv.org/html/2610.35767)
- The "prescribed-call ratio", the share of model calls fixed by the harness, is 0 for the simple harnesses. It is 1.00 for DecompRCA, 0.51 for FoA and 0.35 for RCAgent, and it does not track accuracy. FoA's judge declared a root cause found after one round. RCA-Agent's executor discarded tool outputs above 16,384 tokens, which cost the weakest model 16% of its executor steps. — [arXiv 2610.35767](https://arxiv.org/html/2610.35767)
- Models are anonymised by Artificial Analysis Intelligence Index score, from 29.9 to 52.4, so sizes are unknown. The authors say they cannot tell whether the ordering holds for weaker models. A stronger model mainly improves **reliability**: run-to-run unreliability fell from 32–36 to 7–8 points. A multi-turn harness mainly improves **aptitude**: one-shot never solved 26% of cases in any pass, against 14–16% for agents. — [arXiv 2610.35767](https://arxiv.org/html/2610.35767)
- On cost, the weakest model with Codex reached 68.9% PR@1 for under 1 cent per case. The best run reached 88.9% at about 26 cents and 277 s per case. Raising reasoning effort added about 2–4 points while multiplying wall time by 1.5–4×. — [arXiv 2610.35767](https://arxiv.org/html/2610.35767)

**Trajectory-level study (5,000 trajectories, 9 frameworks)**
- "Beyond Fault Localization" (arXiv 2608.21310) tested 9 frameworks with a Qwen backbone (`qwen3.5-plus`, API) on **RCABench**, a 500-case sample. Acc@1: **ClaudeCode 79.6, ThinkDepth.ai 79.2, AIQ 77.6, TaskWeaver 65.2, RCLAgent V2 53.4, GoS 48.2, OpenRCA 46.6, OpsAgent 45.8, mABC 42.6**. ThinkDepth.ai with Claude Sonnet 4.6 reached 90.0%. — [arXiv 2608.21310](https://arxiv.org/html/2608.21310)
- Getting the root-cause service right does not mean getting the propagation path right. For Qwen ThinkDepth.ai, **Node F1 is 0.78 but Edge F1 is 0.59**, and even correct runs reach only about 0.66 Edge F1. Accuracy drops with causal-chain depth, from 85.5% at depth 2 to 57.1% at depth 5 for Qwen. — [arXiv 2608.21310](https://arxiv.org/html/2608.21310)
- Weaker-backbone behaviour:
  - Qwen acted on the previous round's result in **24.9%** of rounds, against 54.3% for Sonnet.
  - Qwen used `resource_probe` in 16.6% of trajectories, against 82.8% for Sonnet.
  - Qwen fell into shallow `trace_follow` loops, with that 5-gram occurring about 0.96 times per trajectory.
  - Incorrect runs used up to 11.4 more rounds than correct ones.
  - Qwen consumed about 1.74M tokens per case.
  - — [arXiv 2608.21310](https://arxiv.org/html/2608.21310)

**Tree search**
- **LATS-RCA** (arXiv 2605.03505) runs MCTS with UCT (c=1.0) and 5 sampled actions per expansion at temperature 0.7, with an LLM reflection score and log, metric and supervisor agents. On LO2 (100 cases) it reached **91.3% ± 1.2** (5 runs), against 57.4% for multi-agent ReAct and 39.8% for single-agent ReAct, using Claude Sonnet 4.5. The cost was **53.1 calls, 156K tokens and 9.1 min per investigation**, against 13.5 calls, 41K tokens and 1.2 min for single-agent ReAct. — [arXiv 2605.03505](https://arxiv.org/html/2605.03505)
- Backbone sensitivity on LO2: Sonnet 4.5 91.3, Gemini 3 Pro 90.1, GPT-5 89.7, Haiku 4.5 79.6, **GPT-5.2 nano 72.8**. On 37 production incidents at Zoner Oy it averaged 65.1% (range 62–70%) at about 220K tokens and 13 min per incident. Ablations: no reflection 87.6, no backpropagation 84.8, no candidate batching 84.3. — [arXiv 2605.03505](https://arxiv.org/html/2605.03505)

**Hypothesise-then-verify with a small model**
- **SpecRCA** (ICSE-NIER '26, arXiv 2601.02736) works in three stages:
  1. A non-LLM drafter ranks candidates. It uses Wasserstein-distance metric anomalies with Granger weights, trace critical-path residual latency with service PageRank, and log burst mining, all fused over the topology.
  2. **RCALite**, a Llama-3.2-3B verifier distilled with SFT from Claude 3.5 Sonnet, checks each candidate's self-state, parents and children **in parallel**.
  3. A larger LLM synthesises the result.
  
  On AIOps 2022 it reached **R@1 61.34, R@3 75.72, MRR 62.64**, against mABC at 34.19/42.13/38.46 and RCAgent at 22.10/28.40/23.95 (both on Qwen-2.5-Plus). Latency was **9.89 s/query**, against 83.17 s for mABC and 52.79 s for RCAgent. The results are preliminary: one dataset, and the RL stage was not yet run. — [arXiv 2601.02736](https://arxiv.org/html/2601.02736)

**Grounded ReAct over read-only tools (industrial)**
- **ARGUS** (arXiv 2608.23084) runs ReAct over 4 read-only MCP servers (Kubernetes, Prometheus/PromQL, Loki/LogQL, NATS) with runbook and past-incident retrieval. It uses Claude Sonnet 4.6. It found the correct root cause in **10/10** fault-injection scenarios, with 75/82 MCP calls succeeding. This was a single run per scenario at one company, so it is weak evidence for generalisation. — [arXiv 2608.23084](https://arxiv.org/html/2608.23084)

**Earlier context (from the previous note, not re-verified)**
- Flow-of-Action (SOP-guided) scored 64.01% against 35.50% for ReAct in its own paper. "Free to Look" re-ran FoA at 53.3 PR@1 against 72.8 for a plain SQL agent. OpenRCA's best agent solved 11.34%. — [arXiv 2502.08224](https://arxiv.org/pdf/2502.08224); [arXiv 2610.35767](https://arxiv.org/html/2610.35767)

### Inferences
- For Veyltrace v2, the best-supported pattern is: **a deterministic or ML ranker drafts the candidates, an LLM agent investigates each one with a small free-form tool set (query, summarise, compare windows) inside a hard budget, and code verifies**. This combines SpecRCA's drafting and verification, "Free to Look"'s finding that free tool use beats prescribed SOPs, and ARGUS's read-only tools with a sufficiency gate.
- Don't build mABC-style voting or a heavy SOP multi-agent setup. Both independent re-runs put mABC last or near last (15.6 PR@1; 42.6 Acc@1).
- Token budgets are the binding laptop constraint. Single-agent ReAct averaged 41K tokens per case on LO2, and frontier-style agents use 150K–1.7M. Local CPU prefill speeds make even the low end (41K) a multi-minute run (see Q4). Tool outputs must therefore be **compact, code-computed summaries** (top-k anomalies, z-scores, onset times), not raw telemetry dumps. RCA-Agent's 16K-token truncation failure shows what goes wrong otherwise.
- Tree search such as LATS is about 4× the tokens and 7× the wall time of ReAct. It is not laptop-feasible for a live demo. At most, run it as an offline ablation.
- Small models loop and fail to act on prior results (Qwen's 24.9% "acts on previous result"). Have the **controller in code** enforce "one hypothesis → N checks → verdict request" rather than trusting a 9B model to plan long horizons. This is a hypothesis-test loop with a code-owned state machine.

### Gaps
- No 2024–2026 paper found evaluates **≤10B local open-weight models** as the investigating RCA agent on OpenRCA, RCAEval or RCABench. The closest are SpecRCA's fine-tuned 3B verifier and GPT-5.2 nano in LATS-RCA, whose size is unknown. ThinkFL (arXiv 2504.18776, RL-fine-tuned small-model failure localisation) was found but not read.
- "Free to Look" anonymises its models, so its results can't be mapped to parameter counts.
- Flow-of-Action's backbone model was not re-verified here.

---

## Q2. Verification and guarding patterns: what evidence shows they improve accuracy or trust?

### Takeaway
Explicit verification steps give measurable gains:
- DiagGuard: +3.5 to +35.1 pp Acc@1.
- SpecRCA's small-LLM verifier: R@1 nearly double the agent baselines.
- LATS reflection: +3.7 pp.
- ARGUS's grounding rules: 7/10 "fully evidence-backed".

The failure taxonomies show *what* the verifier must catch: fabricated out-of-schema causes, "silence read as health", untested propagation edges and anchoring. The LLM-based verifiers do **not** fix misreading of evidence semantics, so those checks belong in deterministic code. LLM judges used as stop conditions are a documented pitfall.

### Cited Findings
**DiagGuard (arXiv 2608.21310)**
- DiagGuard has two parts. A **Verifier** runs a self-audit before investigation and a soundness check before committing. A **Grounder** builds a search-space profile before the first query. Acc@1 improved in **all 14 configurations, by 3.5–35.1 pp**, with a median of +10.5 pp on RCA100. — [arXiv 2608.21310](https://arxiv.org/html/2608.21310)
- Ablation on AIOps 2025 (Doubao, 5 runs): baseline **43.5±0.6**, Grounder only 47.6±1.6, **Verifier only 48.0±0.9**, full **52.5±1.1**. Mean distinct failure modes per run fell from 1.94 to 1.39. "Edge untested" fell from 57.3% to 44.7% and "friction stop" from 15.1% to 4.7%. **"Semantics misread" did not improve (11.8% → 13.6%).** — [arXiv 2608.21310](https://arxiv.org/html/2608.21310)

**Failure modes the verifier must target** (share of failed runs, Sonnet / Qwen)

| Mode | Sonnet | Qwen |
|---|---|---|
| Edge untested | 54.0% | 68.3% |
| Resource gap | 34.0% | 63.5% |
| Baseline gap | 26.0% | 51.9% |
| Silence-as-health | 30.0% | 44.2% |
| Semantics misread | 86.0% | 61.5% |
| Schema-out claim (fabricated cause outside the label space) | 82.0% | 20.2% |
| Anchor lock | 28.0% | 34.6% |

Stronger models fail mainly by misreading and fabricating; weaker ones by omitting evidence. — [arXiv 2608.21310](https://arxiv.org/html/2608.21310)

**ARGUS grounding rules**
- Evidence is cited by reference number, signals that weren't retrieved are listed, and the report must write **"Unknown" instead of inferring missing values**.
- A **sufficiency gate** rejects reports that lack the minimum evidence for the alert type.
- The confidence label is **computed deterministically from the MCP success ratio and the count of non-MCP sources**, not generated by the model.
- Tool budgets apply, repeated calls are deduplicated and cached, and each server has a circuit breaker.
- Rubric results: Correctness 8 fully / 2 partially / 0 not met; Evidence Backing 7/3/0.
- — [arXiv 2608.23084](https://arxiv.org/html/2608.23084)

**Other verification evidence**
- LATS-RCA's reward is R = 0.5·(LLM reflection score on evidence quality, completeness and consistency) + 0.5·(self-consistency across sampled actions). Removing reflection costs 3.7 pp (91.3 → 87.6). — [arXiv 2605.03505](https://arxiv.org/html/2605.03505)
- SpecRCA's verifier checks each candidate against its local topology (self-state, parents, children), then consolidates evidence. This structured verification is what lets a 3B model work. — [arXiv 2601.02736](https://arxiv.org/html/2601.02736)
- **Pitfall: an LLM judge as the stop condition.** FoA's judge declared the root cause found after one round. In one case FoA matched a generic SOP that never reads logs, and mABC walked the call chain but **missed a service that stopped receiving calls** (silence-as-health). — [arXiv 2610.35767](https://arxiv.org/html/2610.35767)
- LLM-judge biases (position, verbosity, self-enhancement) and >80% agreement with humans: Zheng et al. — [arXiv 2306.05685](https://arxiv.org/abs/2306.05685) (from the earlier note)
- An LLM-as-judge for failure explanations was validated against a 12-person study with participants from software engineering, using pass/fail criteria against a reference root-cause description. This is the pattern to copy: validate any judge against humans before trusting it. — [arXiv 2604.18309](https://arxiv.org/pdf/2604.18309) (search snippet only)
- Constrained decoding itself slightly *improves* task accuracy. On Llama-3.1-8B, GSM8K went from 80.1% (unconstrained) to 83.7% (XGrammar) and 83.8% (Guidance), and Last Letters from 50.7% to 51.2–54.0% (single runs). — [JSONSchemaBench, arXiv 2501.10868](https://arxiv.org/html/2501.10868v2)

### Inferences
Concrete verifier design for Veyltrace v2. Code decides; the LLM output is only a *proposal*.

1. **Closed hypothesis space.** Hypotheses are `{service ∈ enum(topology), fault_class ∈ enum(taxonomy), onset_window}`, enforced by a JSON-schema enum during constrained decoding. This makes "schema-out claims" (82% of Sonnet's failures) impossible to express.
2. **Claims must cite tool-call IDs.** Every supporting claim is `{predicate_id, args, evidence_ref: tool_call_id}`. The verifier **re-executes or looks up** each referenced query from the recorded trace and evaluates the predicate in code, for example `zscore(metric, window) > 3` or `onset(svc) < onset(child)`. The LLM never supplies numbers. This extends the earlier note's slot-based numeric grounding to the agent's *claims*, not just its prose.
3. **Mandatory coverage checks**, aimed at the omission modes:
   - the candidate's baseline vs incident window was compared (baseline gap);
   - at least one parent→child edge was tested (edge untested);
   - resource metrics were probed (resource gap);
   - a **traffic-drop or silence check** was run (silence-as-health).
   
   If coverage is incomplete, the verdict is `INCONCLUSIVE` rather than "best guess".
4. **Deterministic counterfactual and consistency tests.** Examples: "if the candidate is the root, its anomaly onset must precede its dependents' onsets"; "removing the candidate's anomalous edges should leave the downstream anomalies unexplained". These are graph checks in code, which also cover the "semantics misread" mode that LLM self-audits failed to reduce.
5. **Verdict rule in code.** Accept the top hypothesis only if every mandatory predicate passes and its margin over the runner-up meets a calibrated threshold (see Q6). Otherwise abstain. The confidence label is computed, as in ARGUS.
6. **No LLM-as-judge in the decision path.** Use LLM judges only for offline evaluation of prose, validated against human labels.

### Gaps
- No published RCA paper isolates the effect of a **purely deterministic** verifier, as opposed to an LLM-based one, on accuracy. DiagGuard's Verifier is LLM-based.
- No RCA-specific self-consistency ablation was found beyond LATS's combined reward.
- No paper found tests "counterfactual verification" of RCA hypotheses in an LLM pipeline. Item 4 above is a design inference.
- arXiv 2604.18309 was seen only as a search snippet.

---

## Q3. Determinism and replay with LLMs: what is achievable on CPU vs GPU?

### Takeaway
Bit-exact re-generation is achievable on **one machine with a pinned build, single request slot, prompt cache off, and fixed seed** in llama.cpp or Ollama. It is **not portable** across hardware, backends, quantisations or versions. On GPU servers, determinism needs batch-invariant kernels, which in vLLM are beta and limited to recent datacenter-class GPUs per the newest docs. So "every verdict is replayable" should mean **re-verifying recorded LLM outputs**, a cassette replay keyed by content hash. Re-running the model and hoping for identical text is not a sound basis.

### Cited Findings
- **Cause of the problem.** Temperature-0 nondeterminism in servers comes mainly from a **lack of batch invariance**: kernels change their reduction order with batch size, and batch size varies with server load. Floating-point concurrency alone is not the main cause. In an experiment, 1,000 temperature-0 completions of Qwen3-235B gave **80 unique outputs**, diverging at token 103. With batch-invariant kernels, all 1,000 were identical. The cost on Qwen3-8B was 26 s (default) vs 55 s (naive deterministic) vs 42 s (optimised). — [Thinking Machines, "Defeating Nondeterminism in LLM Inference"](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
- **vLLM** has `VLLM_BATCH_INVARIANT=1`, which switches to deterministic kernels at a performance cost. The newest docs mark it beta and require NVIDIA compute capability ≥ 9.0 (H100/H200, B100/B200). Older and stable pages say ≥ 8.0. The docs conflict, so check the version. The tracking issue is vLLM #27433. — [vLLM docs: batch invariance](https://docs.vllm.ai/en/latest/features/batch_invariance/); [stable](https://docs.vllm.ai/en/stable/features/batch_invariance/)
- **llama.cpp server**:
  - On `cache_prompt`, the README says "enabling this option can cause nondeterministic results", because logits are not bit-identical across batch sizes (prompt processing vs generation). — [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
  - The `cache_prompt` default was switched to true. — [commit #10501 mirror](https://cdn04132025.gitlink.org.cn/replica/llama.cpp/commit/47f931c8f9a26c072d71224bc8013cc66ea9e445) (secondary mirror)
  - Using more than one parallel slot "yields results that are not deterministic". — [llama.cpp README fork](https://git.peisongxiao.com/CS348Project/llama.cpp/commit/1b01f06db0cff5f5f600bb754fc39fde565ed56a) (secondary copy; confirm upstream)
  - Per-slot RNG for consistent seeded results under concurrency was added in #6835. — [commit mirror](https://cdn04132025.gitlink.org.cn/replica/llama.cpp/commit/28103f4832e301a9c84d44ff0df9d75d46ab6c76)
  - With temperature > 0, setting a `seed` makes output deterministic again. — [commit #4668](https://app.semanticdiff.com/gh/ggerganov/llama.cpp/commit/65e5f6dadbba4b496bba27f573e473c66b446496)
- **Ollama** is non-deterministic by default. Reproducibility needs `temperature: 0` **and** a fixed `seed`. Drift remains across Ollama versions, quantisations and builds with different compute kernels. — [makandra cards](https://makandracards.com/makandra/626358-ollama-generate-deterministic-results); [Zenn write-up](https://zenn.dev/nonamecode/articles/d98ad5f738995d?locale=en) (secondary)
- **Greedy decoding vs model recommendations.** Qwen3.5-9B's card recommends non-greedy sampling, for example instruct mode at temperature 0.7, top_p 0.8, top_k 20, presence_penalty 1.5. Thinking is on by default and is disabled with `enable_thinking: False`. — [Qwen3.5-9B model card](https://huggingface.co/Qwen/Qwen3.5-9B)
- **Run-to-run variance is large for weaker models even on API harnesses.** The weakest model's PR@1 ranged 62–76% across passes, so single-pass comparisons can flip. — [arXiv 2610.35767](https://arxiv.org/html/2610.35767). Published RCA agent results report ±0.6–1.6 pp over 5 runs (DiagGuard) and ±1.2 (LATS-RCA). — [arXiv 2608.21310](https://arxiv.org/html/2608.21310); [arXiv 2605.03505](https://arxiv.org/html/2605.03505)
- **Record/replay ("cassette") pattern:**
  - Canonicalise each request by stripping volatile fields and sorting keys, including tool lists.
  - Key it by SHA-256.
  - Record the model, prompt (system, user and tool results), parameters (temperature, seed, max_tokens), response (content and tool calls), token counts and latency.
  - Use **strict replay mode, which fails on unrecorded calls**, in CI, and re-record deliberately when the prompt, model or parameters change.
  - — [LLM VCR and agent trace hierarchy](https://understandingdata.com/posts/llm-vcr-and-agent-trace-hierarchy/); [cendor-cassette](https://pypi.org/project/cendor-cassette/1.1.1/); [coding-agent-vcr](https://pypi.org/project/coding-agent-vcr/) (small early-stage libraries)

### Inferences
- **Tier 1 replay (guaranteed):** the verifier's verdict is a pure function of `(incident data snapshot hash, recorded tool results, recorded LLM proposals, verifier code version, config)`. Replay = load the cassette and re-run the verifier, producing the same verdict hash. This works on any laptop, CPU or GPU, and is the claim to put in the paper.
- **Tier 2 re-generation (best effort, same machine):**
  - llama.cpp `llama-server -np 1`, `cache_prompt: false`, fixed `seed`, pinned GGUF (record its SHA-256), pinned llama.cpp build or commit, same thread count and backend.
  - Either greedy (`top_k=1`) or the model's recommended sampler with a fixed seed. The seeded sampler keeps Qwen-recommended quality while staying reproducible on the same build; this is an inference.
  - Report the measured re-generation match rate, for example "N/50 incidents reproduce byte-identical proposals", as a secondary result.
- **CPU vs GPU.** A single-slot CPU run avoids batch-variance from concurrent requests, which makes it the easiest to reproduce. GPU builds may use different kernels per batch shape, and the vLLM batch-invariant mode needs datacenter-class GPUs per the newest docs. This is an inference; no llama.cpp CPU-determinism test was found.
- Because the verifier decides, nondeterministic proposals affect **recall of hypotheses**, not verdict integrity. Report agent accuracy over ≥3–5 seeds with a standard deviation, following DiagGuard and LATS practice.

### Gaps
- No official llama.cpp or Ollama doc guaranteeing bit-exact CPU reproducibility was found, and no measured CPU-vs-CUDA divergence rates for llama.cpp.
- The upstream wording on multi-slot nondeterminism was seen only in a fork copy of the README.
- Whether vLLM batch invariance works on consumer Ada/Ampere laptop GPUs (compute capability 8.6/8.9) is unclear because the docs conflict. vLLM on native Windows was not checked.
- Whether greedy decoding degrades Qwen3.5 thinking mode (earlier Qwen cards warned against greedy) was not confirmed for 3.5.

---

## Q4. Local open-weight models for a 16 GB laptop: tool use, JSON, speed, RAM, licences

### Takeaway
For a 16 GB-RAM Windows laptop:
- **(a) tool-calling agent:** **Qwen3.5-9B** (Apache-2.0, BFCL-V4 66.1, TAU2 79.1, IFEval 91.5, 262K context) is the best-documented choice. **Gemma 4 12B** (Apache-2.0, Tau2 69.0) is a strong alternative. **Qwen3.5-4B** (TAU2 79.9, BFCL-V4 50.3) is the CPU-only fallback.
- **gpt-oss-20b** (Apache-2.0, 21B total / 3.6B active, "runs within 16GB") is fast per token but tight on 16 GB RAM, and it requires the harmony format.
- **(b) explanation writing:** use the same model in non-thinking mode, or Gemma 4 E4B/12B. With slots, enums and the verifier, prose quality matters less than schema fidelity.
- **Speeds:** expect roughly 3–15 tok/s CPU-only for 8–9B Q4, and tens of tok/s fully on a GPU.

### Cited Findings
**Qwen3.5 (Feb 2026)**
- **Qwen3.5-9B:** Apache-2.0. 9B parameters (10B with vision), hybrid Gated DeltaNet plus Gated Attention, context 262,144 native (up to about 1M with YaRN). Thinking on by default, switchable off. Tool calling via the `qwen3_coder` parser in vLLM and SGLang. — [Qwen3.5-9B model card](https://huggingface.co/Qwen/Qwen3.5-9B)
- **Benchmarks:**

| Model | BFCL-V4 | TAU2-Bench | IFEval | IFBench |
|---|---|---|---|---|
| Qwen3.5-9B | 66.1 | 79.1 | 91.5 | 64.5 |
| Qwen3.5-4B | 50.3 | 79.9 | 89.8 | 59.2 |

— [Qwen3.5-9B model card](https://huggingface.co/Qwen/Qwen3.5-9B)
- Other Qwen3.5 BFCL-V4 figures: 0.8B 25.3, 2B 43.6, 27B 68.5, 397B 72.9. These are vendor numbers, not yet on the independent BFCL board as of mid-2026. — [vdf.ai](https://vdf.ai/blog/best-small-language-models/); [d-central compilation](https://d-central.tech/local-llm-agent-capability/) (secondary)
- Ollama's default `qwen3.5` tag resolves to 9B. Some third-party GGUF repos carry custom licences, so use the official or Unsloth GGUFs. — search summary (secondary), [SoAIHQ GGUF](https://huggingface.co/SoAIHQ/Qwen3.5-9B-GGUF)

**Gemma 4 (official model card)**

| Variant | Parameters | Context | Tau2 avg (3 runs) |
|---|---|---|---|
| E2B | 2.3B effective | 128K | 24.5% |
| E4B | 4.5B effective (8B with embeddings) | 128K | 42.2% |
| 12B | 11.95B | 256K | **69.0%** |
| 26B A4B (MoE) | 25.2B total / 3.8B active | 256K | 68.2% |
| 31B | 30.7B | 256K | 76.9% |

Apache 2.0. Gemma 3 27B scored 16.2%. — [Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4)
- Secondary sources cite "86.4% Tau2 Retail" for the 31B. That is a single-domain number and not comparable to the card's 3-domain average. — [agentmarketcap](https://agentmarketcap.ai/blog/2026/04/05/google-gemma-4-open-weight-models-agentic-tasks-frontier-reasoning) (secondary)
- Q4_0 weight memory (+~20% overhead, excluding the KV cache): E4B 4.5 GB, 12B 6.7 GB. — [Gemma core docs](https://ai.google.dev/gemma/docs/core) (from the earlier note)

**gpt-oss-20b**
- Apache 2.0. 21B total / **3.6B active** MoE, MXFP4 on the MoE weights, "runs within 16GB of memory". Reasoning effort low, medium or high. Native function calling and structured outputs. **Must use the harmony response format.** — [HF model card](https://huggingface.co/openai/gpt-oss-20b)
- Memory in practice:
  - A Q4_K_M GGUF is about 11.6 GB, so an 8 GB GPU needs CPU offload.
  - Ollama shows `gpt-oss:20b` at about 13–14 GB loaded.
  - Microcenter states that 16 GB of total system memory is not enough.
  - Unsloth says 14 GB of combined memory gives 6+ tok/s with its dynamic 4-bit quant.
  - — [glukhov 16GB VRAM benchmarks](https://www.glukhov.org/llm-performance/benchmarks/choosing-best-llm-for-ollama-on-16gb-vram-gpu/); [Microcenter](https://www.microcenter.com/site/mc-news/article/can-your-pc-run-gpt-oss-ai.aspx); [Unsloth docs](https://docs.unsloth.ai/basics/gpt-oss)

**Other families** (secondary compilation, last reviewed 18 Jul 2026)
- IBM Granite 4.1: 8B BFCL-v3 68.27%, 30B 73.68%.
- Phi-4-mini (3.8B): BFCL v4 "low-to-mid 80s", third-party with no official row.
- Qwen3 dense: tau2-Telecom 14B 32%, 4B-2507 27%.
- No usable BFCL scores for Mistral Small 3.x/4, Gemma 2/3 or DeepSeek-R1 distills.
- BFCL v3 and v4 are not cross-comparable.
- — [d-central](https://d-central.tech/local-llm-agent-capability/) (secondary; verify against the BFCL board)
- A third-party write-up says tool-use accuracy "falls off a cliff" below about 7B. Unverified. — [search summary of framework comparisons](https://pooyagolchian.com/blog/ai-agents-frameworks-local-llm-2026/) (secondary)

**Throughput (mostly secondary, mixed hardware)**
- **Desktop GPUs:**
  - RTX 3060 12 GB with llama.cpp: Qwen3 8B 42.0 tok/s at 16K context (31.9 at 32K); Qwen3 14B 22.7 tok/s. — [singhajit](https://singhajit.com/llm-inference-speed-comparison/)
  - 16 GB-VRAM GPU with Ollama, fully on GPU: `gpt-oss:20b` 139.93 tok/s; `qwen3:14b` 61.85 tok/s. — [glukhov](https://www.glukhov.org/llm-performance/benchmarks/choosing-best-llm-for-ollama-on-16gb-vram-gpu/)
  - RTX 4060 Ti 16 GB: gpt-oss-20b about 83 tok/s at ~4K context, 57.8 at 16K. — search summary citing [llama.cpp gpt-oss guide](https://github.com/ggml-org/llama.cpp/discussions/15396) / [llamabuilds](https://www.llamabuilds.ai/models/gpt-oss-20b) (secondary)
- **RTX 4060 8 GB with CPU offload:** Qwen2.5-32B Q4_K_M 10.8 tok/s. — [bswen](https://docs.bswen.com/blog/2026-03-27-rtx-4060-token-speed-benchmark-coding/)
- **CPU-only laptops:**
  - 8B Llama-3 Q4_K_M on an i7-1165G7 (4 cores): 6.1–6.5 tok/s. — [dev.to](https://dev.to/tekk_73/an-8b-llm-on-a-4-core-laptop-cpu-no-gpu-6-tokenssec-25gi)
  - Qwen3 8B Q4_K_M on a 16 GB laptop: estimates of 8–15 tok/s, and 3–6 tok/s on Ryzen 7 / Core i7. These are labelled estimates. — [promptquorum](https://www.promptquorum.com/local-llms/local-llm-on-laptop); [localaimaster](https://localaimaster.com/blog/run-llm-cpu-only)
  - Gemma 4 via LiteRT-LM: about 17 tok/s decode on an Intel Lunar Lake CPU (from the earlier note). — [Google LiteRT-LM](https://developers.google.com/edge/litert-lm/models/gemma-4)
  - gpt-oss-20b on a 16 GB Mac mini M4 (unified memory, not comparable to x86): 17.8 tok/s short prompt, 12.9 long. — [Microcenter](https://www.microcenter.com/site/mc-news/article/can-your-pc-run-gpt-oss-ai.aspx)

### Inferences
**Recommended stack.** Qwen3.5-9B Q4_K_M via llama.cpp `llama-server` or Ollama for tool calling. Weights are roughly 5.5–6.5 GB by parameter count; this is an estimate, so measure it. Keep context at 8–16K to bound the KV cache.
- **GPU laptops (RTX 4060 8 GB):** fully offloaded, expect a few tens of tok/s.
- **CPU-only 16 GB laptops:** expect roughly 4–10 tok/s decode, so budget each investigation to about 10–20 short LLM turns.
- **Fallbacks:** Qwen3.5-4B for weak CPUs (its TAU2 score equals the 9B's, but BFCL is 16 points lower), or Gemma 4 E4B for narration only, since its Tau2 of 42.2 is too weak to drive tools.

**Models to avoid as the main agent on 16 GB:**
- gpt-oss-20b: 13–14 GB loaded leaves no room for Windows and the telemetry store on 16 GB RAM. It is a good option only with an 8 GB+ GPU plus offload, or on a 32 GB machine.
- Gemma 4 26B-A4B / 31B and Mistral Small 24B: too large at Q4 for 16 GB alongside the system.
- Llama 4 (Scout is 109B total): too large.
- DeepSeek-R1 distills: no reliable function-calling scores.

**For explanations** (prose with slots, constrained by schema): use the same Qwen3.5-9B with thinking off to avoid loading a second model. Gemma 4 12B, if RAM allows, is an option for an A/B of narration quality.

**For the paper**, report each model with its GGUF SHA-256, quant type, llama.cpp commit, and `llama-bench` pp512/tg128 on each team laptop. The published laptop numbers are too weak to quote as facts.

### Gaps
- There is no independent BFCL-v4 row for Qwen3.5-9B/4B or Gemma 4. The Qwen and Gemma figures are vendor-reported, and BFCL and Tau2 aren't comparable to each other.
- No reliable measured llama.cpp CPU-only tok/s (pp or tg) was found for Qwen3.5-9B, Gemma 4 12B or gpt-oss-20b on x86 laptops. No RTX 3050/4060 **laptop** GPU measurements were found for these models.
- The GGUF file sizes for Qwen3.5-9B Q4_K_M are not verified from an official source.
- Whether a "Qwen3.6" or newer small model exists by late October 2026 was not checked. Llama 4, Mistral Small 4 and Phi-4 (14B) were not individually researched.
- No benchmark of RCA-explanation writing quality by small local models was found.

---

## Q5. Structured output enforcement and lightweight, reproducible function-calling frameworks

### Takeaway
Use **grammar-constrained JSON** from the inference server: llama.cpp `json_schema`/GBNF, or Ollama's `format` with a JSON Schema generated from Pydantic. Validate again in code with Pydantic. JSONSchemaBench shows that open-source engines handle simple function-call-style schemas at about 93–96% empirical coverage, but coverage collapses on complex schemas. Keep schemas flat, enum-heavy and small. For the agent loop, a **plain Python loop with Pydantic models** (or PydanticAI) is the easiest to record and replay. smolagents' code-as-action and LangGraph add surface area without solving determinism.

### Cited Findings
- **JSONSchemaBench** (about 10K real schemas; models: Llama-3.2-1B for open engines) — [arXiv 2501.10868](https://arxiv.org/html/2501.10868v2)

  Empirical coverage:

  | Schema set | LM only | Guidance | llama.cpp | Outlines | XGrammar | OpenAI | Gemini |
  |---|---|---|---|---|---|---|---|
  | GlaiveAI (simple function schemas) | 0.90 | 0.96 | 0.95 | 0.95 | 0.93 | 0.89 | 0.86 |
  | Kubernetes | 0.56 | 0.91 | 0.76 | 0.57 | 0.07 | – | – |
  | GitHub Hard | 0.13 | 0.41 | 0.39 | 0.03 | 0.28 | 0.09 | – |

  - Closed APIs reach compliance near 1.00 but cover only a subset of JSON Schema.
  - Compile time: llama.cpp grammar about 0.05 s, Guidance about 0.00–0.01 s, Outlines 3.5–8 s.
  - On GlaiveAI, time per output token: Guidance 6.37 ms, llama.cpp 29.98 ms, LM only 15.40 ms. Guidance is fastest thanks to fast-forwarding.
- **llguidance** (the Guidance engine) claims on-the-fly mask computation with near-zero startup, and lists integration into llama.cpp (2025-02-01), vLLM and SGLang. These are vendor README claims. — [llguidance](https://code.gitlink.org.cn/dnrops/llguidance) (mirror)
- **Ollama structured outputs:**
  - Pass a JSON Schema in `format`, for example Pydantic `Model.model_json_schema()`, then validate with `model_validate_json`.
  - Ollama recommends temperature 0 and **also putting the schema in the prompt** "to ground the model's response".
  - The OpenAI-compatible `response_format` works too.
  - Ollama's cloud does **not** support structured outputs.
  - — [Ollama docs: structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- **gpt-oss** requires the harmony format; Qwen3.5 uses the `qwen3_coder` tool parser on vLLM/SGLang. Tool-call parsing therefore depends on chat templates, which is another versioned artefact to pin. — [gpt-oss card](https://huggingface.co/openai/gpt-oss-20b); [Qwen3.5-9B card](https://huggingface.co/Qwen/Qwen3.5-9B)
- **Frameworks (secondary sources):**
  - **PydanticAI** is type-safe, enforces output schemas at each boundary and supports Ollama. Its stable v2 line launched around June 2026; version claims conflict between sources.
  - **smolagents** (Hugging Face) has agents write **code as actions**, with a JSON `ToolCallingAgent` option. It claims about 30% fewer LLM calls (secondary).
  - **LangGraph** is the heaviest of the three, graph and state oriented, connecting to Ollama via `langchain_ollama`.
  - — [ZenML: PydanticAI vs LangGraph](https://zenml.io/blog/pydantic-ai-vs-langgraph); [ZenML: smolagents vs LangGraph](https://www.zenml.io/blog/smolagents-vs-langgraph); [jangwook comparison](https://jangwook.net/en/blog/en/python-ai-agent-library-comparison-2026/)

### Inferences
- **Two output modes:**
  - (1) **Tool calls:** constrain the agent turn to a schema such as `{"action": enum[tool names], "args": {...}, "hypothesis_id": enum, "why": str≤200}`. Use the server's `json_schema` instead of model-native tool templates, so the same schema works across Qwen, Gemma and gpt-oss without per-model parsers. That avoids harmony and qwen3_coder parsing differences, but it is an inference, so validate it.
  - (2) **Narrative:** use the earlier note's slot schema.
- Keep schemas within the "GlaiveAI-like" complexity band (flat objects, enums, required fields, no `oneOf`/`patternProperties`/recursion). That band is where llama.cpp reaches 0.95 coverage. Always re-validate with Pydantic and treat a validation failure as a recorded, verifier-visible event, not a silent retry.
- **Framework choice:** a ~200-line plain loop (`while budget: ask_llm → validate → run_tool → record`) gives full control of what is hashed and recorded. That property is what makes Tier-1 replay simple. PydanticAI is acceptable if the team wants typed tools. Avoid smolagents' code-execution agents in the decision path, because arbitrary generated code is hard to verify and replay. Avoid LangGraph unless graph state is needed; this is an inference.

### Gaps
- No benchmark compares PydanticAI, smolagents and LangGraph tool-call success with local ≤10B models.
- JSONSchemaBench used Llama-3.2-1B and older engine versions (early 2025). Late-2026 coverage for llama.cpp with the llguidance backend vs its built-in GBNF converter was not found.
- How Ollama's `format` interacts with native tool calling in the same request was not documented in the page read.

---

## Q6. Calibration and abstention for RCA / AIOps

### Takeaway
There is little RCA-specific calibration literature:
- **LM-PACE** (Microsoft, FSE 2024 Industry): reduced the calibration error of LLM root-cause confidence to 31% of direct prompting on more than 100K incidents.
- A 2026 conformal changepoint and RCA paper with finite-sample coverage sets.
- An OSDI 2026 "abstention protocol" for network RCA.
- Industrial systems (ARGUS, Datadog Bits) compute confidence or "inconclusive" states with rules.

No published work combines conformal prediction with abstention for microservice RCA, which is a research gap Veyltrace v2 can claim.

### Cited Findings
- **PACE-LM / LM-PACE.** Black-box LLM RCA can't be recalibrated by fine-tuning or temperature scaling, so the method prompts a retrieval-augmented LLM in two stages: confidence in its own grounding for this incident, then a rating of the prediction against historical cases. A learned transformation combines the two. This **reduced expected calibration error to 31% of the direct-prompting baseline** on more than 100,000 Microsoft incidents. — [arXiv 2309.05833](https://arxiv.org/pdf/2309.05833); [FSE 2024 Industry](https://2024.esec-fse.org/details/fse-2024-industry/37/LM-PACE-Confidence-Estimation-by-Large-Language-Models-for-Effective-Root-Causing-of)
- **Conformal RCA.** CONCH gives a set of plausible changepoints with finite-sample coverage. CROC gives distribution-free confidence sets for which stream changed first, applied to offline root-cause localisation under corrupted observations. — [arXiv 2607.26481](https://arxiv.org/pdf/2607.26481) (search snippet only)
- **Abstention-based RCA.** "The Abstention Protocol: RCA for Clos Fabrics" (CoreSec, listed for OSDI '26) replaces weighted score fusion with an abstention-based composition of telemetry agents that abstain when evidence is ambiguous. — [papers.cool OSDI'26 listing](https://papers.cool/venue/gaikwad@osdi26@USENIX) (search snippet only)
- **ARGUS** computes its confidence label deterministically from the MCP success ratio and the count of non-MCP sources. — [arXiv 2608.23084](https://arxiv.org/html/2608.23084). **Datadog Bits AI SRE** marks hypotheses validated, invalidated or inconclusive. — [Datadog docs](https://docs.datadoghq.com/bits_ai/bits_ai_sre/investigate_alerts) (from the earlier note)
- **Practitioner view.** In a Westermo industrial experience report on LLM test-failure RCA, practitioners **found confidence values hard to interpret**. They valued reports for pointing to relevant evidence even when they rejected the proposed root cause. — [arXiv 2609.21843](https://arxiv.org/pdf/2609.21843) (search snippet only)

### Inferences
- **Split-conformal top-k sets over the deterministic ranker's scores.** Calibrate a nonconformity score, for example 1 − normalised rank score or the margin to the top-1, on a held-out set of benchmark incidents (RCAEval/RCABench cases). Emit a candidate set guaranteed to contain the true root cause with ≥90% marginal probability. **Abstain**, verdict `INCONCLUSIVE`, when the set is larger than k (e.g. 3) or when coverage predicates fail. The calibration is code-only, deterministic and replayable. The guarantee is marginal and assumes exchangeability, so state that and report empirical coverage per dataset. This is an inference built from standard split conformal; no source above applies it to microservice RCA.
- **Selective-prediction metrics** for the paper: risk–coverage curves (accuracy vs fraction answered) and AURC, comparing (i) the ranker alone, (ii) ranker plus agent proposals plus verifier, and (iii) the verifier with abstention.
- Show confidence as a **set plus a reason**, such as "verified: 4/4 predicates; candidate set {A, B}", not a bare probability. This answers the Westermo finding that numeric confidences confuse practitioners.
- Don't use LLM self-reported confidence in the verdict. LM-PACE shows raw prompting is badly calibrated, and it needed retrieval plus a learned transform to fix it.

### Gaps
- The conformal RCA paper (2607.26481) and CoreSec (OSDI '26) were seen only as search snippets, so methods and numbers are unverified.
- No paper was found on calibrating **agentic** (multi-step) RCA, as opposed to single-shot prediction.
- No AIOps paper reporting risk–coverage or AURC for microservice RCA was found.

---

## Q7. Provenance and receipts: recording evidence lineage so verdicts can be audited

### Takeaway
There is no finished standard for "LLM agent receipts" as of October 2026. The practical recipe combines three things:
- **W3C PROV vocabulary**: Entity, Activity and Agent, with `used`, `wasGeneratedBy` and `wasAssociatedWith`. PROV-AGENT extends it for agents, LLM calls and tool calls.
- **in-toto Statement v1** envelopes, where subjects are matched by content digest, to attest "this verdict was produced from these input hashes by this verifier version".
- A **hash-chained, append-only trace** in the style of the IETF WCA draft.

### Cited Findings
- **PROV-AGENT** (IEEE e-Science 2025) extends W3C PROV so that agent prompts, responses and decisions link to end-to-end workflow provenance, using MCP and data observability. It ships an open-source near-real-time capture system, evaluated across edge, cloud and HPC. — [arXiv 2508.02866](https://arxiv.org/abs/2508.02866). Search summaries describe AI agents as a subclass of `prov:Agent` and tool executions and LLM calls as `prov:Activity` subclasses. — [alphaXiv overview](https://www.alphaxiv.org/overview/2508.02866) (secondary)
- **in-toto Statement v1** has these fields:
  - `_type` = `https://in-toto.io/Statement/v1`;
  - `subject[]`, a list of ResourceDescriptors where each "MUST have `digest` set";
  - `predicateType` (a URI);
  - `predicate` (an object).
  
  "Subject artifacts are matched purely by digest, regardless of content type." — [in-toto attestation spec v1](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)
- **IETF draft "WCA"** (March 2026, Informational, individual submission, expires 2 Sep 2026) proposes an **append-only, hash-chained sequence of attestation records for agent tool calls**. Its "Warrant Attestation Levels" are graded like SLSA build levels. It certifies data **sources, not data content**. — [draft-bondar-wca-00](https://www.ietf.org/archive/id/draft-bondar-wca-00.html)
- **Cassette or replay records** should contain the model, full prompt including tool results, parameters, response, token counts and latency, keyed by a SHA-256 of the canonicalised request. — [understandingdata.com](https://understandingdata.com/posts/llm-vcr-and-agent-trace-hierarchy/)
- **ARGUS** records a stop reason in each investigation trace and derives confidence from that trace, but has no replay mechanism. — [arXiv 2608.23084](https://arxiv.org/html/2608.23084)

### Inferences
**Veyltrace v2 "verdict receipt".** One JSON document per incident, plus a JSONL trace:
1. **Inputs.** `telemetry_snapshot`: a SHA-256 over canonical Parquet or JSON of the incident window, plus the topology hash.
2. **Activities (PROV).** Each step is an Activity with `{id, type: tool_call|llm_call|verifier_check, started, ended, used: [entity hashes], generated: [entity hash], wasAssociatedWith: agent_id}`.
   - LLM calls also record `model_gguf_sha256`, `runtime@commit`, `params{temp, seed, top_k}`, `prompt_sha256`, `response_sha256` and `schema_sha256`.
   - Tool calls record `query_text`, `result_sha256` and the code-computed summary.
3. **Hash chain.** Each trace line includes `prev_hash`, so `line_hash = sha256(prev_hash || canonical_json(line))`, as in WCA's append-only chain. Use RFC 8785 JSON canonicalisation or sorted-key, no-whitespace JSON.
4. **Verdict entity.** `{verdict, candidate_set, predicates[{id, args, result, evidence_refs}], verifier_code_sha256, config_sha256}`, with `verdict_hash` over all of it.
5. **in-toto envelope.** `subject = [{name: "verdict.json", digest: {sha256: …}}]`, `predicateType = "https://veyltrace.dev/rca-verdict/v1"` (our own URI), and a predicate holding the input hashes, trace head hash and tool versions. Optionally sign with a local key (DSSE or minisign) for the demo.
6. **`veyltrace replay <receipt>`** reloads the snapshot and cassette, re-runs the verifier and asserts an identical `verdict_hash`. Its exit code is the audit.

This is a design inference; no source gives this exact combination.

### Gaps
- PROV-AGENT's full class model and overhead numbers were not read (abstract only).
- The DSSE wrapping details weren't on the page fetched.
- No precedent was found of in-toto used for ML or LLM inference receipts; it is supply-chain oriented.
- C2PA or other content-credential approaches for text verdicts were not examined.

---

## Q8. Evaluating explanations: how papers measure the faithfulness and usefulness of RCA explanations

### Takeaway
RCA papers mostly evaluate explanations in five ways:
- **Rubrics scored by humans** (ARGUS: Correctness, Evidence Backing and Actionability, each fully/partially/not met, with inter-rater agreement).
- **Practitioner interviews** (ARGUS, 6 on-call engineers; Westermo).
- **Path-level grounding metrics** (Node/Edge F1 against annotated propagation paths; OpenRCA 2.0's verified causal path).
- **LLM-as-judge** with human validation.
- **Atomic-claim support metrics** such as FActScore and ALCE citation precision and recall (from the earlier note).

Veyltrace v2 can make faithfulness *mechanically checkable*: the share of claims whose predicates the verifier re-evaluates as true.

### Cited Findings
- **ARGUS rubric:**
  - Correctness 8/2/0, Evidence Backing 7/3/0, Actionability 7/1/2 (fully / partially / not met, 10 scenarios).
  - Inter-rater agreement 83.3% exact before adjudication, **Cohen's κ = 0.36 but Gwet's AC1 = 0.81**. κ is deflated when ratings are skewed, so report both.
  - Interviews with **6 on-call engineers** (8 themes): practitioners trusted the diagnosis but doubted the recommended fixes.
  - — [arXiv 2608.23084](https://arxiv.org/html/2608.23084)
- **Path-grounding metrics.** Service-level propagation paths are annotated and scored with **Node F1 and Edge F1**. The best Qwen arm scores Node F1 0.78 and Edge F1 0.59. A failure taxonomy is labelled by humans with 93.5–98% agreement. — [arXiv 2608.21310](https://arxiv.org/html/2608.21310). OpenRCA 2.0 reports a 61.5% verified causal path vs 76% correct-service. — [arXiv 2606.27154](https://arxiv.org/abs/2606.27154) (from the earlier note)
- **Judge validation.** An LLM judge for failure explanations was checked against a 12-person study; participants rated 3 explanations per defect against a reference root cause with pass/fail criteria and a difficulty rating. — [arXiv 2604.18309](https://arxiv.org/pdf/2604.18309) (search snippet)
- **Reasoning-quality taxonomy.** Riddell et al. ("Stalled, Biased, and Confused", FORGE '26 distinguished paper) ran 48,000 simulated failure scenarios and built a 16-category RCA reasoning-failure taxonomy scored with an LLM judge. Their argument is that reasoning quality matters as much as accuracy. — [UWaterloo news](https://cs.uwaterloo.ca/news/se-researchers-win-acm-sigsoft-distinguished-paper-award-forge-2026); [thesis PDF](https://dspacemainprd01.lib.uwaterloo.ca/server/api/core/bitstreams/efc62ad6-993c-46b0-9bc7-d46e6714ceb2/content)
- **Westermo report.** Practitioners valued evidence pointers more than the proposed root cause and found confidence values hard to interpret. — [arXiv 2609.21843](https://arxiv.org/pdf/2609.21843) (search snippet)
- **Atomic-claim metrics** from the earlier note: FActScore (share of supported atomic facts; estimator error <2%) and ALCE citation recall and precision (85.1% and 77.6% agreement with humans). — [arXiv 2305.14251](https://arxiv.org/abs/2305.14251); [arXiv 2305.14627](https://arxiv.org/pdf/2305.14627)

### Inferences
Evaluation plan for the paper (laptop-feasible):
1. **Mechanical faithfulness.**
   - *Claim validity* = the share of explanation claims whose `{predicate, evidence_ref}` re-evaluates true in the verifier.
   - *Citation coverage* = the share of sentences with at least one evidence ref.
   - *Numeric fidelity* = the share of numbers rendered from slots; this should be 100% by construction.
   
   These are computed by code with no judge.
2. **Path grounding.** Node and Edge F1 of the explanation's propagation path against the injected fault's ground-truth path, for datasets with path labels (RCABench, RCA100), or against the topology plus the injection point for our own demo system.
3. **Human rubric** following ARGUS (Correctness, Evidence Backing, Actionability; three levels), with 2 raters per item and κ and AC1 reported. Feasible with a 3-person team plus 2–3 outside SRE or student raters on 20–30 incidents.
4. **Optional LLM judge.** Use a different family from the generator (earlier note). Validate it on the human-rated subset and report agreement before using it at scale.
5. **Ablations:** LLM off (template) vs LLM narration, and verifier on vs off. Report the rejection rate and failure categories, following DiagGuard's taxonomy.

### Gaps
- No published user study measures whether engineers can **detect** unfaithful RCA explanations, or how verification badges change trust or decision time.
- No standard RCA-explanation benchmark with gold explanations was found.
- 2604.18309 and 2609.21843 were seen only as search snippets, so their sample details are unverified.
