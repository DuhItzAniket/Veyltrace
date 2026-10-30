# veyltrace-anomara (`veyltrace_anomara`)

Engine 3 of Veyltrace v2 (Observe lane). Anomara says, for every series, how far the incident window deviates from the baseline, in which direction and from when, and flags services that went silent.

- **Detectors**: `robust_z` (median with a scale floor of MAD, IQR/1.349, a per-family epsilon and 2% of |median|; persistent max; `log1p` compression), `nsigma` (RCAEval-comparable), `bocpd` (Bayesian online change-point onset), `silence`; optional `tsfm` plugin, off by default.
- **Onsets**: per-service internal and external onsets; incident onset `t_onset` = second-earliest external onset, clamped to `[t_alert − 60 s, t_alert + 300 s]`.
- **`detect_alert(telemetry)`**: first sustained entry-service SLO breach, used by core's alert step for the detected-alert protocol.

Spec: [docs/engines/03-anomara.md](../../docs/engines/03-anomara.md). Rules for agents: [AGENTS.md](AGENTS.md).

| | |
|---|---|
| Reads | `case_manifest`, `alert`, `signal_cube.{series,edges}`; `detect_alert`: `telemetry.{spans,metrics}` |
| Writes | `anomalies.parquet`, `onsets.json` |
| Config | `config/anomara.yaml` |

Once implemented (O-04):

```bash
uv run python scripts/check.py --package anomara
uv run veyltrace diagnose --dataset synth --case synth-01 --ai off
```
