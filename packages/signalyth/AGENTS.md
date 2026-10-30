# AGENTS.md — packages/signalyth (`veyltrace_signalyth`)

Adds to the root [AGENTS.md](../../AGENTS.md); never overrides it.

**Lane:** Observe. **Spec:** [docs/engines/02-signalyth.md](../../docs/engines/02-signalyth.md). **Master:** [02 §6.2](../../docs/02-architecture.md). **Contract:** [03 §3](../../docs/03-contracts.md).

## Purpose
Engine 2, pipeline step 2. Turns canonical telemetry into typed signals: per-series values tagged with `family` and `klass`, counter → rate conversion, trace series (latency, error rate, request rate, self-time), call edges, CRISP-style critical paths, and Drain3 log templates with log series.

## Inputs / outputs
In: `case_manifest`, `alert` (windows only), `telemetry.{metrics,logs,spans}`. Out: `signal_cube/{series,edges,templates,critical_path}.parquet`.

## Package rules
- `series`, template text and `template_id` must not depend on `alert.json`; only `edges`, template counts and `critical_path` do (test: move the windows, compare).
- The `family`/`klass` table in spec §3.2 and §3.6 is the single mapping; change it only with a spec edit in the same PR.
- Drain3: one fresh in-memory miner per service, services A→Z, distinct masked messages by (count desc, text asc), `sim_th = 0.4`, `depth = 4`. No persistence handler.
- Client-span gap time is never charged to a service's self-time.
- Count series are zero-filled; quantile series are not.
- Determinism: exact linear quantiles, DuckDB `threads = 1`, SHA-256-based trace caps (no RNG), sorted iteration.
- Allowed imports: `veyltrace_core`, `veyltrace_contracts`, `duckdb`, `pyarrow`, `numpy`, `drain3`, stdlib. Banned: `veyltrace_llm`, LLM/HTTP clients, `socket`, `torch`, `transformers`, Drain3 Redis/Kafka persistence modules.

## Commands
| Task | Command |
|---|---|
| Check | `uv run python scripts/check.py --package signalyth` |
| Determinism | `uv run python scripts/check.py --determinism` |
| Lanes | `uv run scripts/check_lanes.py --lane observe` |
| Refresh fixtures | `uv run python scripts/check.py --package signalyth --update-golden` |
| Run on synth | `uv run veyltrace diagnose --dataset synth --case synth-01 --ai off` |

## Never (this package)
1. Never read `telemetry.events`, `case_manifest.t_alert_hint_ns`, answer keys or anything under `bench/`/`lab/`.
2. Never resample metrics below their native step or forward-fill gaps.
3. Never use approximate quantiles or an LLM to refine templates (LLM refinement is an unscheduled ablation).
4. Never add a `signal` name containing `|`.
