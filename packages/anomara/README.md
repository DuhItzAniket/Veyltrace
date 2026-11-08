# veyltrace-anomara (`veyltrace_anomara`)

Engine 3 of Veyltrace v2 (Observe lane). Anomara says, for every series, how far the incident window deviates from the baseline, in which direction and from when, and flags services that went silent.

- **Detectors**: `robust_z` (median with a scale floor of MAD, IQR/1.349, a per-family epsilon and 2% of |median|; persistent max; `log1p` compression), `nsigma` (RCAEval-comparable), `bocpd` (Bayesian online change-point onset), `silence`; optional `tsfm` plugin, off by default (O-10, not built).
- **Onsets**: per-service internal and external onsets; incident onset `t_onset` = second-earliest external onset, clamped to `[t_alert − 60 s, t_alert + 300 s]`.
- **`detect_alert(telemetry)`**: first sustained entry-service SLO breach, used by core's alert step for the detected-alert protocol.

Spec: [docs/engines/03-anomara.md](../../docs/engines/03-anomara.md). Rules for agents: [AGENTS.md](AGENTS.md).

| | |
|---|---|
| Reads | `case_manifest`, `alert`, `signal_cube.{series,edges}`; `detect_alert`: `telemetry.{spans,metrics}` |
| Writes | `anomalies.parquet`, `onsets.json` |
| Config | `config/anomara.yaml` (and `causalith.entry.*` for the shared entry rule) |

## Modules

| Module | What | Spec |
|---|---|---|
| `series` | per-series arrays (`split_series`), effective step `g`, epoch-aligned grid series | 03-anomara §3.1 |
| `robust` | `robust_z` (scale floor, persistence) and `nsigma` | §3.2–3.3 |
| `bocpd` | BOCPD run-length posterior, stacked per grid, onset `t − r̂·g` | §3.4 |
| `silence` | zero-silence and absence-silence | §3.5 |
| `onsets` | onset of record, per-service onsets and `silent`, `t_onset` | §3.6–3.7 |
| `settings` | typed, validated view of `config/anomara.yaml` | §4 |
| `api` | `run(ctx)`: one `anomalies` row per series and detector, `onsets.json` | §2, §6 |

On synth, `signal_cube` stays empty until Signalyth (O-02) lands, so `anomalies` has no rows and `onsets` falls back to `t_alert`. The hand-made golden case `fixtures/handmade/anomara-run/` pins the detectors and onsets on a small synth-shaped system; refresh it after review with `VEYLTRACE_UPDATE_HANDMADE=1 uv run pytest packages/anomara/tests/test_handmade.py`.

```bash
uv run python scripts/check.py --package anomara
uv run veyltrace diagnose --dataset synth --case synth-01 --ai off
```
