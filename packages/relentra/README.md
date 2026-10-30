# veyltrace-relentra

Engine 8 of Veyltrace: a local-LLM investigator that reads the hypothesis slate and evidence cards and **proposes** extra candidates and predicate checks. It never decides; FaultLoom re-evaluates every check for every candidate and Causentra sets the verdict.

- Spec: [docs/engines/08-relentra.md](../../docs/engines/08-relentra.md)
- Modes: `brief` (default, one call plus at most one repair), `investigate` (tool loop, ablation), agent-only baseline (bench only)
- Output: `proposals.json`, `agent_trace.jsonl` (hash chain), cassette entries for replay
- Default model: Qwen3.5-9B Q4_K_M (Qwen3.5-4B fallback), GGUF SHA-256 pinned in `config/llm.yaml`

```sh
uv run veyltrace diagnose --dataset synth --case synth-01 --ai record   # needs a local model
uv run veyltrace diagnose --dataset synth --case synth-01 --ai replay   # from the cassette
uv run python scripts/check.py --package relentra
```

With `--ai off` this engine is skipped and writes nothing.
