# AGENTS.md — packages/causatrix (`veyltrace_causatrix`)

Adds to the root [AGENTS.md](../../AGENTS.md); never overrides it.

**Lane:** Reason. **Spec:** [docs/engines/07-causatrix.md](../../docs/engines/07-causatrix.md). **Master:** [02 §6.7](../../docs/02-architecture.md). **Contract:** [03 §8](../../docs/03-contracts.md).

## Purpose
Engine 7. Six deterministic rankers (`prism_m`, `baro_rs`, `nsigma`, `cp_sbfl`, `change_prox`, `graph_walk`), gated RRF (k = 60, weights 1.0), mode / fault-class / indicator rules, and the top-K slate.

## Inputs / outputs
In: `evidence` (engine atoms only), `graph.nodes`, `graph.edges`, `case_manifest`. Out: `slate.json` only.

## Package rules
- Shared surface: the pure functions `rank()` and `classify()` are called by Causentra (trial T9, proposed candidates). Keep them pure and side-effect free; behaviour changes need an issue noting the Causentra impact.
- Rankers are registered under entry point group `veyltrace.rankers`; no registry dict.
- No learned or tuned weights. Fusion weights stay 1.0 a priori; a new fusion rule is an ablation arm, never the default, unless decided on RE1/synth before `prereg-v1` ([04 §5.3](../../docs/04-evaluation-protocol.md)).
- Ranks are competition ranks on scores rounded to 1e-12; ties never depend on service names inside a ranker.
- A ranker abstains when its channel is missing or its scores are constant; it never votes with zeros.
- Every threshold is a key in `config/causatrix.yaml` with its source or "a priori".
- Determinism: sorted iteration, `math.fsum`, fixed PageRank iteration count, no BLAS products on output paths.
- Allowed imports: `veyltrace_core`, `veyltrace_contracts`, `veyltrace_faultloom` (atom-kind constants, `atom_sources`), `numpy`, `pyarrow`, `networkx`, stdlib. Banned: `veyltrace_llm`, LLM/HTTP clients, `socket`, `torch`, `transformers`, `pandas`.

## Commands
| Task | Command |
|---|---|
| Check | `uv run python scripts/check.py --package causatrix` |
| Determinism | `uv run python scripts/check.py --determinism` |
| Refresh fixtures | `uv run python scripts/check.py --package causatrix --update-golden` |

## Never (this package)
1. Never read Observe tables, `proposals`, `claim_check` atoms, answer keys or anything under `bench/` or `lab/`.
2. Never decide or abstain on the case; that is Causentra's job.
3. Never quote a published PRISM/BARO number as if our ranker produced it.
4. Never drop a service from `all_scores`; every service in the universe gets a fused score.
