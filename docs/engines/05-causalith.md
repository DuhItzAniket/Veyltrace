# 05 · Causalith — build the dependency graph and candidate propagation paths; offer a restricted conditional-independence test

> Status: built (O-04, O-05), checked against the code at `results-code-v1` · Lane: Observe · Master: [docs/02-architecture.md §6.5](../02-architecture.md), §6.9 (T3, T8) · Contracts: [docs/03-contracts.md §6](../03-contracts.md) (reads §2–4, §2.6 `alert`) · Last updated: 2026-11-24

## 1. Purpose and scope

Causalith builds the service dependency graph from what the system shows: observed calls in traces, topology hints in events, and service mentions in logs. Each edge records where it came from. It then computes, for every service with an anomaly (in practice every node, §3.6), the best propagation paths to the entry service(s). It also provides two pure functions other engines call: the shared entry-service rule and the restricted conditional-independence (CI) test behind Causentra's trial T8.

**In scope**: nodes, node kinds, entry detection, edges with provenance and an anomaly flag, k-best paths, the CI test API.

**Out of scope**: full causal discovery over all series ([02 §11](../02-architecture.md)); ranking (Causatrix `graph_walk` uses this graph); running trials (Causentra).

**Why no full causal discovery.** On synthetic 10–50-node graphs discovery F1 is 0.1–0.54, PC and FCI ran out of memory at 50 nodes, PCMCI scored F1 0.04–0.12, and most graph-learning RCA methods performed like a random "Dummy"; CIRCA took 3,792 s per Train Ticket case; on PetShop plain ranked correlation beat every graph-free causal method ([novel_building_blocks §Q4][nbb]). In 2026 evaluations graph-based RCA never clearly beat the best statistical baseline ([sota_methods_2026 §Q1][sota]). The defensible use of causality on a laptop is hypothesis verification on a known call graph (card N4), which is what §3.7 provides.

## 2. Inputs and outputs

**Reads**

| Contract | Fields used |
|---|---|
| `case_manifest` | `system`, `services` |
| `alert` | `windows.*`, `detector?.entry_services` |
| `signal_cube.edges` | all columns |
| `signal_cube.series` | `service, source` (node `metrics` provenance); the CI test (§3.7) reads `series_id, service, signal, family, source, unit, t_ns, value` |
| `telemetry.events` | `entity, kind, detail_json` (topology hints) |
| `telemetry.logs` | `service, t_ns, body` (log mentions) |
| `telemetry.spans` | `service, kind, attrs_json` (node kinds from `db.system` / `messaging.system`; external nodes from `server.address` / `peer.service`) |
| `anomalies` | `service, klass, detector, above_threshold` (node anomaly for paths) |

**Writes**

| Contract | Fields |
|---|---|
| `graph.nodes` | `node, kind, is_entry, provenance` |
| `graph.edges` | `src, dst, provenance, calls_incident?, weight, anomalous?` |
| `graph.paths` | `candidate, path_rank, nodes, anomalous_fraction` |

**Library API** (pure functions, no I/O): `veyltrace_causalith.entry` (§3.3) and `veyltrace_causalith.ci` (§3.7, called by FaultLoom's claim pass to produce the `intervention` atoms behind Causentra's T8). In `entry`, `entry_services()` is the rule itself; Anomara's `detect_alert` (which core's alert step calls) calls it directly. `run_entry_services(alert, edges, services, system, cfg)` is the run-level form with the `alert.detector` override; Anomara's `run()` and Causalith call it. `entry_config(section)` parses `causalith.entry` for all three.

## 3. Algorithm

### 3.1 Nodes

Node set = `case_manifest.services` ∪ services in `signal_cube.edges` ∪ external nodes (below). Log mentions and topology hints never create nodes; they only connect known ones.

**External nodes** (when `graph.include_external`): the host in `server.address` (else `peer.service`) of client spans, lower-cased, without userinfo and port. A host is ignored if it is not a valid node name (03 §1), or if it or its first DNS label is a known service (a manifest service or a trace-edge endpoint). It becomes a node with ≥ `graph.external_min_calls` such spans.

`provenance` = sorted union of the provenance of the node's edges (§3.4; both endpoints of an edge get it, so `topology` marks the event's entity and the service it names, `logs` the source and target of a counted mention), plus `traces` if the node has spans or is an external node, plus `metrics` if it has a `source = metrics` series in `signal_cube.series`. Edge provenance never contains `metrics` here: Causalith derives no edges from metrics.

### 3.2 Node kinds

First match wins:

| Order | Condition | `kind` |
|---|---|---|
| 1 | `is_entry` | `entry` |
| 2 | spans of the node carry `db.system` ∈ {redis, memcached} or name matches `node_kinds.cache_patterns` | `cache` |
| 3 | spans carry `db.system`, or name matches `node_kinds.db_patterns` | `db` |
| 4 | spans carry `messaging.system`, or name matches `node_kinds.queue_patterns` | `queue` |
| 5 | external node (§3.1) | `external` |
| 6 | otherwise | `service` |

"Spans of the node" are a service's own server and internal spans, and for an external node the client spans that call it. Client, producer and consumer spans describe the remote side, so a service that calls a database or uses a queue does not become a `db` or a `queue`. `db.system` values are compared in lower case; name patterns are case-sensitive regex searches on the node name.

`db.*` attributes follow stable OTel semantic conventions; `messaging.*` is still in progress ([stack_and_market §A1][sm]).

### 3.3 Entry detection (shared rule)

`entry_services(call_pairs, services, system, cfg) -> list[str]` (sorted A→Z), where `call_pairs` is the sorted set of (caller, callee) service pairs. Three callers use it:

| Caller | `call_pairs` from |
|---|---|
| Anomara `detect_alert` (core's alert step, before Signalyth) | parent→child spans in different services over the full `telemetry.spans` span |
| Anomara `run()` and Causalith | `signal_cube.edges` (both windows), **unless** `alert.detector` is set, in which case both return `alert.detector.entry_services` (sorted) and do not recompute it |

The override keeps all three consistent under the detected protocol (the alert was decided on that entry set), and under the other protocols Anomara and Causalith compute from identical inputs. A cross-engine test asserts `onsets.entry_services == sorted(node where is_entry)` on every fixture.

Rule:

1. **System hint.** Take `entry.hints[system]` ∩ `services`. If the case has at least one call pair with caller ≠ callee, keep only the hinted services that occur in such a pair, as caller or callee ([ADR 20261122-ak-entry-hint-needs-trace-edge](../adr/20261122-ak-entry-hint-needs-trace-edge.md)). Return the result if it is not empty; otherwise continue with rule 2. Defaults (a priori, architecture knowledge, not fault labels): `ob: [frontend]`, `ss: [front-end]`, `tt: [ts-ui-dashboard]` (RCAEval TT has `ts-ui-dashboard_istio-latency-90`, [rcaeval_facts §Dataset layout][rf-layout]), `otel: [frontend-proxy]`. The names were checked on RE2 data under #36: the OB and SS hints apply; on RE2-TT `ts-ui-dashboard` is a known service with no spans, so rule 2 decides there (**measured**, same ADR).
2. **From call pairs.** Ignore self pairs (caller = callee). Remove services in `entry.exclude` (load generators). Entries = services that appear as a caller and never as the callee of a non-excluded service.
3. Otherwise an empty list. (Without traces and without a hint there is no defensible entry; `detect_alert` then returns `None` and paths are empty.)

### 3.4 Edges

**From traces** (`signal_cube.edges`): one edge per (`caller`, `callee`) present in either window.

- `calls_incident` = incident-window `calls` (0 if only baseline calls exist).
- `weight` = this edge's incident calls ÷ all incident calls from `src`; if `src` has none, the same share from baseline calls; else 1.0.
- `anomalous` (incident row `i` vs baseline row `b`; thresholds a priori), true if any holds:
  - `i.p99_callee_ms ≥ (1 + edges.anom_latency_ratio) · b.p99_callee_ms` and the difference ≥ `edges.anom_latency_min_ms`;
  - the same test on `p99_gap_ms` (when both non-null);
  - `i.error_rate − b.error_rate ≥ edges.anom_error_delta`;
  - `b.calls ≥ edges.silence_min_baseline_calls` and the edge has no incident row (edge went silent; 03 §3.2 omits rows with `calls = 0`);
  - no baseline row and `i.error_rate ≥ edges.anom_error_delta`.

  Each `≥` also holds for a value equal to its threshold up to float rounding (`math.isclose`), so an exact +0.05 error step meets a 0.05 threshold. A null p99 never triggers a latency rule.

**From topology hints** (`telemetry.events`): for events of kind `deploy` or `config` on entity A, scan every string value in `detail_json` with the mention matcher (§3.5); a match on known service B gives A → B. Events whose entity is not a node, or whose `detail_json` is not valid JSON, are ignored. A static topology file (`topology.static_path`, a YAML adjacency list per system) is reserved and not built: any value other than `null` is a `ConfigError`.

**From log mentions** (`telemetry.logs`): for each logging service A and known service B ≠ A, count lines of A whose body mentions B (§3.5) over baseline ∪ incident. Count ≥ `logs.min_mentions` gives A → B. A frontend line "failed to get cart from cartservice" is evidence of the call frontend → cartservice ([rcaeval_facts §Logs][rf-logs]). DuckDB groups the lines into distinct (service, body) pairs with their line counts; the matcher then runs once per distinct body, in Python. A service's patterns run only when its name occurs in the case-folded body. Every non-gRPC form contains the name as a literal, so this prefilter (added 2026-11-22, #36) never changes a result; a property test compares it with running every pattern.

**Merge.** Union by (`src`, `dst`); self-loops dropped; `provenance` = sorted union; `calls_incident` only from traces (null otherwise); `weight` from traces, else 1.0; `anomalous` from traces, else null (no trace data, 03 §6.2).

### 3.5 Mention matcher and the ambiguity rule

For a known service name `n` (already normalised, regex-escaped):

| Form | Pattern (sketch) | Example |
|---|---|---|
| host:port | `(?<![\w.-])n(\.[a-z0-9-]+)*:\d{2,5}\b` (optional cluster DNS suffix) | `ts-order-service:12031`, `cartservice.default.svc.cluster.local:7070` |
| URL | `[a-z][a-z0-9+.-]*://n(\.[a-z0-9-]+)*(:\d+)?(?![\w-])` (the host ends at a non-name character, so `mongodb://carts-db:27017` is not `carts`) | `http://carts:80/carts/1` |
| gRPC package | `\b[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*\.([A-Z]\w*)\b` where lowercase of the last part equals `n`, or equals `n` after removing a trailing `service` | `hipstershop.CartService` → `cartservice`; `oteldemo.CartService` → `cart` |
| plain word | `(?<![\w.-])n(?![\w-])` | `ts-order-service` |

**Ambiguity rule.** If `n` matches `^[a-z]+$` (e.g. `carts`, `orders`, `user`, `payment`, `frontend`), only the host:port, URL and gRPC-package forms count; a plain word is too likely to be ordinary English. Names with a hyphen, digit or dot may also match as a plain word. A line counts at most once per mentioned service; mentions of the logging service itself are ignored. The host:port, URL and plain-word forms match case-insensitively; the gRPC form needs a capitalised last part.

### 3.6 Paths

Paths run from a candidate to an entry against the call direction (03 §6.3): if the entry calls … calls the candidate, the path is candidate → … → entry.

1. **Node anomaly**: the service has an `anomalies` row with `above_threshold` and either (`detector = robust_z`, `klass = external`) or (`detector = silence`, `klass ∈ {external, context}`).
2. **Reversed graph** `R`: for each edge `src → dst`, add `dst → src` with cost 1.0 if the edge is anomalous (`anomalous = true`; null counts as not anomalous) or `src` (the caller, next node on the path) is anomalous, else `1.0 + paths.non_anomalous_penalty`.
3. Add a virtual sink with zero-cost arcs from every entry. Nodes and arcs are inserted in sorted order.
4. For **every** node `c` (a superset of 02 §6.5's "every service with an anomaly"; the slate does not exist yet at step 4): enumerate simple paths `c → sink` in cost order with Yen's algorithm, written in-package (`veyltrace_causalith.paths.yen`, a lead decision in O-05; no graph library). A path's cost is the correctly rounded sum of its arcs (`math.fsum`), so equal-cost paths tie exactly. Paths with more than `paths.max_len` nodes (the sink not counted) are skipped. Enumeration stops when `paths.k` paths are collected **and** the next path costs more than the k-th (so ties are all seen), or when the next path costs more than `(paths.max_len − 1)` × the largest arc cost. Sort by (cost asc, `anomalous_fraction` desc, length asc, node list lexicographic); keep the first `paths.k`; `path_rank` = 1…k.
5. An entry node gets the single path `[entry]` (fraction 1 if the entry is anomalous, else 0). A node that cannot reach an entry gets no rows.
6. `anomalous_fraction` = anomalous nodes on the path ÷ nodes on the path.

Micro-example: edges frontend → checkout, checkout → payment, frontend → cart; only checkout → payment is anomalous; payment and checkout are anomalous. For candidate payment, `R` has payment → checkout (cost 1, anomalous edge) and checkout → frontend (cost 1, checkout anomalous). Path `[payment, checkout, frontend]`, cost 2, `anomalous_fraction` 2/3 if frontend is not anomalous.

### 3.7 Restricted conditional-independence test (for T8)

Trial T8 asks whether the candidate's anomaly is explained by its parents ([02 §6.9](../02-architecture.md)). In a call graph the parents of a service's symptom are its callees (failures propagate up to callers) plus its own load. The test is an IDI-lite residual check: fit the candidate's signal on its parents using baseline data only, then see whether the incident deviation survives ([novel_building_blocks §Q4, card N4][nbb]; IDI, ICLR 2025).

```python
CI_API_VERSION = "1"

@dataclass(frozen=True)
class CIResult:
    candidate: str
    target_series_id: str | None
    parents: tuple[str, ...]            # regressor series_ids, in the order used
    n_baseline: int
    n_incident: int
    stat_raw: float                     # persistent robust z of the target (incident vs baseline)
    stat_resid: float                   # same statistic on residuals
    explained_fraction: float           # clip(1 - stat_resid / stat_raw, 0, 1); 0 if stat_raw == 0
    p_value: float                      # block-conformal p-value of the residual deviation
    independent_of_parents: bool | None # True: anomaly NOT explained by parents (T8 pass); None: untestable
    reason: str | None                  # no_target | no_parents | short_baseline | no_incident | singular

def intervention_test(series: pa.Table, graph_edges: pa.Table, alert: Alert,
                      candidate: str, config: CIConfig,
                      target_series_id: str | None = None) -> CIResult: ...

def partial_corr_test(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> tuple[float, float]: ...
```

`CIConfig.from_sections(causalith, anomara)` builds the config from `causalith.ci.*` plus Anomara's `robust_z.{persist_steps, mad_factor, iqr_divisor, eta, epsilon}` and `grid.bucket_s`, so the scale floor, the persistence and the grid step of traces and logs series are always Anomara's. A missing or malformed key is a `ConfigError`. An untestable result (`reason` set) has `stat_raw = stat_resid = explained_fraction = 0.0` and `p_value = 1.0`; consumers read `reason`, not the numbers.

`intervention_test` steps:

1. **Target**: `target_series_id` if given (FaultLoom passes the candidate's top internal series, [06-faultloom](06-faultloom.md)); else the first present of the candidate's traces `latency_p99`, metric latency (highest quantile), traces `error_rate`, metric `error`, ties by `series_id`. None, an unknown `target_series_id`, or a series of another service → `reason = no_target`.
2. **Parents** (≤ `ci.max_parents` = 5 regressors): callees of the candidate in `graph.edges` ordered by (`anomalous` desc with null as false, `weight` desc, name asc), each represented by its target-priority series (a callee without one is skipped and uses no slot); then one load covariate, the candidate's own `rps` series, else `workload`, if a slot is left. No regressor → `no_parents`.
3. **Grid**: from the baseline start to the incident end; step = the largest effective step among involved series (metrics: the median run of equal values, at least the median spacing; traces and logs: Anomara's `grid.bucket_s`; as [03-anomara §3.1](03-anomara.md)); last value per bucket; keep buckets where every column is observed.
4. **Fit on baseline buckets** (`alert.windows.baseline`; residuals are judged on `alert.windows.incident`): standardise each column with the robust scale floor of [03-anomara §3.2](03-anomara.md) (re-implemented locally to avoid a circular package dependency; a parity test compares both). Ridge regression with an unpenalised intercept: centre, then solve `(ZᵀZ + λ n I) b = Zᵀx` with `numpy.linalg.solve`, `λ = ci.ridge`. Checked in this order before the fit: ≥ `ci.min_baseline_points` baseline buckets and more than `2(k + 1)` for `k` regressors (else `short_baseline`); at least one incident bucket (else `no_incident`, e.g. a crashed candidate whose series stops at the incident). A singular system gives `singular`.
5. **Residuals** `r = x − Zb` over all buckets. `stat_raw` and `stat_resid` = max persistent z over the incident buckets (Anomara §3.2 steps 3–5: `anomara.robust_z.persist_steps` = 3 contiguous grid buckets of one sign) of `x` and of `r`, each centred on its own baseline median and measured in `x`'s floored scale from step 4. They are not standardised a second time: dividing by their own baseline spread would undo the scale floor, and a residual that is a scaled copy of its parent would then score like the parent.
6. **p-value** (technique T2b, [rcaeval_facts §Anomaly scoring methods][rf-methods]): cut baseline residual z-values into non-overlapping blocks as long as the incident span (at most baseline/4); `g` = median `|z|` per block; `p = (1 + #{blocks with g_b ≥ g_I}) / (n_blocks + 1)`. Its floor is `1/(n_blocks + 1)`, so it is reported, not used for the decision.
7. `independent_of_parents = stat_resid ≥ ci.threshold` (3.0).

`partial_corr_test(x, y, z)`: residualise `x` and `y` on `z` with the same solver and no penalty; Pearson `r` of residuals; Fisher `z = atanh(r)·sqrt(n − dim(z) − 3)`; two-sided `p = erfc(|z|/√2)` (stdlib `math`, equal to `2·norm.sf(|z|)`). A singular system returns `(0.0, 1.0)`; `n − dim(z) − 3 ≤ 0` returns `p = 1.0`. Exposed for the ablation arm only.

Caller contract: the API is caller-agnostic; its caller is FaultLoom's claim pass, which writes evidence atoms of kind `intervention` for decision-pool candidates ([03 §7](../03-contracts.md)); Causentra reads atoms only. The caller applies the per-case limit: FaultLoom tests the first `intervention.max_candidates` (5, `config/faultloom.yaml`) members of the decision pool ([06-faultloom §3.6](06-faultloom.md)); Causalith does not read `ci.max_candidates`. The caller loads `signal_cube.series`, `graph.edges` and `alert` through `veyltrace_core.io`. The function never reads files, the clock or RNG. The solved system is at most 5 × 5 (`ci.max_parents` regressors), so the result is reproducible; the determinism gate covers it.

## 4. Configuration — `config/causalith.yaml`

| Key | Default | Unit | Rationale / source |
|---|---|---|---|
| `entry.hints` | `{ob: [frontend], ss: [front-end], tt: [ts-ui-dashboard], otel: [frontend-proxy]}` | — | a priori; [rcaeval_facts §Dataset layout][rf-layout] |
| `entry.exclude` | `[load-generator, loadgenerator, locust]` | — | traffic sources are not entries |
| `node_kinds.db_patterns` | `[-db$, mongo, mysql, postgres, mariadb]` | regex | a priori |
| `node_kinds.cache_patterns` | `[redis, memcached, valkey]` | regex | a priori |
| `node_kinds.queue_patterns` | `[kafka, rabbitmq, nats]` | regex | a priori |
| `graph.include_external` | `true` | — | a priori |
| `graph.external_min_calls` | `10` | spans | a priori |
| `edges.anom_latency_ratio` | `0.5` | ratio | a priori |
| `edges.anom_latency_min_ms` | `5.0` | ms | a priori |
| `edges.anom_error_delta` | `0.05` | ratio | a priori |
| `edges.silence_min_baseline_calls` | `10` | calls | a priori |
| `logs.min_mentions` | `3` | lines | a priori |
| `topology.static_path` | `null` | path | not built; must be `null` (§3.4) |
| `paths.k` | `3` | paths | a priori |
| `paths.max_len` | `10` | nodes | a priori (≤ 100-node graphs, [02 §8](../02-architecture.md)) |
| `paths.non_anomalous_penalty` | `1.0` | cost | a priori |
| `ci.max_parents` | `5` | regressors | [02 §6.5](../02-architecture.md) (≤ 5 neighbourhoods) |
| `ci.max_candidates` | `5` | candidates | not read by Causalith; the effective limit is FaultLoom's `intervention.max_candidates` (§3.7) |
| `ci.ridge` | `0.001` | — | a priori, numerical stability |
| `ci.min_baseline_points` | `20` | buckets | a priori |
| `ci.threshold` | `3.0` | z | same as Anomara `robust_z.threshold` |
| `duckdb.threads` | `1` | — | determinism |
| `duckdb.memory_limit` | `2GB` | — | a priori, lead default (M0, 2026-11-06) |

All keys are validated once per run; a missing or malformed key is a `ConfigError` before the graph is built. The unused key `causalith.ci.max_candidates` stays in the YAML until v1.1, because removing it changes the config hash of every run.

## 5. Determinism and isolation

- Graph built with nodes and arcs inserted in sorted order; path ties resolved explicitly (§3.6); no graph library.
- Distinct-body line counts from DuckDB (exact, ordered); regex patterns built from the sorted service list.
- CI test: float64, fixed parent order, tiny dense solves, no RNG.
- Allowed imports: `veyltrace_core`, `veyltrace_contracts`, `numpy`, `pyarrow`, stdlib (DuckDB only through `veyltrace_core.duck`). Banned per AGENTS §4.3. `veyltrace_causalith` must not import `veyltrace_anomara` (Anomara imports `veyltrace_causalith.entry`; a reverse import would be circular).

## 6. Missing data and failure behaviour

| Situation | Behaviour |
|---|---|
| No traces (e.g. Sock Shop, [rcaeval_facts §Datasets and telemetry][rf-data]) | edges only from logs/topology; `calls_incident` null, `weight` 1.0, `anomalous` null; entry from the system hint |
| No logs | no log-mention edges |
| No events | no topology edges |
| No edges at all | nodes only; paths only for entries; T3 becomes untestable downstream |
| No entry found | `is_entry` false everywhere; `graph.paths` empty |
| System hint names a service the case's traces never show (RE2-TT) | hint ignored; entries from call pairs (§3.3 rule 2) |
| `alert.detector` set | entry services copied from it (§3.3) |
| No `anomalies` rows | every node non-anomalous; an arc costs 1 only where its trace edge is anomalous, else `1 + penalty`; fractions 0 |
| CI test preconditions fail | `independent_of_parents = None` with `reason`; Causentra marks T8 `untestable` |

## 7. Tests

**Unit**: node kind precedence (a service that calls a database or uses a queue stays a `service`); entry rule branches (hint, a hint without a trace edge, a logs-only or self-pairs-only case keeping its hint, call pairs with an excluded load generator, empty) and the `alert.detector` override; edge anomaly rules one by one; weight normalisation; mention matcher (each form; `carts` as plain word does not count, `carts:80` does; `hipstershop.CartService` → `cartservice`; `oteldemo.CartService` → `cart`; self-mention ignored; the four non-ASCII case folds); path micro-example; tie handling in Yen enumeration, exact ties whatever the arc order, `paths.max_len`; CI on hand-built series with a known answer, each untestable reason, a tiny shift on a floored scale, persistence needing contiguous buckets; Fisher-z p-value against a textbook value; config defaults equal the §4 table and a non-null `topology.static_path` is rejected.

**Golden (synth-01…05)**: nodes and edges equal the synthetic topology exactly (O-05 acceptance, pinned by the hand-made case `fixtures/handmade/synth-topology/`); entry equals the toy system's entry; every non-entry node that can reach the entry has `path_rank` 1. CI: on synth-01 the CPU-hog service's latency is not explained by its callees (`independent_of_parents = True`); fixtures record the result for every service.

**Cross-engine** (`tests/integration/test_observe_entry.py`): `onsets.entry_services` equals entry nodes on all fixtures; scale-floor parity with Anomara on random data.

**Property (hypothesis)**: every path starts at its candidate, ends at an entry, has no repeated node, and consecutive nodes are connected; ranks are 1…n without gaps; Yen enumerates every simple path in cost order; prefiltered mentions equal running every pattern; entries are the sorted uncalled callers whatever the input order; adding a log-mention edge never removes an existing provenance entry (not built); CI — `x = a·z + noise` in both windows with a shift in `z` during the incident → `independent_of_parents = False`; an independent shift in `x` → `True`; result invariant to row order.

**Real-case smoke** (not built, neither the test nor the bench arm): RE2-OB (traces; gRPC package names in logs), RE2-SS (no traces; log mentions and hint entry), RE2-TT (≈ 64 services): schema-valid, two runs identical, time within §8. On OB and TT, bench reports precision and recall of log-mention edges against trace edges (no answer key needed).

## 8. Performance budget

Budget per RE2 case: ≤ 2 s and ≤ 0.5 GB (*estimate*, allocation of the 30 s / 3 GB budget). Graphs have ≤ 100 nodes ([02 §8](../02-architecture.md)); `k = 3` paths per node.

**Measured** step time (Observe laptop, Apple M4, 2026-11-23, AI off, one case per system): 0.6 s on an RE2-OB case, 1.4 s on an RE2-SS case, 1.4 s on an RE2-TT case that has no logs. No memory figure has been measured.

Log-mention matching is the cost that grows with the case. Counting runs over distinct log bodies, but RE2-TT bodies start with a timestamp, so nearly every line is a distinct body. **Measured** on one RE2-TT case with 221,202 distinct log bodies and 68 services (lead, issue #36): matching took 341–387 s before the substring prefilter (§3.4) and about 4 s after, with identical results. Such a case is over the 2 s allocation; the end-to-end measurement is open under O-11 (#36).

## 9. Evaluation hooks and ablations

| Arm | Bench measures |
|---|---|
| edge provenance: traces only / + logs / + topology (static topology: not built, §3.4) | T3 testability, `graph_walk` accuracy, Retrieval@K |
| log-mention edges vs trace edges (OB, TT) (not built) | edge precision/recall |
| `paths.non_anomalous_penalty` ∈ {0, 1} | path anomalous fraction, T3 outcomes |
| T8 on/off; `intervention_test` vs `partial_corr_test` | Causentra accuracy and status mix |
| Causalith itself | wall time, node/edge counts per case |

## 10. Tasks and milestones

| ID | When | Scope | Acceptance (summary) |
|---|---|---|---|
| O-00 | done | stub, synth fixtures | e2e on `synth-01` |
| O-04 (part) | done | `veyltrace_causalith.entry` first, because Anomara depends on it | entry consistency test passes |
| O-05 | done | graph from traces/topology/logs; paths; CI test API | graph matches synth topology exactly |
| O-11 | Phase 3; measurement open (#36) | performance pass | ≤ 30 s, ≤ 3 GB end to end |
| O-12 | Phase 4; in progress (#48) | docs, fixtures | reviewed by lead |

## 11. Open questions

| # | Question | Default if unresolved |
|---|---|---|
| 1 | ~~Causalith needs `anomalies`, which the 02 §3 reads omitted.~~ Resolved in 02 (2026-10-30): [02 §3](../02-architecture.md) lists `anomalies`, and the 03 §1 catalog lists Causalith as an `anomalies` consumer. | — |
| 2 | ~~Paths "for each slate candidate", before the slate exists.~~ Resolved in 02 §6.5 (2026-10-30): paths for every anomalous service; this spec computes them for every node (superset). | — |
| 3 | ~~**CCR**: `metrics` provenance value.~~ Resolved in 03 §6.1 (2026-10-30). | — |
| 4 | ~~**CCR**: nullable `graph.edges.anomalous`.~~ Resolved in 03 §6.2 (2026-10-30): null when the edge has no trace data. | — |
| 5 | ~~Who calls `intervention_test`?~~ Resolved in 03 §7 (2026-10-30): FaultLoom's claim pass, evidence kind `intervention`. | — |
| 6 | ~~Entry hints are a priori names; verify on RE2 data.~~ Resolved (2026-11-22, [ADR 20261122-ak-entry-hint-needs-trace-edge](../adr/20261122-ak-entry-hint-needs-trace-edge.md)): the TT hint is not traced, so a hint counts only when the case's traces show it (§3.3 rule 1). Hint names still change only by ADR. | — |
| 7 | ~~Should the CI API be frozen with contracts at M1?~~ Resolved: `ci.py` carries `CI_API_VERSION = "1"`; a signature change needs an issue tagging the consuming lane (package AGENTS). | — |

## 12. References

- Master and contracts: [02 §6.5, §6.9, §8, §11](../02-architecture.md); [03 §6](../03-contracts.md); [07](../07-roadmap.md)
- Causal discovery benchmarks, IDI, Smooth Traversal, card N4: [novel_building_blocks §Q4][nbb]
- Graph-based vs statistical RCA in 2026: [sota_methods_2026 §Q1][sota]
- Caller-blame log mentions, block p-values: [rcaeval_facts §Anomaly scoring methods][rf-methods], [§Logs][rf-logs]; call graph for consistency only: [rcaeval_facts §Traces][rf-traces]
- Semantic-convention stability: [stack_and_market §A1][sm]
- RCAEval systems and names: [rcaeval_facts §Datasets and telemetry][rf-data], [§Dataset layout][rf-layout]
- IDI: "Robust Root Cause Diagnosis using In-Distribution Interventions", ICLR 2025 (arXiv 2505.00930) · Yen's k-shortest paths (implemented in `veyltrace_causalith.paths`)
- Entry hint rule: [ADR 20261122-ak-entry-hint-needs-trace-edge](../adr/20261122-ak-entry-hint-needs-trace-edge.md)

[nbb]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/novel_building_blocks.md
[sota]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/sota_methods_2026.md
[sm]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/stack_and_market.md
[rf-data]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#datasets-and-telemetry-per-system
[rf-layout]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#dataset-layout
[rf-methods]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#anomaly-scoring-methods
[rf-traces]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#traces-spectrum-and-timing
[rf-logs]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#logs

