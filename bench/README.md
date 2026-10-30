# bench (`veyltrace_bench`)

The evaluation harness of Veyltrace v2. It implements the pre-registered protocol in [docs/04-evaluation-protocol.md](../docs/04-evaluation-protocol.md): answer keys, baselines (chance, prior-only, RCAEval's N-Sigma / BARO and others in an isolated venv, SimpleRCA-style alert count, PRISM re-implementation), metrics (AC@k, Avg@5, Retrieval@K, Rerank@1, coverage, risk–coverage, `NO_FAULT` rates, cost, replay), calibration fitting, the experiment runner and the result tables.

| Path | Owner | Content |
|---|---|---|
| `bench/experiments/*.yaml` | Reason | experiment configs ([04 §9](../docs/04-evaluation-protocol.md)) |
| `bench/results/<id>/` | Reason | `per_case.csv` (committed), `summary.json`, `manifest.json` |
| `bench/results/tables/` | Reason | generated Markdown tables for the paper |
| `bench/decoys/` | **Observe** (O-13) | RCAEval-C decoy-change generator |
| `bench/stats/` | **Observe** (O-14) | cluster bootstrap, sign-flip permutation, McNemar, Holm |
| `config/calibration/<family>.json` | Reason (written by bench) | fitted q̂ and τ_nf, read by Causentra through config |

Rules for agents: [AGENTS.md](AGENTS.md).

```bash
uv run veyltrace bench run bench/experiments/synth-smoke.yaml
```
