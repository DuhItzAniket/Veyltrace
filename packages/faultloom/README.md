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

## Stub (R-00)

Until R-06 lands, `api.run` dispatches on `ctx.phase` to the package's own stub (`veyltrace_faultloom.stub`). It replaces core's R-02 bootstrap stub.

- **Reads.** Both passes read every input of [06 §2.1](../../docs/engines/06-faultloom.md) through `ctx`, using the exact columns the spec names (`veyltrace_faultloom.inputs`): `case_manifest`, `alert`, `signal_cube.*`, `anomalies`, `onsets`, `alignment`, `changes` and `graph.*`. The claim pass also reads `evidence` (the main pass), `slate` and `proposals`. From these inputs the stub derives the shared values of 06 §2.1:
  - the universe U: manifest services ∪ non-external graph nodes, with external nodes only if `core.universe.include_external`;
  - `tol_ns`;
  - W_base, W_inc and W_score (`window.score_ms`, clamped to W_inc);
  - the claim-pass pool P: slate ∪ proposed services that are graph nodes.
- **Missing inputs (06 §6).**
  - A missing `case_manifest`, `alert`, `anomalies`, `onsets` or `graph.nodes` gives `status = failed`. In the claim pass, so does a missing `evidence` or `slate`.
  - A missing optional table counts as zero rows and adds a note.
  - A missing `alignment` sets `tol_ns = alignment.missing_tolerance_ns` (15 s) and adds a note.
  - An absent `proposals.json` (AI off) means there are no claims. A schema-invalid one means claims are skipped and the status is `degraded`.
- **Writes.** It writes `evidence` only, through the contract writer.
  - Main pass: an empty, schema-valid table.
  - Claim pass: the main-pass evidence read back and rewritten unchanged, so the file is byte-identical.
  - Row counts, |U| and |P| go into `EngineResult.metrics`. Every result carries the note `stub: R-00 …`. It starts with `cli.STUB_MARK`, so `diagnose` prints its "placeholder outputs" warning for a run with FaultLoom's stub.
- **Deliberately not done.**
  - No atom of any kind. Every kind needs FaultLoom's own computation over Observe evidence. A `silence = 0.0` or `critical_path_share = 0` atom built from placeholder upstream data would look like a healthy measurement, and 06 §6 says absence is "no atom".
  - No claim is evaluated. If proposals hold claims, the claim pass is `degraded` with a note, so a run with real proposals is never reported as checked.
  - No `intervention` atoms, no `evidence_cards`, no predicate library (`veyltrace.predicates`). Nothing reads `telemetry.*`, answer keys or case names.
- **Replaced by.**
  - R-06: `internal_anomaly`, `external_anomaly`, stable `atom_id`.
  - R-08: all other kinds, the predicate library with polarity, the symmetric claim pass and `evidence_cards`.
  - R-12: T8 `intervention` atoms.

  `config/faultloom.yaml` already declares every 06 §4 key, so ablation overrides can name them. The stub reads `window.score_ms` and `alignment.missing_tolerance_ns`.
