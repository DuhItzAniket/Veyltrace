# veyltrace-signalyth (`veyltrace_signalyth`)

Engine 2 of Veyltrace v2 (Observe lane). Signalyth turns canonical telemetry into typed signals that the rest of the pipeline scores and cites.

- **Series**: metrics on their native grid (counters → per-second rates, units normalised); per-service trace latency p50/p99, error rate, request rate and self-time in 10 s buckets; log rate, error-line rate and per-template counts in 10 s buckets. Each series is tagged with a `family` and an `internal` / `external` / `context` klass.
- **Edges**: caller → callee call counts, error rate, caller/callee latency and gap per window.
- **Critical path**: CRISP-style last-finishing-child walk per trace; per-service critical-path self-time and share, plus slow-trace counts and shares (the spectrum for Causatrix's `cp_sbfl`).
- **Templates**: Drain3 with fixed order rules, so two laptops produce the same templates.

Spec: [docs/engines/02-signalyth.md](../../docs/engines/02-signalyth.md). Rules for agents: [AGENTS.md](AGENTS.md).

| | |
|---|---|
| Reads | `case_manifest`, `alert`, `telemetry.{metrics,logs,spans}` |
| Writes | `signal_cube/{series,edges,templates,critical_path}.parquet` |
| Config | `config/signalyth.yaml` |

Once implemented (O-02, O-03):

```bash
uv run python scripts/check.py --package signalyth
uv run veyltrace diagnose --dataset synth --case synth-01 --ai off
```
