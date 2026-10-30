# Local-first LLM: Qwen3.5 on Ollama or llama.cpp, with cassette replay tiers

- **Status:** Accepted (default model per laptop confirmed at M0, per [02 §12](../02-architecture.md))
- **Date:** 2026-10-30
- **Author:** Aniket Kumar (ak)
- **Deciders:** lead, Explain lane
- **Consulted:** all lanes
- **Issue / CCR:** kickoff; M0 benchmark task L-01
- **Supersedes:** none · **Superseded by:** none

## Context

- The build and demo run on 16 GB Windows laptops with no cloud for now ([01 §10](../01-vision-and-requirements.md)).
- We found no paper that evaluates a ≤ 10B model as the investigating RCA agent; the closest are SpecRCA's fine-tuned 3B verifier and ThinkFL, which fine-tunes lightweight LLMs of unconfirmed size; every strong agent result uses a frontier cloud model ([verified_agents §Q1][va]).
- Best-documented small tool-calling models (all scores vendor-reported, [verified_agents §Q4][va]):

| Model | Licence | Tool-use scores | Fit on 16 GB |
|---|---|---|---|
| Qwen3.5-9B | Apache-2.0 | BFCL-V4 66.1, TAU2 79.1, IFEval 91.5 | Q4_K_M weights ~5.5–6.5 GB (*estimate*) |
| Qwen3.5-4B | Apache-2.0 | BFCL-V4 50.3, TAU2 79.9 | fallback for weak CPUs |
| Gemma 4 12B | Apache-2.0 | Tau2 69.0 | Q4_0 weights ~6.7 GB |
| gpt-oss-20b | Apache-2.0 | native tool calls; harmony format required | ~13–14 GB once loaded |

- CPU speed is the binding constraint: one measured point is 6.1–6.5 tokens/s for an 8B Q4_K_M model on a 4-core laptop CPU; other figures are 3–15 tokens/s *estimates* ([verified_agents §Q4][va]). A single-agent ReAct run used ~41K tokens per case on LO2 ([verified_agents §Q1][va]).
- Bit-exact regeneration is not portable: 1,000 temperature-0 completions of one server model gave 80 distinct outputs; llama.cpp warns that `cache_prompt` can make results nondeterministic; Ollama needs temperature 0 and a fixed seed and still drifts across versions and quantisations ([verified_agents §Q3][va]).
- Grammar-constrained JSON in llama.cpp covers ~0.95 of simple function-call schemas but collapses on complex ones (0.39 on "GitHub Hard") ([verified_agents §Q5][va]).

## Decision drivers

- No telemetry or prompt leaves the laptop by default.
- The verdict must replay on any laptop regardless of LLM nondeterminism.
- The LLM step must fit the token budget a CPU can afford.
- Swappable providers without per-model parsers.

## Considered options

1. **Local Qwen3.5-9B (fallback 4B) via Ollama or llama.cpp `llama-server`; cassette replay** (chosen).
2. Gemma 4 12B as the default.
3. gpt-oss-20b.
4. A frontier cloud model as the default.
5. vLLM with batch-invariant kernels for deterministic regeneration.
6. An agent framework (LangGraph, smolagents) instead of a plain loop.

## Decision

1. **Default model:** Qwen3.5-9B Q4_K_M; fallback Qwen3.5-4B on laptops where `llama-bench` shows the 9B cannot meet the `brief`-mode budget. Each laptop runs `llama-bench` at M0 and records pp512/tg128 and the GGUF SHA-256 in `docs/team/<initials>.md`. The GGUF SHA-256 is pinned in `config/llm.yaml` and recorded in every run manifest. Use official or Unsloth GGUFs (some third-party GGUF repos carry custom licences, [verified_agents §Q4][va]).
2. **Runtime:** Ollama or llama.cpp `llama-server` with a single slot, prompt cache off, fixed seed, pinned runtime version ([02 §8](../02-architecture.md)). Sampler: the model card's recommended non-thinking settings with a fixed seed (*initial default*, confirmed by an M0 pilot); greedy decoding is an ablation.
3. **Structured output:** server-side JSON-schema constrained decoding with flat, enum-heavy schemas (no `oneOf`, recursion or pattern properties), schema restated in the prompt, Pydantic re-validation; a validation failure is a recorded event, not a silent retry. One schema works across models, so no per-model tool parsers.
4. **Shape:** a plain code-owned state machine; `brief` mode (one or two calls over evidence cards) is the default and `investigate` is an ablation; budgets ≤ 5 hypotheses, ≤ 12 turns, ≤ 16K context, ≤ 180 s on CPU ([02 §6.8](../02-architecture.md)).
5. **Privacy:** `veyltrace_llm` talks to `localhost` only; any remote endpoint (LAN split demo, OpenAI-compatible server) needs `VEYLTRACE_ALLOW_REMOTE_LLM=1` ([02 §9](../02-architecture.md)).
6. **Replay tiers:**
   - **Tier 1 (guaranteed):** the verdict is a pure function of input hashes, recorded tool results, recorded proposals, code and config. `ai.mode = replay` reads the cassette (keyed by SHA-256 of the canonicalised request) and fails on any unrecorded call. `veyltrace replay` must reproduce `verdict_hash`.
   - **Tier 2 (best effort):** regenerate on the same machine with the same pinned build and settings; report the measured match rate (RQ6), never claim it.
7. **Cloud adapters later:** an OpenAI-compatible or Bedrock provider may be added post-v1.0 behind the same interface ([02 §10](../02-architecture.md)). Using a frontier cloud model as an offline, cassette-recorded comparison arm is **not** part of v1.0; it needs its own ADR because it conflicts with "no cloud for now" ([report][rep], "Qwen3.5-9B on CPU fits the proposer role").

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Gemma 4 12B default | Strong Tau2 (69.0), Apache-2.0 | Larger weights; lower vendor tool-use evidence than Qwen3.5-9B | Allowed as an A/B arm if RAM permits |
| gpt-oss-20b | Fast per token on GPUs | ~13–14 GB loaded leaves no room for Windows and the store on 16 GB; harmony format | Does not fit |
| Frontier cloud default | Best accuracy evidence | Sends incident data off the laptop; cost per call; violates "no cloud for now" | Privacy and constraint; may return as an opt-in adapter |
| vLLM batch-invariant mode | Deterministic regeneration | Beta; newest docs require datacenter GPUs (compute capability ≥ 9.0) | No such hardware |
| LangGraph / smolagents | Ready-made loops | More surface; harder to control exactly what is hashed and recorded; code-as-action is hard to verify | A ~200-line loop is simpler to replay |

## Consequences

- **Positive:** Zero marginal cost per diagnosis; no data leaves the laptop; verdict integrity is independent of model nondeterminism, which only affects which hypotheses get tested.
- **Negative:** Proposer quality is likely low, so lift may be zero (still reportable). Per-laptop model choice adds variance; results must name the model per run. A 9B model and the lab likely exceed 16 GB on one laptop, so the single-laptop demo runs with `--ai off` or the 4B model, and an AI-on demo with the 9B model uses the split or cassette shape ([02 §10](../02-architecture.md)). Running the AI arm on all 270 RE2 cases × 3 seeds is ~20 laptop-hours at ~1.5 min per call (*estimate*, [report][rep]).
- **Follow-ups:** L-01 benchmarks; X-01 provider and cassette; X-07/X-08 Relentra; contamination probe by service-name anonymisation (RQ4).

## Confirmation

- Strict-mode replay fails on a missing cassette entry (X-01 acceptance).
- 100% Tier-1 replay on recorded RE2 cases at M3.
- `brief` mode p95 ≤ 180 s plus Causivra narration ≤ 60 s on the slowest laptop ([02 §9](../02-architecture.md), *targets*), or the fallback is applied.

## Evidence

- [verified_agents §Q1, §Q3–Q5][va]; [report][rep], "Replay re-verifies recorded proposals instead of re-generating them" and "Qwen3.5-9B on CPU fits the proposer role within a token budget".

[rep]: ../../reports/Veyltrace%20v2%20SOTA%20root%20cause%20analysis.md
[va]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/verified_agents_local_llms.md
