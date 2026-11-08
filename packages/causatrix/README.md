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

## Stub (R-00)

Until R-09 lands, `api.run` calls `veyltrace_causatrix.stub.run_stub`, which proves the wiring of pipeline step 6 without making any ranking claim.

- **Reads** (07 §2.1, through `ctx` only): `case_manifest` (`case_id`, `services`), `evidence` (engine atoms: `atom_id`, `candidate`, `component`, `kind`, `args_json`, `value`, `origin`), `graph.nodes` (`node`, `kind`) and `graph.edges` (`src`, `dst`, `weight`, `provenance`). It also reads `thresholds.anomaly_z` and `universe.include_external` from `config/core.yaml`, plus `slate.k`, `rankers.enabled`, `fusion.method`, `rrf.k`, `rrf.weights` and `indicator_map` from `config/causatrix.yaml`. If `evidence` or `graph.nodes` is absent, the step fails (07 §6). If `graph.edges` is absent, the stub treats the graph as having no edges.
- **Writes** `slate.json` through `ctx.write`. The output is schema-checked, its `x-sort` orders are checked, and it is stamped.
  - `all_scores` lists every service of U (06 §2.1: manifest services plus non-external graph nodes, external nodes only with `include_external`), each with `fused_score = 0.0`, in A→Z order.
  - `candidates` holds the first `slate.k` services of U in the 07 §3.1 step-5 tie-break order. With every F equal, that order is: internal anomaly (I ≥ k_anom) first, then earliest `onset_precedence{self}`, then name.
  - Each candidate carries:
    - `fused_score = 0.0`;
    - `ranker_ranks` and `ranker_scores`, set to null for every enabled ranker;
    - `mode` and `fault_class` from the fallback rule R6 (`unknown`/`unknown`);
    - the indicator of family `other` (`unknown`, via `indicator_map`);
    - `component` from topI, else topE (null when absent or equal to the service).
  - `rankers_active = []`.
  - `fusion = {method, k: rrf.k (null if the method is not rrf), weights: rrf.weights for every enabled ranker}`.
- **Why list U instead of an empty slate.** The spec's no-vote rule asks for `candidates = []` in two places: 07 §3.1 (last paragraph, "If no ranker votes, candidates = []") and 07 §6 ("no anomaly atoms at all: every ranker abstains; empty slate"). The stub lists U anyway, as the lead's R-00 scope prefers:
  - The 03 §8 contract allows it honestly ("candidates may be empty", not "must"). Every value is either a contract enum fallback (`unknown`) or the arithmetic of an empty vote: an RRF sum over no rankers is 0.0, and an abstaining ranker is null. No score, enum value or field is invented.
  - Downstream stubs and fixtures (Relentra, Causentra `ranked`, Causivra) get the case's real candidate names. Causentra must keep every slate candidate in `ranked`, so a non-empty slate exercises that path.
  - R-09 must restore the 07 §3.1 and §6 rule for the real "no ranker voted" case, or the lead must amend both rows (or record an ADR) to match the stub.
- **The order is not a ranking.** With no atoms (every synth fixture on R-00), every F, I(s) and onset is equal, so the step-5 tie-break reduces to the service name. `candidates` is then the first `slate.k` services of U A→Z, ranks 1..K are alphabetical, and services after the first K by name are dropped from the slate. On synth, U has six services and `recommend` is always left out, although 09 §7 names it a plausible synth-02 leader. Every consumer must treat a slate with `rankers_active = []` as **unranked** ([04 §7](../../docs/04-evaluation-protocol.md) "Unranked runs"; in 04 an abstention is a Causentra status): bench (R-04) must not score its order (or Causentra's `ranked`/`ranks_rcaeval` built on it) as AC@k or Retrieval@K, and Relentra must not present ranks 1..K as a ranking.
- **Deliberately not done:**
  - no ranker is implemented or registered under `veyltrace.rankers`;
  - no fusion and no gating are computed;
  - no rule R1–R5 and no indicator branch 1–3 is evaluated;
  - the public `rank()` and `classify()` functions do not exist yet;
  - no `graph_walk` runs.
  - The stub reads only the keys listed above. The other 07 §4 keys (`rrf.gate`, `abstain_on_constant`, `prism_m.*`, `graph_walk.*`, `mode.*`) are declared in `config/causatrix.yaml` so that ablation overrides can already name them.
- **Replaced by** R-09: the six rankers, gated RRF, the rule table, `rank()` and `classify()`. R-09 also regenerates the golden fixtures with `check.py --package causatrix --update-golden`.

```bash
uv run python scripts/check.py --package causatrix
```
