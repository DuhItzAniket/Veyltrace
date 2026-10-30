# AGENTS.md — packages/causentra (`veyltrace_causentra`)

Adds to the root [AGENTS.md](../../AGENTS.md); never overrides it.

**Lane:** Reason. **Spec:** [docs/engines/09-causentra.md](../../docs/engines/09-causentra.md). **Master:** [02 §6.9](../../docs/02-architecture.md). **Contract:** [03 §10](../../docs/03-contracts.md) (reads calibration, 03 §12.1).

## Purpose
Engine 9, the only engine that sets the verdict. Trials T1–T10, the fixed decision function, the conformal set, `NO_FAULT` / `INCONCLUSIVE`, asks, proposal decisions, `verdict_hash`.

## Inputs / outputs
In: `slate`, `evidence` (incl. `claim_check` and `intervention` atoms), `proposals` (optional), `graph.*`, `onsets`, `alignment`, `case_manifest`, and calibration via `ctx.config.calibration`. Out: `verdict.json` only.

## Package rules
- The decision function, trial factors, margins and α are exactly [02 §6.9](../../docs/02-architecture.md); any change is an ADR on 02 first.
- Calibration (q̂, τ_nf) arrives only through `ctx.config` from `config/calibration/<family>.json`; never open files yourself.
- Trials are registered under entry point group `veyltrace.trials`.
- Proposals are data: decisions use only `claim_check` atoms and validation results, never `rationale`, `asks`, `cites` or the proposal's `fault_class`.
- Verdict must be invariant to proposal and claim order (property test).
- Round V, nonconformity and margin to 9 decimals before comparing.
- Allowed imports: `veyltrace_core`, `veyltrace_contracts`, `veyltrace_faultloom` (predicates, `validate`, `atom_sources`), `veyltrace_causatrix` (`rank`, `classify`), `numpy`, `pyarrow`, `networkx`, stdlib. Banned: `veyltrace_llm`, LLM/HTTP clients, `socket`, `torch`, `transformers`, `pandas`.

## Commands
| Task | Command |
|---|---|
| Check | `uv run python scripts/check.py --package causentra` |
| Determinism | `uv run python scripts/check.py --determinism` |
| Replay a verdict | `uv run veyltrace replay runs/<…>/receipt.json` |

## Never (this package)
1. Never read anything under `bench/` or `lab/` (answer keys, calibration splits); the isolation test scans for these paths.
2. Never fit calibration or tune a threshold here; bench fits on calibration splits only.
3. Never let an LLM output, model confidence or LLM judge influence the verdict except through code-evaluated predicates.
4. Never apply T10 to slate-origin candidates: AI-on vs AI-off differences must come only from verified evidence.
5. Never drop a slate candidate from `ranked`.
