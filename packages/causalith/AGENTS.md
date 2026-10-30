# AGENTS.md — packages/causalith (`veyltrace_causalith`)

Adds to the root [AGENTS.md](../../AGENTS.md); never overrides it.

**Lane:** Observe. **Spec:** [docs/engines/05-causalith.md](../../docs/engines/05-causalith.md). **Master:** [02 §6.5, §6.9](../../docs/02-architecture.md). **Contract:** [03 §6](../../docs/03-contracts.md).

## Purpose
Engine 5, pipeline step 4 (parallel with Causync). Builds the dependency graph from trace calls, topology hints in events and log mentions, each edge with provenance; computes k-best propagation paths to the entry services for every node (02 §6.5 requires every anomalous service). Exports two pure library APIs: `entry.entry_services()` (shared entry rule) and `ci.intervention_test()` (restricted CI test for trial T8).

## Inputs / outputs
In: `case_manifest`, `alert`, `signal_cube.{edges,series}`, `telemetry.{events,logs,spans}`, `anomalies`. Out: `graph/{nodes,edges,paths}.parquet`.

## Package rules
- Shared APIs: `entry` is called by Anomara (`run()` and `detect_alert`, so also by core); `ci` by FaultLoom's claim pass (evidence kind `intervention`, 03 §7), which Causentra's T8 reads. Keep signatures stable (`CI_API_VERSION`); changes need an issue tagging the consuming lane.
- When `alert.detector` is set, copy its `entry_services`; never recompute them.
- Log mentions: a service named `^[a-z]+$` counts only in host:port, URL or gRPC-package form. Logs and topology never create nodes.
- No full causal discovery (02 §11): no PC/FCI/PCMCI/NOTEARS, no graph learning over all series.
- Determinism: insert nodes and arcs in sorted order; resolve path ties explicitly; CI test in float64 with fixed parent order; no RNG.
- Allowed imports: `veyltrace_core`, `veyltrace_contracts`, `networkx`, `numpy`, `scipy`, `pyarrow`, `duckdb`, stdlib. Banned: `veyltrace_llm`, LLM/HTTP clients, `socket`, `torch`, `transformers`, and `veyltrace_anomara` (circular: Anomara imports `entry`).

## Commands
| Task | Command |
|---|---|
| Check | `uv run python scripts/check.py --package causalith` |
| Determinism | `uv run python scripts/check.py --determinism` |
| Lanes | `uv run scripts/check_lanes.py --lane observe` |
| Refresh fixtures | `uv run python scripts/check.py --package causalith --update-golden` |
| Run on synth | `uv run veyltrace diagnose --dataset synth --case synth-01 --ai off` |

## Never (this package)
1. Never read answer keys, `case_manifest.t_alert_hint_ns`, or anything under `bench/`/`lab/`.
2. Never compute paths only for slate candidates: the slate does not exist yet at step 4.
3. Never read files, the clock or RNG inside `entry` or `ci` functions.
4. Never set `anomalous` on an edge without trace data: it stays null (03 §6.2).
