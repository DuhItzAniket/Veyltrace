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

## v1 (R-09)

- **Modules:** `config` (`CausatrixConfig`, every 07 §4 key validated), `views` (`EvidenceView`, `GraphView`: U and the 07 §2.1 quantities), `ranking` (`Ranker`, `Vote`, competition ranks, gating), `rankers/<name>` (one module per ranker, each declared under `veyltrace.rankers`), `rank` (`rank()` → `RankResult`: gated RRF and the step-5 order), `classify` (`classify()` → `Classification`: rules R1–R6 and the indicator), `slate` and `api`.
- **Ranker lookup.** Engines may not import `importlib.metadata` (02 §9), so `ranking.load_ranker(name)` imports `veyltrace_causatrix.rankers.<name>` and takes its `RANKER`; `tests/test_rankers.py` pins every entry point to exactly that object.
- **No vote, no slate.** When every enabled ranker abstains, `candidates = []`, `rankers_active = []`, every `all_scores` entry is 0.0, and the step's notes say `no ranker voted: empty slate` (07 §3.1, §6). This replaces the R-00 stub's choice to list U anyway (removed in #115). While Anomara is a stub the synth evidence is empty, so every synth slate is empty; `fixtures/handmade/` pins the ranking instead (the 07 §3.7 example, a no-vote case, and a change/silence/dependency/code case).
- **Each ranker alone** (bench `causatrix:<ranker>`, 07 §9): override `causatrix.rankers.enabled=[<ranker>]`; the slate then follows that ranker's ranks, ties broken by the step-5 key. If it abstains on a case, the slate is empty.
- **Not yet:** `fusion.method` `combsum_minmax` and `borda` are R-16 ablations and raise `ConfigError`; no `availability` rule (07 §11 Q8); synth-03's exception keeps the literal `logs` indicator (07 §11 Q9).

```bash
uv run python scripts/check.py --package causatrix
```
