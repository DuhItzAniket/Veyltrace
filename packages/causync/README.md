# veyltrace-causync (`veyltrace_causync`)

Engine 4 of Veyltrace v2 (Observe lane). Causync puts the telemetry sources on one clock and turns change events (deploys, config and flag changes, scaling, deliberate restarts, commits) into change evidence.

- **Alignment**: per-service trace offsets from client/server span pairs (NTP-style estimate), log offsets from log–span joins, co-movement fallback; `tolerance_ns` = coarsest source step.
- **Changes**: scope, proximity to the entity's onset, latest-before-onset flag (ASOF join), changed-vs-peer replica contrast.
- **Decoys**: every change is treated the same; bench's RCAEval-C decoys (O-13) test that the channel is not gullible.

Spec: [docs/engines/04-causync.md](../../docs/engines/04-causync.md). Rules for agents: [AGENTS.md](AGENTS.md).

| | |
|---|---|
| Reads | `case_manifest`, `alert`, `telemetry.{events,spans,logs}`, `signal_cube.series`, `anomalies`, `onsets` |
| Writes | `alignment.json`, `changes.parquet` |
| Config | `config/causync.yaml` |

Once implemented (O-06):

```bash
uv run python scripts/check.py --package causync
uv run veyltrace diagnose --dataset synth --case synth-04 --ai off
```
