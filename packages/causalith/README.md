# veyltrace-causalith (`veyltrace_causalith`)

Engine 5 of Veyltrace v2 (Observe lane). Causalith builds the service dependency graph from what the system shows and computes candidate propagation paths. It does not learn a causal graph from series; benchmarks show that does not pay off at this scale.

- **Graph**: nodes with kinds (`service`, `db`, `cache`, `queue`, `external`, `entry`); edges from traces, topology hints and log mentions, each with provenance, call share and an anomaly flag.
- **Paths**: for every node, up to 3 lowest-cost paths to an entry service, preferring anomalous edges and nodes.
- **`entry.entry_services()`**: the one entry-service rule, shared with Anomara and core's alert step.
- **`ci.intervention_test()`**: IDI-style residual test (fit on baseline, judge the incident) on at most 5 candidate neighbourhoods, called by FaultLoom's claim pass (`intervention` atoms) for trial T8.

Spec: [docs/engines/05-causalith.md](../../docs/engines/05-causalith.md). Rules for agents: [AGENTS.md](AGENTS.md).

| | |
|---|---|
| Reads | `case_manifest`, `alert`, `signal_cube.{edges,series}`, `telemetry.{events,logs,spans}`, `anomalies` |
| Writes | `graph/{nodes,edges,paths}.parquet` |
| Config | `config/causalith.yaml` |

Once implemented (O-05):

```bash
uv run python scripts/check.py --package causalith
uv run veyltrace diagnose --dataset synth --case synth-01 --ai off
```
