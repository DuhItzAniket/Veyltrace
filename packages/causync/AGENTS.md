# AGENTS.md — packages/causync (`veyltrace_causync`)

Adds to the root [AGENTS.md](../../AGENTS.md); never overrides it.

**Lane:** Observe. **Spec:** [docs/engines/04-causync.md](../../docs/engines/04-causync.md). **Master:** [02 §6.4](../../docs/02-architecture.md). **Contract:** [03 §5](../../docs/03-contracts.md).

## Purpose
Engine 4, pipeline step 4 (parallel with Causalith). Estimates clock offsets between sources (trace parent/child pairs, log–span joins, co-movement) and the comparison tolerance; builds the change timeline from `telemetry.events`; scores change-to-onset proximity (`exp(−Δt/τ)`, τ = 300 s) and changed-vs-peer contrast.

## Inputs / outputs
In: `case_manifest`, `alert`, `telemetry.{events,spans,logs}`, `signal_cube.series`, `anomalies`, `onsets`. Out: `alignment.json`, `changes.parquet`.

## Package rules
- Decoys: score a change only from its time, entity, kind and anomalies. `source_system` and `actor` must never enter a rule or score (property test relabels them).
- `k8s_event` and `other` are symptoms, not changes.
- No events (all RCAEval cases) → zero-row `changes`; that is the expected abstention, not an error.
- `peer_contrast` is in raw robust-z units (FaultLoom relies on this).
- Offsets are published only where the data shows skew (spec §3.2 gate); otherwise 0.
- `latest_before_onset` uses a DuckDB ASOF join; equal timestamps are all flagged.
- Determinism: fixed BFS and tie orders, exact medians, DuckDB `threads = 1`, no RNG.
- Allowed imports: `veyltrace_core`, `veyltrace_contracts`, `duckdb`, `pyarrow`, `numpy`, `scipy`, stdlib. Banned: `veyltrace_llm`, LLM/HTTP clients, `socket`, `torch`, `transformers`.
- The RCAEval-C generator (O-13) is bench code in `bench/decoys/` (also Observe-owned). This package never imports it and it never imports this package's internals.

## Commands
| Task | Command |
|---|---|
| Check | `uv run python scripts/check.py --package causync` |
| Determinism | `uv run python scripts/check.py --determinism` |
| Lanes | `uv run scripts/check_lanes.py --lane observe` |
| Refresh fixtures | `uv run python scripts/check.py --package causync --update-golden` |
| Run on synth | `uv run veyltrace diagnose --dataset synth --case synth-04 --ai off` |

## Never (this package)
1. Never read answer keys, `decoy_changes_json`, `case_manifest.t_alert_hint_ns`, or anything under `bench/`/`lab/`.
2. Never rewrite telemetry timestamps; publish offsets instead.
3. Never tune `changes.tau_s` on test data; sensitivity runs are reported, not used to pick a value.
