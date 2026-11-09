# veyltrace-causalith (`veyltrace_causalith`)

Engine 5 of Veyltrace v2 (Observe lane). Causalith builds the service dependency graph from what the system shows and computes candidate propagation paths. It does not learn a causal graph from series; benchmarks show that does not pay off at this scale.

- **Graph**: nodes with kinds (`service`, `db`, `cache`, `queue`, `external`, `entry`); edges from traces, topology hints and log mentions, each with provenance, call share and an anomaly flag.
- **Paths**: for every node, up to 3 lowest-cost paths to an entry service, preferring anomalous edges and nodes.
- **`entry.entry_services()`**: the one entry-service rule, shared with Anomara and core's alert step (built in O-04b). Use it like this:
  - `entry_config(section)` parses `causalith.entry` from the causalith config section. Anomara reads it as `ctx.config.section("causalith")`.
  - `entry_services(call_pairs, services, system, cfg)` applies the rule: the system hint ∩ services, else callers that no non-excluded service calls, else `[]`. The result is sorted.
  - `run_entry_services(alert, edges, services, system, cfg)` is the run-level form. It copies `alert.detector.entry_services` when the detected protocol set it, else applies the rule to `signal_cube.edges`.
- **`ci.intervention_test()`**: IDI-style residual test (fit on baseline, judge the incident) on at most 5 candidate neighbourhoods, called by FaultLoom's claim pass (`intervention` atoms) for trial T8.

Spec: [docs/engines/05-causalith.md](../../docs/engines/05-causalith.md). Rules for agents: [AGENTS.md](AGENTS.md).

| | |
|---|---|
| Reads | `case_manifest`, `alert`, `signal_cube.{edges,series}`, `telemetry.{events,logs,spans}`, `anomalies` |
| Writes | `graph/{nodes,edges,paths}.parquet` |
| Config | `config/causalith.yaml` |

## Modules

| Module | What | Spec |
|---|---|---|
| `entry` | the shared entry-service rule (also used by Anomara and core's alert step) | 05-causalith §3.3 |
| `graph` | trace edges (call shares, anomaly rules), external hosts, node kinds | §3.1, §3.2, §3.4 |
| `mentions` | mention matcher with the ambiguity rule; log-mention and topology-hint edges | §3.4, §3.5 |
| `paths` | Yen's k-shortest propagation paths to the entries, ranked by anomaly | §3.6 |
| `ci` | the restricted CI test for T8: `intervention_test()` (`CI_API_VERSION = "1"`) and `partial_corr_test()` | §3.7 |
| `settings` | typed, validated view of `config/causalith.yaml` | §4 |
| `api` | `run(ctx)`: `graph.nodes` and `graph.edges` with trace, log and topology provenance and `graph.paths` | §2 |

On synth, `signal_cube.edges` stays empty until Signalyth (O-02) lands, so the synth graph has its nodes (six services and the external card gateway) and only its log and topology edges (recommend → catalog, frontend → checkout) until then. The hand-made golden case `fixtures/handmade/synth-topology/` is the synth topology written as Signalyth will, and pins the graph exactly; refresh it after review with `VEYLTRACE_UPDATE_HANDMADE=1 uv run pytest packages/causalith/tests/test_handmade.py`.

Commands:

```bash
uv run python scripts/check.py --package causalith
uv run veyltrace diagnose --dataset synth --case synth-01 --ai off
```
