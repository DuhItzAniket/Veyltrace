# veyltrace-causatrix (`veyltrace_causatrix`)

Engine 7 of Veyltrace v2 (Reason lane). Causatrix ranks every service in the case with six deterministic rankers, fuses them with gated reciprocal rank fusion (RRF, k = 60, all weights 1.0), classifies each top candidate's mode, fault class and RCAEval indicator, and writes the **slate**: the top-K candidates (default 5) plus a fused score for every service.

| Ranker | Score |
|---|---|
| `prism_m` | M = I + E − ln(1 + I + E) over internal (I) and external (E) robust z |
| `baro_rs` | max robust-scaled deviation (two-sided) |
| `nsigma` | max N-sigma deviation |
| `cp_sbfl` | critical-path-weighted Ochiai spectrum (traces only) |
| `change_prox` | change proximity × anomaly presence (events only) |
| `graph_walk` | personalised PageRank walking from symptoms to the services they call |

A ranker abstains when its channel is missing (no traces → `cp_sbfl` abstains) or its scores carry no information. Each ranker is also reported alone as a baseline.

Spec: [docs/engines/07-causatrix.md](../../docs/engines/07-causatrix.md). Rules for agents: [AGENTS.md](AGENTS.md).

| | |
|---|---|
| Reads | `evidence` (engine atoms), `graph.nodes`, `graph.edges`, `case_manifest` |
| Writes | `slate.json` |
| Public functions | `rank()`, `classify()` (used by Causentra) |
| Config | `config/causatrix.yaml` |

```bash
uv run python scripts/check.py --package causatrix
```
