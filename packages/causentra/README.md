# veyltrace-causentra (`veyltrace_causentra`)

Engine 9 of Veyltrace v2 (Reason lane): the deterministic verifier. Statistical rankers and the LLM investigator only propose; Causentra decides.

For every candidate in the decision pool (slate ∪ proposed candidates in `graph.nodes` with at least one supporting claim that code found true) it runs ten fixed trials (origin, precedence, propagation, silence, latency accounting, change alignment, peer contrast, intervention, leave-one-source-out, claim checks), computes the verified score

`V(c) = S0(c) × Π trial_factor(c) × (1 + clip(Σ_p w_p · polarity_p · holds_p(c), −0.3, +0.3))`,

builds a split-conformal candidate set (α = 0.10), and returns `CONFIRMED`, `LIKELY`, `INCONCLUSIVE` (with asks) or `NO_FAULT`, sealed by `verdict_hash` so replay can check it.

Spec: [docs/engines/09-causentra.md](../../docs/engines/09-causentra.md). Rules for agents: [AGENTS.md](AGENTS.md).

| | |
|---|---|
| Reads | `slate`, `evidence`, `proposals` (AI on), `graph.*`, `onsets`, `alignment`, `case_manifest`; calibration through `ctx.config.calibration` (from `config/calibration/<family>.json`) |
| Writes | `verdict.json` |
| Config | `config/causentra.yaml` (trial factors, margins, predicate weights, α, β) |

```bash
uv run python scripts/check.py --package causentra
uv run veyltrace diagnose --dataset synth --case synth-05 --ai off   # expect NO_FAULT
```
