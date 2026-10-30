# AGENTS.md — packages/faultloom (`veyltrace_faultloom`)

Adds to the root [AGENTS.md](../../AGENTS.md); never overrides it.

**Lane:** Reason. **Spec:** [docs/engines/06-faultloom.md](../../docs/engines/06-faultloom.md). **Master:** [02 §6.6](../../docs/02-architecture.md). **Contract:** [03 §7](../../docs/03-contracts.md).

## Purpose
Engine 6. Turns Observe outputs into evidence atoms (pipeline step 5) and, in the claim pass (step 8), evaluates Relentra's claims for every claim-pass pool candidate and writes `intervention` atoms (T8) for decision-pool candidates. Owns the predicate library and `evidence_cards()`.

## Inputs / outputs
In: `case_manifest`, `alert`, `signal_cube.*`, `anomalies`, `onsets`, `alignment`, `changes`, `graph.*`; claim pass adds `slate`, `proposals`. Out: `evidence.parquet` only.

## Package rules
- Shared surfaces: predicates (entry points `veyltrace.predicates`), `validate()`, `atom_sources()` (used by Causentra) and `evidence_cards()` (used by Relentra, Explain lane). Changing their behaviour needs an issue that tags the consuming lane.
- Atom kinds are the closed list in 03 §7. A new kind or predicate is a Contract Change Request, not a code change.
- Predicate polarity must equal the 03 §7 table (unit test). Weights are Causentra's config, never read here.
- Symmetry: a check's result for a candidate may depend only on the data and the candidate, never on which proposal asked or the proposal's order.
- Absence is "no atom" or `holds = null`, never a 0 that looks healthy.
- Determinism: sorted iteration, `math.fsum`, no BLAS products on output paths.
- Allowed imports: `veyltrace_core`, `veyltrace_contracts`, `numpy`, `pyarrow`, `duckdb`, `networkx`, stdlib; `veyltrace_causalith` only for its restricted CI API (`intervention` atoms). Banned: `veyltrace_llm`, LLM/HTTP clients, `socket`, `torch`, `transformers`, `pandas`.

## Commands
| Task | Command |
|---|---|
| Check | `uv run python scripts/check.py --package faultloom` |
| Determinism | `uv run python scripts/check.py --determinism` |
| Refresh fixtures | `uv run python scripts/check.py --package faultloom --update-golden` |
| Run on synth | `uv run veyltrace diagnose --dataset synth --case synth-01 --ai off` |

## Never (this package)
1. Never read `telemetry.*`, answer keys, `inject_time` or folder names.
2. Never rank, score candidates against each other, or drop atoms for "unlikely" services.
3. Never read proposal `rationale`, `asks` or citations to decide anything.
4. Never import a tokenizer; token counts in cards are byte-based estimates.
5. Never write anything but `evidence` (cards are returned, not written).
