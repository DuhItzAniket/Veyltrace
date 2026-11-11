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

## v1 (R-08)

`api.run` dispatches on `ctx.phase` to `veyltrace_faultloom.passes`. Every 06 §3.4 kind except `intervention` (R-12) is computed; nothing reads `telemetry.*`, answer keys or case names.

- **Input view** (`inputs.py`): every 06 §2.1 input read through `ctx`, plus the shared values:
  - the universe U, `tol_ns`, the windows, `k_anom`;
  - per-service onsets aligned by Causync's offsets;
  - the component map and the series signals.

  Rows without an id are cited as `<table>#<12 hex>` over the whole row (`row_ref`, 06 §3.3). Missing inputs follow 06 §6.
- **Engine pass** (`passes.run_main`):
  - kinds: anomaly (`atoms.py`), silence (`onset.py`), onset and propagation (`graph.py`), change, peer and log (`change.py`), and trace (`trace.py`);
  - every engine row is built by `atoms.engine_atom`; `atoms.disabled` (06 §9) drops kinds; an `atom_id` collision is a hard error;
  - metrics carry `atoms.<kind>` for all 15 kinds.
- **Predicate library** (`predicates.py`, entry points `veyltrace.predicates`): `LIBRARY` holds the 10 predicates of 03 §7 with fixed params, polarity, window and unit. `Predicate.evaluate(ClaimView, subject, args)` reads the input view and the main-pass engine atoms. Not evaluable is `holds = None`.
- **Validation** (`validation.py`): the pure `validate(name, args, domain) -> ValidClaim | Rejection` (`unknown_predicate`, `unknown_entity`, `bad_args`). `read_domain(ctx)` gives Causentra and Relentra the case's graph nodes, series signals and the `predicates.<name>.<param>` ranges of `config/faultloom.yaml`.
- **Claim pass** (`passes.run_claim_pass`, `claims.py`):
  - claims come from proposals with status `complete` or `budget_exhausted`, sorted by (`proposal_id`, `claim_id`);
  - each claim is validated and duplicates are removed;
  - every distinct claim runs for every candidate of the claim-pass pool (slate ∪ proposed graph nodes);
  - the `claim_check` atoms are appended to the main evidence, which is read back unchanged;
  - metrics: `claims.seen`, `claims.valid`, `claims.rejected.<reason>`, `pool`;
  - every result notes that `intervention` atoms (T8) are R-12.
- **`atom_sources(atom)`** (`sources.py`): the sources of the series in `refs` plus the kind's tag (06 §3.3), for Causentra's T9.
- **Fixtures.**
  - Synth Observe outputs are still stubs, so the synth goldens hold only `silence = 0` atoms (from the stub onsets).
  - Every kind and predicate is pinned by the synth-shaped hand-made case `fixtures/handmade/cpu-hog/`. Its `inputs.json` is written through `io.write` by the tests, and `evidence.main.txt` is the expected canonical evidence. It carries the 06 §3.8 worked numbers.
  - Refresh: `VEYLTRACE_UPDATE_HANDMADE=1 uv run pytest packages/faultloom/tests/test_handmade.py`.
- **Spec readings** made for R-08 are in 06 §11 Q13–Q17. `evidence_cards` (06 §3.7) is R-08h; `intervention` atoms are R-12.
