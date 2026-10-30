# AGENTS.md — packages/anomara (`veyltrace_anomara`)

Adds to the root [AGENTS.md](../../AGENTS.md); never overrides it.

**Lane:** Observe. **Spec:** [docs/engines/03-anomara.md](../../docs/engines/03-anomara.md). **Master:** [02 §5.1, §6.3](../../docs/02-architecture.md). **Contract:** [03 §4](../../docs/03-contracts.md).

## Purpose
Engine 3, pipeline step 3. Scores every series with `robust_z` (multi-part scale floor), `nsigma`, `bocpd` and `silence`; derives per-service onsets and `t_onset`. Also exports `detect_alert(telemetry)`, which core's alert step (step 1) calls under the detected-alert protocol.

## Inputs / outputs
`run()`: in `case_manifest`, `alert`, `signal_cube.{series,edges}`; out `anomalies.parquet`, `onsets.json`. `detect_alert()`: in `telemetry.{spans,metrics}`, `case_manifest`; returns `AlertDetection | None` to core (writes nothing).

## Package rules
- `detect_alert` is a cross-lane API: keep its signature stable; changes need the lead's approval.
- One `anomalies` row per series per enabled detector, even below threshold.
- `score_norm = log1p(score)` for `robust_z` (Causentra's `NO_FAULT` statistic relies on it).
- Entry services: copy `alert.detector.entry_services` when set, else call `veyltrace_causalith.entry.entry_services()`. Never write a second entry rule.
- Determinism: exact medians/quantiles; BOCPD in log space with one sequential time loop and no matrix products; no RNG; ties → earliest time.
- Allowed imports: `veyltrace_core`, `veyltrace_contracts`, `numpy`, `scipy`, `pyarrow`, `duckdb`, `veyltrace_causalith.entry`, stdlib. Banned: `veyltrace_llm`, LLM/HTTP clients, `socket`, `transformers`.
- `torch` and the TSFM model package only inside `veyltrace_anomara/tsfm/`, imported lazily when `tsfm.enabled` (off by default), CPU, offline, pinned weights (optional extra `tsfm`; cut-list item 1).

## Commands
| Task | Command |
|---|---|
| Check | `uv run python scripts/check.py --package anomara` |
| Determinism | `uv run python scripts/check.py --determinism` |
| Lanes | `uv run scripts/check_lanes.py --lane observe` |
| Refresh fixtures | `uv run python scripts/check.py --package anomara --update-golden` |
| Run on synth | `uv run veyltrace diagnose --dataset synth --case synth-01 --ai off` |

## Never (this package)
1. Never read `case_manifest.t_alert_hint_ns`, answer keys, or anything under `bench/`/`lab/`. Onset accuracy against injection times is measured in bench, not here.
2. Never treat a series that went silent as healthy.
3. Never tune a threshold on RE2, RE3, Nezha or VeylLab results.
4. Never import `torch` at module level or download model weights from engine code.
