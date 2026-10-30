# veyltrace-faultloom (`veyltrace_faultloom`)

Engine 6 of Veyltrace v2 (Reason lane). FaultLoom turns the Observe tables into **evidence atoms**: one row per (candidate service, kind, defining arguments) with a value, unit, window and references to the source rows. It is the only place evidence for the decision is created.

- **Engine pass** (pipeline step 5): every engine atom kind in [03 §7](../../docs/03-contracts.md) (all but `claim_check` and `intervention`) for every service.
- **Claim pass** (step 8): every library predicate that Relentra cited is evaluated for every candidate in the claim-pass pool (slate ∪ proposed candidates), so the LLM can request checks but cannot favour a candidate; `intervention` atoms (Causalith's restricted CI test, trial T8) are added for decision-pool candidates, also when `ai.mode = off`.
- **Predicate library**: 10 predicates with fixed signatures and polarity, registered under entry point group `veyltrace.predicates`.
- **`evidence_cards(slate, k, *, ctx)`**: the deterministic compact view Relentra's `brief` mode puts in its prompt.

Spec: [docs/engines/06-faultloom.md](../../docs/engines/06-faultloom.md). Rules for agents: [AGENTS.md](AGENTS.md).

| | |
|---|---|
| Reads | `case_manifest`, `alert`, `signal_cube.*`, `anomalies`, `onsets`, `alignment`, `changes`, `graph.*`; claim pass: `slate`, `proposals` |
| Writes | `evidence.parquet` |
| Config | `config/faultloom.yaml` (+ shared keys in `config/core.yaml`) |

```bash
uv run python scripts/check.py --package faultloom
uv run veyltrace diagnose --dataset synth --case synth-01 --ai off
```
