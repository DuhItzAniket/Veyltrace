# 03 · Data contracts

> **Status:** v0.1-draft (frozen as v1.0 at milestone M1) · **Owner:** lead (file), producer lane (semantics) · **Last updated:** 2026-11-08 (R-04: bench_result `ranks` and `summary.json` CI notes)
> Master spec: [02-architecture](02-architecture.md). This doc is the field-level truth for every artifact that crosses a package boundary. If a field is not here, no engine may rely on it.

## 1. How contracts work

| Item | Rule |
|---|---|
| Source of truth | `contracts/schemas/<name>.schema.json` (JSON Schema 2020-12), where `<name>` is the contract name exactly as written here, dots kept (`case_manifest.schema.json`, `telemetry.metrics.schema.json`, `graph.edges.schema.json`). This doc and the schemas must match; the schemas are written from this doc in task `R-01` (see [07-roadmap](07-roadmap.md)). The mechanical schema rules (file names, `$id`, how `?` is encoded, Arrow column types, key and sort annotations, shared `$defs` in `common.schema.json`) are in [contracts/schemas/CONVENTIONS.md](../contracts/schemas/CONVENTIONS.md). Every contract has one valid example instance, `contracts/examples/<name>.example.json`, validated by the generator's `--check`. |
| Generated code | `contracts/generated/python/veyltrace_contracts/` (Pydantic v2: `models.py`, `arrow.py`, `registry.py`, `predicates.py`, a copy of the schemas) and `contracts/generated/ts/index.ts` (TypeScript). Regenerate with `uv run scripts/gen_contracts.py`; `uv run scripts/gen_contracts.py --check` validates schemas and examples and fails on any diff. Never edit by hand. CI fails if regeneration produces a diff. |
| Versioning | Every schema has `$id: https://veyltrace.dev/schemas/<major>.<minor>/<name>.schema.json` (v0.1: `https://veyltrace.dev/schemas/0.1/telemetry.metrics.schema.json`); the URL is an identifier and is never fetched. JSON artifacts carry `"schema_version": "<major>.<minor>.<patch>"`. Parquet files carry the key `veyltrace.schema` = `<name>/<major>.<minor>.<patch>` in file metadata (e.g. `evidence/0.1.0`). |
| Before M1 | `0.x`: the lead may change fields after posting in the team channel and the CCR issue. |
| After M1 (`1.0`) | Additive optional fields only (minor bump), via a Contract Change Request (CCR) issue + ADR + lead approval. Removing or renaming a field needs all three lanes' approval and a major bump. |
| Golden fixtures | Producer ships outputs for `synth-01` … `synth-05` in `packages/<producer>/fixtures/<case>/`. Consumers load them via `veyltrace_core.testing.golden("<contract>", "<case>")`. |
| Units | Time: int64 **nanoseconds** since Unix epoch (UTC), suffix `_ns`. Durations in JSON: `_ms` (float). Scores: unitless float. In JSON, `_ns` values are plain integers (exact). TypeScript's `number` is display-only for them: at current epochs it is lossy below about 256 ns, and the console never re-hashes artifacts. |
| Identifiers | `case_id` = first 12 hex of SHA-256 of the adapter's canonical case key ([engines/01 §3.2](engines/01-infralume.md)), pattern `^[0-9a-f]{12}$`. `run_id` = first 16 hex of SHA-256(case_id, config_sha256, code_commit, ai.mode); a derived `verify_hypothesis` run appends `-x<12 hex>` ([02 §4.1](02-architecture.md)), so the pattern is `^[0-9a-f]{16}(-x[0-9a-f]{12})?$`. `atom_id` = `E` + first 10 hex of SHA-256 of canonical JSON `[kind, candidate, A]` (`A` per §7), pattern `^E[0-9a-f]{10}$`. `change_id` `^C[0-9a-f]{10}$` (§5.2), `template_id` `^T[0-9a-f]{8}$` (§3.3), `proposal_id` `^P[0-9a-f]{8}$` (§9.1). |
| Name patterns | Service, component, entity and node names match `^[a-z0-9][a-z0-9.-]*$`: lowercase, no `_`, because RCAEval ranks are `{service}_{indicator}` (§10 `ranks_rcaeval`). `dataset` matches `^[a-z0-9]+(-[a-z0-9]+)*$`; it is a pattern, not an enum. |
| Hashes | Lowercase 64-hex SHA-256, no prefix. `canonical_json`: sorted keys, `(",", ":")` separators, UTF-8, floats rounded to 9 decimals, NaN/Inf → `null`. |
| Nulls | A field or column marked `?` is **required and nullable**: it is always present and its value may be `null` (JSON and TypeScript `T \| null`; the Parquet column exists and is nullable). Nothing is optional by omission. A field without `?` is never null. |
| Floats in tables | NaN and ±inf are rejected in every float column of a table contract (Parquet, CSV); a missing value is `null` and only in a `?` column. |
| Free-form maps | Maps with free keys (`weights`, `ranker_ranks`, `ranker_scores`, `libs`) have typed values (`number`, `number \| null` or `string`), never `any`. Canonical JSON sorts their keys. |
| Parquet hashes | File bytes depend on the writer (pyarrow version, compression). Hashes are compared only within one pinned environment; a different pyarrow version is "environment drift" (replay exit 5), not a mismatch. |
| Sorting | Every Parquet table is written sorted by its **key** column list (given per table), then by every remaining column in schema column order; nulls sort first; strings compare by UTF-8 bytes. A table's key is unique for `telemetry.metrics`, `telemetry.spans`, `signal_cube.*`, `anomalies`, `changes`, `graph.*` and `evidence` (writers reject duplicate keys); `telemetry.logs` and `telemetry.events` may repeat a key. JSON arrays are sorted as stated per field; writers validate a stated order instead of re-sorting it ([CONVENTIONS §3.4](../contracts/schemas/CONVENTIONS.md)), and arrays whose order is semantic (`graph.paths.nodes`, `ranked`) are kept as produced. |

Catalog (producer → consumers):

| Contract | Kind | Producer | Consumers |
|---|---|---|---|
| `case_manifest` | JSON | Infralume | all engines, core |
| `alert` | JSON | core (alert step) | all engines from Signalyth on |
| `telemetry.metrics` / `.logs` / `.spans` / `.events` | Parquet | Infralume | core alert step (`detect_alert`), Signalyth, Causync, Causalith |
| `signal_cube.series` / `.edges` / `.templates` / `.critical_path` | Parquet | Signalyth | Anomara, Causalith, FaultLoom, Relentra tools |
| `anomalies` | Parquet | Anomara | Causync, Causalith, FaultLoom, Relentra tools |
| `onsets` | JSON | Anomara | Causync, FaultLoom, Causentra, Relentra tools, Causivra |
| `alignment` | JSON | Causync | FaultLoom, Causentra |
| `changes` | Parquet | Causync | FaultLoom, Relentra tools, Causivra |
| `graph.nodes` / `.edges` / `.paths` | Parquet | Causalith | FaultLoom, Causatrix, Causentra, Relentra tools, Causivra |
| `evidence` | Parquet | FaultLoom | Causatrix, Causentra, Relentra tools, Causivra |
| `slate` | JSON | Causatrix | Relentra, Causentra |
| `proposals` | JSON | Relentra | FaultLoom (claim pass), Causentra |
| `agent_trace` | JSONL | Relentra | Causivra (receipt) |
| `verdict` | JSON | Causentra | Causivra, gateway, bench |
| `card` | JSON (+ `card.md`) | Causivra | gateway, console |
| `config_lock` | JSON (`config.lock.json`) | core (manifest step) | `veyltrace replay`, core (run_manifest `config_sha256`) |
| `run_manifest` | JSON | core | Causivra, bench |
| `receipt` | JSON | Causivra | `veyltrace replay`, gateway |
| `calibration` | JSON (`config/calibration/<family>.json`) | bench | Causentra (via `ctx.config`) |
| `predicates` | JSON (`contracts/predicates.json`, repo file, not a run artifact) | lead (FaultLoom predicate library, §7) | FaultLoom, Relentra, Causentra (via generated `veyltrace_contracts.predicates`) |
| `answer_key` | Parquet | bench / lab | **bench only** |
| `bench_result` | CSV + JSON | bench | paper tables |
| API types (§14) | OpenAPI → TS | gateway | console, MCP clients |

Gateway and console may read every run artifact above for display; they never write them.

Cross-package Python types that are not artifacts are **not** contracts and have no schema: `CanonicalCase`, `AlertDetection`, `TelemetryTables` (core), `CIResult` with `CI_API_VERSION` (Causalith), `CardDeck` (FaultLoom), and `EvidenceView`, `GraphView`, `RankResult`, `Classification` (Causatrix). They stay frozen dataclasses in their owning packages, documented in the package README and pinned by tests. Schema-worthy but deferred (no change before M1): the cassette layout (Explain), the VeylLab capture layout ([05](05-fault-lab-and-dataset.md) OQ-3) and `snapshot.json` ([06](06-gateway-and-console.md) OQ-6).

Closed vocabularies used below:

- `family`: `cpu | mem | disk | net | latency | errors | traffic | logs | self_time | other`
- `klass`: `internal | external | context`
- `mode`: `resource | network | code | change | dependency | unknown`
- `fault_class`: `cpu | mem | disk | socket | delay | loss | error | exception | availability | config | dependency | unknown` (`socket`: RCAEval RE2 socket exhaustion; `availability`: pod kill, container restart, pod failure)
- `source`: `metrics | logs | traces | events` (`signal_cube.series`, `anomalies` and `onsets.per_service[].*_source` use the narrower subset `metrics | logs | traces`)
- `event_kind`: `deploy | config | flag | scale | restart | k8s_event | commit | other`
- `status` (verdict): `CONFIRMED | LIKELY | INCONCLUSIVE | NO_FAULT`
- `indicator`: `cpu | mem | diskio | socket | latency | error | logs | workload | unknown` (outputs of Causatrix's `indicator_map`; a series of family `other` maps to `unknown`). Used by `slate`, `verdict`, `proposals` and `answer_key`.
- `ai_mode` (`ai.mode`): `off | record | replay`
- `ai_arm`: `off | brief | investigate | external` (AI experiment arm; used by `calibration` and bench)

---

## 2. Infralume outputs

### 2.1 `case_manifest.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version` | str | `"0.1.0"` |
| `case_id` | str | 12 hex (§1) |
| `dataset` | str | e.g. `synth`, `re1-ob`, `re2-ob`, `re2-ss`, `re2-tt`, `re3-ob`, `nezha-ob`, `fse26-tt`, `veyllab-ob`, `veyllab-otel`, `live`; pattern `^[a-z0-9]+(-[a-z0-9]+)*$` (§1), not an enum |
| `system` | str | `ob \| ss \| tt \| otel \| other` (`live` is a dataset, not a system) |
| `t_alert_hint_ns`? | int | set only when the run's `alert.protocol` is `oracle` (the dataset's published injection time) or `live` (trigger time); null under `detected`, so the injection time never reaches engines in detected runs. Only core's alert step reads it ([02 §5.1](02-architecture.md)). The schema does not check that the hint lies inside the data span (core's alert step does). |
| `hint_source` | str | `oracle \| live \| none`; `none` if and only if `t_alert_hint_ns` is null (including every detected-protocol run); the schema enforces this pairing |
| `data_start_ns`, `data_end_ns` | int | span of available data, including overlay events; `data_start_ns ≤ data_end_ns` (writer check) |
| `sources` | object | `{metrics: bool, logs: bool, traces: bool, events: bool}`; the key is `traces` (not `spans`). One shared definition, also used as Causatrix's `Sources` type; config `sources.drop` lists values of the `source` vocabulary |
| `services` | [str] | sorted by UTF-8 bytes; may be empty (e.g. an events-only case) |
| `inputs` | [{`name`, `sha256`, `bytes`}] | sorted by `name`; may be empty; `name` is relative, matches `^(metrics\|logs\|traces\|events\|overlay)/[^/]+$` and never contains the original folder name |
| `adapter` | {`name`, `version`} | `version` is a per-adapter revision string |
| `scrub` | {`rules_version`, `dropped_attributes`, `dropped_rows`} | counts; `dropped_rows` counts rows of deny-listed services, dropped containers and chaos events; Infralume documents the rule ([engines/01 §3.6](engines/01-infralume.md)) |

### 2.2 `telemetry.metrics` — key: `service, component, name, t_ns`

Labels that distinguish series (for example per-endpoint or per-status-code) are folded into `name` by the adapter, so the key stays unique; `attrs_json` keeps the remaining labels for display only.

| Column | Type | Notes |
|---|---|---|
| `t_ns` | int64 | |
| `service` | str | normalised name (lowercase, no pod hash; name pattern §1) |
| `component` | str | container/pod/db name; equals `service` if unknown |
| `name` | str | original metric name after scrubbing. The adapter may rewrite it: distinguishing labels encoded as `name{k=v,…}` (sorted keys), `_total` appended to monotonic sums, histograms split into `<name>_count` and `<name>_sum` ([engines/01 §3.9](engines/01-infralume.md)). No pattern |
| `metric_type`? | str | `gauge \| counter \| histogram_bucket \| summary \| unknown` (OTLP-native when known) |
| `attrs_json`? | str | canonical JSON of remaining labels, scrubbed |
| `value` | float64 | |
| `unit`? | str | |
| `source_system` | str | `prom \| otlp \| csv` (synthetic cases use `prom`) |

### 2.3 `telemetry.logs` — key: `service, t_ns, body`

The key is not unique: writers do not reject repeated keys (§1 Sorting).

| Column | Type | Notes |
|---|---|---|
| `t_ns` | int64 | |
| `service`, `component` | str | |
| `severity`? | str | `TRACE \| DEBUG \| INFO \| WARN \| ERROR \| FATAL` |
| `body` | str | scrubbed |
| `trace_id`?, `span_id`? | str | |
| `attrs_json`? | str | canonical JSON, scrubbed |

### 2.4 `telemetry.spans` — key: `trace_id, start_ns, span_id`

| Column | Type | Notes |
|---|---|---|
| `trace_id`, `span_id` | str | free strings (no hex pattern) |
| `parent_span_id`? | str | null for a root span, never `""` |
| `service` | str | |
| `component`? | str | Infralume decides between null and a component name |
| `operation` | str | |
| `kind` | str | `server \| client \| internal \| producer \| consumer \| unspecified`; Infralume writes `unspecified` when the source has no kind |
| `start_ns`, `end_ns` | int64 | |
| `status` | str | `ok \| error \| unset` |
| `status_code`? | int32 | HTTP or gRPC code; error rule in [engines/01-infralume](engines/01-infralume.md) |
| `attrs_json`? | str | scrubbed |

### 2.5 `telemetry.events` — key: `t_ns, entity, kind`

The key is not unique: writers do not reject repeated keys (§1 Sorting).

| Column | Type | Notes |
|---|---|---|
| `t_ns` | int64 | |
| `entity` | str | service or component |
| `kind` | str | `event_kind` |
| `source_system` | str | `k8s \| flagd \| git \| ci \| manual \| synthetic` |
| `detail_json` | str | canonical JSON object (e.g. `{"image":"…","from":"…","to":"…"}`); `flag` events carry `{"flag": <8 hex>, "from": …, "to": …}` (shape to be confirmed by Observe and Explain) |
| `actor`? | str | |

### 2.6 `alert.json` (produced by core's alert step, pipeline step 1)

| Field | Type | Notes |
|---|---|---|
| `schema_version` | str | |
| `protocol` | str | `oracle \| detected \| live` |
| `t_alert_ns` | int | after `alert.shift_s` is applied: `t_alert_ns = base + shift_ns` exactly, under every protocol (base = the hint for `oracle`/`live`, the detected breach for `detected`) |
| `shift_ns` | int | `alert.shift_s` (an integer number of seconds) × 10⁹; 0 unless an onset-shift robustness run |
| `detector`? | {`entry_services`: [str], `signal`: str, `threshold`: float} | non-null if and only if `protocol = detected`; `entry_services` sorted |
| `windows.baseline` | [int, int] | ns, clamped to available data; half-open `[start, end)`, exactly two int64 values, `start ≤ end` |
| `windows.incident` | [int, int] | same form as `baseline`; the two windows may be contiguous |
| `clamped` | bool | true if either window was shortened |

---

## 3. Signalyth outputs

### 3.1 `signal_cube.series` — key: `series_id, t_ns`

| Column | Type | Notes |
|---|---|---|
| `series_id` | str | `"{service}\|{component}\|{signal}\|{source}"`; each part matches `^[^\|]+$`, and the writer checks that the parts equal the row's columns |
| `service`, `component` | str | |
| `signal` | str | free string. Names Signalyth emits: `cpu`, `mem`, `disk`, `diskio`, `net`, `socket`, `latency`, `latency_p{q}`, `error`, `rps`, `workload`, `error_rate`, `self_time_p50`, `self_time_p99`, `log_rate`, `log_error_rate`, `tmpl:{template_id}` ([engines/02](engines/02-signalyth.md)) |
| `family` | str | closed vocabulary |
| `klass` | str | closed vocabulary |
| `source` | str | `metrics \| logs \| traces` (subset of `source`) |
| `unit`? | str | free string; canonical units are `ms`, `bytes`, `ratio`, `1/s`, `count` and `<unit>/s` for counter rates |
| `t_ns` | int64 | metrics: native observation time (a counter's rate is written at the later point `t₂` of each pair); traces and logs: bucket start on the epoch-aligned 10 s grid. The step is not stored; consumers infer it from `t_ns` ([engines/02 §3.1](engines/02-signalyth.md)) |
| `value` | float64 | |

### 3.2 `signal_cube.edges` — key: `caller, callee, window`

| Column | Type | Notes |
|---|---|---|
| `caller`, `callee` | str | services |
| `window` | str | `baseline \| incident` |
| `calls` | int64 | ≥ 1 (rows with `calls = 0` are not written) |
| `error_rate` | float64 | ∈ [0, 1] |
| `p50_caller_ms`, `p99_caller_ms` | float64? | client-observed duration; null when no client span |
| `p50_callee_ms`, `p99_callee_ms` | float64? | server-side duration |
| `p50_gap_ms`, `p99_gap_ms` | float64? | caller − callee; null when no client span |

Every quantile column is also null when the pair has fewer samples than Signalyth's minimum (`traces.min_spans_per_quantile`, [engines/02 §3.3](engines/02-signalyth.md)). Rows with `calls = 0` are omitted, so a (caller, callee) pair present in one window and absent in the other has `calls = 0` in the absent window. Consumers must read a missing row that way: a callee that stops answering has `calls = 0` in the incident window, not "no data".

### 3.3 `signal_cube.templates` — key: `service, template_id`

| Column | Type | Notes |
|---|---|---|
| `service` | str | |
| `template_id` | str | `short_id("T", 8, [service, template])`: `T` + first 8 hex of SHA-256 of canonical JSON `[service, template]` (UTF-8, `ensure_ascii=False`) |
| `template` | str | Drain3 template |
| `count_baseline`, `count_incident` | int64 | |
| `error_level` | bool | any line at ERROR/FATAL or matching error lexicon |
| `first_seen_ns` | int64 | |

### 3.4 `signal_cube.critical_path` — key: `window, service`

| Column | Type | Notes |
|---|---|---|
| `window` | str | `baseline \| incident` |
| `service` | str | |
| `traces` | int64 | traces where the service is on the critical path |
| `cp_self_ms_p50`, `cp_self_ms_p99` | float64 | self time on the critical path; 0.0 when `traces = 0` (Signalyth to confirm) |
| `cp_share_mean` | float64 | mean share of end-to-end latency (0–1), averaged over all `traces_total` eligible traces of the window (a trace without this service counts as 0) |
| `traces_total` | int64 | eligible traces in the window after the per-window trace cap (`cp.max_traces_per_window`); same value on every row of that window |
| `traces_slow` | int64 | traces on which this service is on the critical path **and** the trace is slow (end-to-end latency above the baseline p95 of its entry operation) |
| `cp_share_sum_slow` | float64 | sum of this service's critical-path share over slow traces (spectrum numerator for `cp_sbfl`) |

A window has rows only for services seen in its eligible traces (Signalyth to confirm).

---

## 4. Anomara outputs

### 4.1 `anomalies` — key: `series_id, detector`

| Column | Type | Notes |
|---|---|---|
| `series_id`, `service`, `component`, `family`, `klass`, `source` | str | copied from series (`source` ∈ `metrics \| logs \| traces`) |
| `detector` | str | `robust_z \| nsigma \| bocpd \| silence \| tsfm` |
| `score` | float64 | detector-native, ≥ 0 |
| `score_norm` | float64 | log1p-compressed, scale-floored (comparable across series). Per detector ([engines/03](engines/03-anomara.md)): `robust_z` = `log1p(score)` exactly (§3.2); `nsigma` = `log1p` of the deviation over the floored scale `max(σ_B, ε, η·\|μ_B\|)` (§3.3); `bocpd` = `log1p(score)` (§3.4); `silence` = `log1p(score)` (§3.5); `tsfm` as defined in §3.9 |
| `direction` | str | `up \| down \| flat` |
| `onset_ns`? | int64 | |
| `threshold` | float64 | |
| `above_threshold` | bool | every series gets one row per detector (even below threshold), so evidence can be recomputed |

### 4.2 `onsets.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version` | str | |
| `t_onset_ns` | int | incident onset ([02 §6.3](02-architecture.md)) |
| `method` | str | `second_external \| single_external \| t_alert_fallback` (default rule: `second_external`; fallbacks when fewer external onsets exist) |
| `slo_breach_ns`? | int | first entry-service SLO breach: `alert.t_alert_ns − alert.shift_ns` if `alert.protocol = detected`, else null |
| `entry_services` | [str] | sorted; may be empty |
| `per_service` | [{`service`, `external_onset_ns`?, `external_onset_source`?, `internal_onset_ns`?, `internal_onset_source`?, `silent`: bool}] | sorted by `service`; one entry for every `case_manifest.services` entry; `*_source` ∈ `metrics \| logs \| traces`, so Causync's per-source offsets can be applied; a `*_source` is null if and only if its onset is null |

All onset times are in source time (before Causync's alignment offsets).

---

## 5. Causync outputs

### 5.1 `alignment.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version` | str | |
| `reference` | str | `traces` if present, else `metrics` (also for a logs-only case) |
| `offsets` | [{`source`, `service`?, `offset_ns`, `method`, `confidence`}] | add `offset_ns` to source times to align; `source` uses the full `source` vocabulary (including `events`); the `service` key is always present and null for a source-level offset; `offset_ns` is an integer, rounded half-to-even; `confidence` ∈ [0, 1]; `method` ∈ `reference \| trace_pairs \| log_span_join \| comovement \| none`; sorted by (`source`, `service`) with null service first |
| `tolerance_ns` | int | coarsest step among present sources; 0 if no stepped source is present |

### 5.2 `changes` — key: `t_ns, entity, change_id`

| Column | Type | Notes |
|---|---|---|
| `change_id` | str | `short_id("C", 10, {t_ns, entity, kind, source_system, detail_json, actor})`: `C` + first 10 hex of SHA-256 of that canonical JSON object, over the original event fields (`t_ns` before alignment, `detail_json` hashed as its string); duplicate IDs are collapsed |
| `t_ns` | int64 | aligned |
| `entity` | str | |
| `kind` | str | `event_kind` (full vocabulary) |
| `scope` | str | `service \| component \| cluster` |
| `detail_json` | str | |
| `latest_before_onset` | bool | latest change on this entity at or before its onset plus `tolerance_ns`; every change at that matched `t_ns` is flagged (ties are all "latest") |
| `delta_to_onset_ms`? | float64 | `(t_ns − O) / 10⁶`, negative = before onset; null only if there is no onset at all |
| `proximity` | float64 | `exp(−max(0, O − t_ns)/τ_change)` if `t_ns ≤ O + tolerance_ns`, else 0 (a change recorded slightly after the onset, within tolerance, still counts); ∈ [0, 1] |
| `peer_contrast`? | float64 | changed-vs-peer anomaly gap in raw robust z (max `anomalies.score` of `robust_z`); null if the changed set or the peer set is empty, or `scope = cluster` |

`O` is the change's target onset (aligned): the entity's onset for service scope, the onset of the component's service for component scope, `t_onset_ns` for cluster scope ([engines/04 §3.6](engines/04-causync.md)).

---

## 6. Causalith outputs

### 6.1 `graph.nodes` — key: `node`

| Column | Type | Notes |
|---|---|---|
| `node` | str | service, or an external host (name pattern §1) |
| `kind` | str | `service \| db \| cache \| queue \| external \| entry` |
| `is_entry` | bool | receives external traffic |
| `provenance` | list<str> | `traces \| topology \| logs \| metrics`; unique, sorted; may be empty |

### 6.2 `graph.edges` — key: `src, dst`

| Column | Type | Notes |
|---|---|---|
| `src`, `dst` | str | caller → callee |
| `provenance` | list<str> | `traces \| topology \| logs \| metrics`; unique, sorted, at least one element |
| `calls_incident`? | int64 | from traces |
| `weight` | float64 | normalised call share: this edge's incident calls ÷ all incident calls from `src`; the baseline share if `src` has no incident calls; 1.0 if unknown (no trace data) ([engines/05 §3.4](engines/05-causalith.md)) |
| `anomalous`? | bool | edge latency/error anomaly in incident window; null when the edge has no trace data |

### 6.3 `graph.paths` — key: `candidate, path_rank`

| Column | Type | Notes |
|---|---|---|
| `candidate` | str | |
| `path_rank` | int32 | 1 = best |
| `nodes` | list<str> | candidate → … → entry (reverse call direction); at least one element; the order is semantic and never sorted |
| `anomalous_fraction` | float64 | anomalous nodes on the path ÷ nodes on the path, where a node is anomalous if it has an `above_threshold` `anomalies` row from `robust_z` with `klass = external`, or from `silence` with `klass ∈ {external, context}` ([engines/05 §3.6](engines/05-causalith.md)) |

---

## 7. FaultLoom output: `evidence` — key: `candidate, kind, atom_id`

| Column | Type | Notes |
|---|---|---|
| `atom_id` | str | stable ([§1](#1-how-contracts-work)): `E` + first 10 hex of SHA-256 of canonical JSON `[kind, candidate, A]`, where `A` = the defining-arguments object below for engine atoms, and `A = {"args": <canonical predicate args>, "predicate": <name>}` for `claim_check` (so two predicates with equal args never collide). One atom per (predicate, canonical args, candidate); the preimage is pinned by test vectors |
| `candidate` | str | service |
| `component`? | str | |
| `kind` | str | `internal_anomaly \| external_anomaly \| onset_precedence \| propagation \| change_proximity \| peer_contrast \| spectrum \| critical_path_share \| self_time_share \| log_new_template \| log_error_rate \| silence \| edge_gap \| intervention \| claim_check` (`intervention`: Causalith's restricted conditional-independence test for trial T8, computed in the claim pass for decision-pool candidates) |
| `predicate`? | str | library predicate name: null when `origin = engine`, always set for `claim_check` |
| `args_json` | str | canonical JSON object: the kind's defining arguments `A` (table below) for engine atoms; the predicate arguments after the subject for `claim_check`. Kept as a string column |
| `value` | float64 | finite (never NaN or ±inf) |
| `unit`? | str | free string |
| `window` | str | `baseline \| incident \| onset`; for `claim_check`, the predicate's `window` (`contracts/predicates.json`) |
| `refs` | list<str> | sorted, unique; each element is a `series_id`, a `change_id` (`C…`), a `template_id` (`T…`) or `<contract>#<first 12 hex of sha256(canonical_json(row))>` for any other row (e.g. `graph.edges#3f9a0c41d2e7`) |
| `origin` | str | `engine \| claim_check` |
| `holds`? | bool | null when `origin = engine`; for `claim_check`: the predicate result, `true`, `false`, or null (not evaluable) |
| `producer` | str | `faultloom@<version>` |

There is no sources column: the telemetry sources behind an atom (trial T9) are derived by FaultLoom's `atom_sources()` from `refs` and the kind ([engines/06 §3.3](engines/06-faultloom.md)).

Defining arguments `A` per kind (keys of `args_json` for engine atoms; [engines/06 §3.4](engines/06-faultloom.md)):

| Kind | Keys of `A` |
|---|---|
| `internal_anomaly`, `external_anomaly` | `detector`, `family`, `source`, `window` |
| `onset_precedence` | `scope` (`self`, `dependents` or `internal_vs_external`), `window` |
| `propagation` | `scope` (`entry`, `anomalous` or `path`), `window` |
| `change_proximity` | `change_id`, `event_kind`, `window` |
| `peer_contrast` | `source` (`anomalies` or `changes`), `window` |
| `spectrum` | `formula`, `weighting`, `window` |
| `critical_path_share` | `window` |
| `self_time_share` | `quantile`, `window` |
| `log_new_template` | `error_level_only`, `min_count`, `window` |
| `log_error_rate` | `window` |
| `silence` | `window` |
| `edge_gap` | `direction`, `quantile`, `window` |
| `intervention` | `parents_hash`, `series_id`, `window` |
| `claim_check` | `A = {"args", "predicate"}` as above; `args_json` holds only the predicate args |

Predicate library (v0.1; extended only through CCR). The first argument is always the **subject** service; in the claim pass FaultLoom substitutes every pool candidate for it (symmetric evaluation, [02 §2 P2](02-architecture.md)) and writes one `claim_check` atom per (predicate, canonical args, candidate) with `holds` set. Polarity and default weight are fixed here; weights live in `config/causentra.yaml` under `predicates.<name>.weight`.

The machine-readable copy is `contracts/predicates.json`: per predicate only its name, parameter names and types, polarity and window. The generator turns it into `veyltrace_contracts.predicates`. Parameter ranges stay in `config/faultloom.yaml` (so they enter the config lock), and weights stay in `config/causentra.yaml`. A test checks that `predicates.json`, this table and the polarity in FaultLoom's code agree.

| Predicate | Arguments after subject (type) | Polarity | Default weight |
|---|---|---|---|
| `zscore_above` | `signal` (signal), `k` (float) | supports | 0.10 |
| `onset_before` | `other_service` (service) | supports | 0.10 |
| `edge_anomalous` | `callee` (service) | refutes (the subject is a victim of its callee) | 0.10 |
| `self_time_share_above` | `x` (float) | supports | 0.10 |
| `change_before_onset` | `max_ms` (float) | supports | 0.10 |
| `template_new_in_incident` | `min_count` (int) | supports | 0.05 |
| `error_rate_above` | `x` (float) | supports | 0.05 |
| `silent` | — | supports (silence is a symptom of the root, not health) | 0.10 |
| `on_critical_path` | `min_share` (float) | supports | 0.05 |
| `peer_gap_above` | `x` (float) | supports | 0.10 |

Parameter types follow FaultLoom's `Param` ([engines/06 §3.5](engines/06-faultloom.md)): `float`, `int`, `service` (a `graph.nodes.node`), `signal` (a `signal` present in this case's `signal_cube.series`).

### 7.1 `predicates.json` — `contracts/predicates.json` (repo file, maintained by the lead)

| Field | Type | Notes |
|---|---|---|
| `schema_version` | str | `"0.1.0"` |
| `predicates` | list | one entry per predicate of the table above, sorted by `name` |
| `predicates[].name` | str | library predicate name |
| `predicates[].params` | list | the arguments after the subject in call order, each `{name, type}` with `type` ∈ `float \| int \| service \| signal`; empty for `silent` |
| `predicates[].polarity` | str | `supports \| refutes`, as in the table above |
| `predicates[].window` | str | `baseline \| incident \| onset`: the `window` written on this predicate's `claim_check` atoms |

---

## 8. Causatrix output: `slate.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version`, `case_id` | str | `schema_version` `"0.1.0"` |
| `k` | int | default 5 |
| `rankers_active` | [str] | sorted; rankers that abstained are absent; ranker names are free strings (rankers are plugins) |
| `fusion` | {`method`, `k`: int?, `weights`: {ranker: float}} | `method` ∈ `rrf \| combsum_minmax \| borda` (default `rrf`; the others are ablations); `k` is the RRF constant (default 60), null for methods without one; ranker keys are free strings |
| `candidates` | [ {`rank`, `service`, `component`?, `indicator`, `mode`, `fault_class`, `fused_score`, `ranker_ranks`: {ranker: int?}, `ranker_scores`: {ranker: float?}} ] | sorted by `rank`; `rank` = 1…n, unique; length ≤ `k`; may be empty; `indicator` uses the `indicator` vocabulary |
| `all_scores` | [ {`service`, `fused_score`} ] | every service in the universe U, sorted by score desc (rounded to 9 decimals) then name; may be empty — gives Causentra the base score `S0` for proposed candidates outside the top-K, and bench its full ranking |

---

## 9. Relentra outputs

### 9.1 `proposals.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version`, `case_id` | str | |
| `status` | str | `complete \| budget_exhausted \| failed \| skipped` |
| `mode` | str | `brief \| investigate \| external` (`external`: hypotheses submitted through the MCP `verify_hypothesis` tool, [06](06-gateway-and-console.md)) |
| `model`? | {`provider`, `name`, `gguf_sha256`?, `params`: {`temperature`, `seed`, `top_k`?, `top_p`?, `presence_penalty`?, `thinking`?: bool, `max_tokens`}} | null for `mode = external` and for `status = skipped`; `provider` ∈ `ollama \| llamacpp \| openai_compat \| fake`; `seed` is an integer in [0, 2³¹ − 1) |
| `budget_used` | {`turns`, `tokens_in`, `tokens_out`, `wall_ms`} | `wall_ms` is a float; it comes from the cassette in replay, so replays match |
| `proposals` | [ {`proposal_id`, `hypothesis`: {`service`, `component`?, `fault_class`, `indicator`?}, `claims`: [ {`claim_id`, `predicate`, `args`, `cites`: [str]} ], `requested_trials`: [`T1`…`T10`], `rationale`: str ≤ 280 chars} ] | `proposal_id` matches `^P[0-9a-f]{8}$` (preimage in [engines/08 §2.2](engines/08-relentra.md)); `claim_id` = `<proposal_id>-<i>`; `requested_trials` unique, at most 4, sorted by trial number (T1 < T2 < … < T10); `rationale` ≤ 280 Unicode code points, display-only and never read by code |
| `asks` | [ {`kind`: `telemetry \| trial \| context`, `target`, `why`} ] | at most 3, sorted by (`kind`, `target`); `target` ≤ 80 and `why` ≤ 160 characters (the limits of [engines/08 §3.4](engines/08-relentra.md)) |

`service` must be a `graph.nodes.node`; `predicate` must be in the library (§7). `args` holds only the arguments **after** the subject (the subject is the hypothesis `service`, and the claim pass substitutes every pool candidate); a `subject` key in `args` is invalid (`bad_args`). The contract schema keeps `args` permissive (a JSON object of scalar values) and does not check for `subject`: argument problems are per-claim `bad_args` rejections, not schema errors. The JSON schema used for constrained decoding enumerates both per case. `cites` holds atom IDs (`E…`, both modes) or tool-call IDs (`tc:<seq>`, `investigate` mode), each matching `^(E[0-9a-f]{10}|tc:[0-9]+)$`, at most 3 per claim, possibly none; citations are for display and audit, while the decision uses only the claim pass result.

### 9.2 `agent_trace.jsonl` — one JSON object per line

| Field | Type | Notes |
|---|---|---|
| `seq` | int | from 0 |
| `type` | str | `state \| llm_call \| tool_call` |
| `prev_hash` | str | `"0"*64` for `seq = 0` |
| `line_hash` | str | SHA-256 over the bytes: ASCII hex of `prev_hash`, then UTF-8 `canonical_json(line without line_hash)` |
| `request_sha256`?, `response_sha256`? | str | `llm_call` |
| `tool`?, `args`?, `result_sha256`?, `summary`? | | `tool_call` (`tool_call_id` = `seq`) |
| `state`? | str | state-machine transition name, one of `start`, `cards_built`, `prompt_built`, `validated`, `validation_failed`, `repair`, `drop_claim`, `drop_proposal`, `pick`, `stop`, `probe`, `emit`, `budget_turns`, `budget_tokens`, `budget_wall`, `budget_context`, `provider_error`, `cassette_miss`, `done`, `failed` ([engines/08 §5.3](engines/08-relentra.md)) |
| `detail`? | str | free text, may be set only on `state` lines `drop_claim` and `drop_proposal` (why the claim or proposal was dropped); null on every other line |

Every field is present on every line (§1 Nulls). The schema ties the per-type fields to `type` (if/then): `state` lines set `state`; `llm_call` lines set `request_sha256` and `response_sha256`; `tool_call` lines set `tool`, `args`, `result_sha256` and `summary`; the fields of the other types are null.

---

## 10. Causentra output: `verdict.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version`, `case_id`, `run_id` | str | |
| `status` | str | closed vocabulary |
| `root` | {`service`, `component`?, `indicator`, `fault_class`, `mode`} \| null | null for `NO_FAULT` and `INCONCLUSIVE` with no leader |
| `candidate_set` | [ {`service`, `component`?, `v`, `nonconformity`} ] | conformal set, sorted by `v` desc |
| `ranked` | [ {`rank`, `service`, `component`?, `indicator`, `fault_class`, `v`, `nonconformity`, `fused_score`, `origin`: `slate \| proposal`, `trials`: [ {`id`, `result`: `pass \| fail \| untestable`, `reason`?, `atoms`: [atom_id]} ]} ] | all pool candidates, sorted by tie-break rule ([02 §6.9](02-architecture.md)). `nonconformity` (float) is defined as in `candidate_set` ([engines/09 §3.7](engines/09-causentra.md)) and is given for every ranked candidate, so bench reads the true root's calibration score from here. `trials[].id` ∈ `T1`…`T10`, in numeric order; `reason` is null on `pass`, else matches `^[a-z_]+(:[A-Za-z0-9_.,-]+)?$` |
| `confidence` | {`level`: `high \| medium \| low \| none`, `margin`, `alpha`, `q_hat`?, `set_size`} | `q_hat` null means +∞; `margin = (V_top − V_runner-up) / V_top`; level: CONFIRMED → high, LIKELY → medium, INCONCLUSIVE with a leader → low, else none ([02 §6.9](02-architecture.md)). Under `NO_FAULT`, `margin` is computed as usual and `set_size = 0` |
| `asks` | [ {`kind`, `target`, `why`} ] | `kind` ∈ `telemetry \| trial \| context` |
| `ranks_rcaeval` | [str] | `"{service}_{indicator}"`, for RCAEval scoring; covers every service in the universe U, under every status |
| `proposals_accepted` | [str] | proposal IDs, sorted ascending |
| `proposals_rejected` | [ {`proposal_id`, `reason`: `unknown_entity \| unknown_predicate \| bad_args \| claim_false \| trial_failed \| budget`} ] | sorted by `proposal_id`, so the verdict does not depend on proposal order; "admitted" proposals ([engines/09 §3.2](engines/09-causentra.md)) = all proposals minus the admission rejections |
| `calibration` | {`family`, `sha256`} | `family` = the calibration `family_id` (§12.1) or `"uncalibrated"`; `sha256` = SHA-256 of the calibration file bytes, or `sha256_json({"family":"uncalibrated"})` when uncalibrated |
| `params_sha256` | str | Causentra config section |
| `verdict_hash` | str | SHA-256 of canonical JSON of this object without `verdict_hash` and without `run_id` (the hash never depends on `run_id`) |

---

## 11. Causivra outputs

### 11.1 `card.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version`, `case_id`, `verdict_hash` | str | |
| `title` | str | |
| `status`, `root`, `confidence` | | copied from verdict; same definitions as the verdict's (the card schema references the verdict schema's `$defs`) |
| `candidate_set` | [ {`service`, `component`?} ] | copied from verdict; always present, may be empty (empty for `NO_FAULT`) |
| `summary` | [ {`text`, `cites`: [atom_id]} ] | filled text (no placeholders); `cites` may be empty |
| `timeline` | [ {`t_ns`, `label`, `cites`} ] | sorted by (`t_ns`, `label`); `cites` may be empty |
| `path` | [str] | propagation path |
| `evidence_table` | [ {`atom_id`, `label`, `value`?, `unit`?} ] | `value` is the raw float (number or null) |
| `why_not` | [ {`service`, `text`, `cites`} ] | runner-ups |
| `asks` | [ {`text`} ] | |
| `next_steps` | [ {`text`, `playbook_id`} ] | deterministic playbooks; `playbook_id` matches `^PB-[A-Z]+-[0-9]{2}$` |
| `narrator` | {`path`: `llm \| template`, `model`?, `attempts`, `checker_failures`} | |
| `card_hash` | str | SHA-256 of the canonical JSON of this object without `card_hash` |

### 11.2 `receipt.json` (in-toto Statement v1)

```json
{
  "_type": "https://in-toto.io/Statement/v1",
  "subject": [{"name": "verdict.json", "digest": {"sha256": "<verdict file sha256>"}}],
  "predicateType": "https://veyltrace.dev/rca-verdict/v1",
  "predicate": {
    "run_manifest": { "...": "see §12" },
    "verdict_hash": "<64 hex>",
    "card_hash": "<64 hex>",
    "agent_trace_head": "<line_hash of last line or null>"
  }
}
```

The receipt keeps the in-toto shape: it has no `schema_version` (its version is `predicateType`); `subject` has exactly one entry, whose `name` is the constant `"verdict.json"`; `agent_trace_head` is nullable (null when the run has no `agent_trace`).

---

## 12. Core output: `run_manifest.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version`, `run_id`, `case_id`, `dataset` | str | |
| `code` | {`commit`, `dirty`: bool} | dirty runs are marked and never used for paper tables |
| `env` | {`python`, `os`, `libs`: {name: version}} | sorted. Replay exit 5 compares only Python major.minor, `libs` and `uv_lock_sha256`; `os` is reported, never compared (a Windows-recorded receipt must replay on Linux CI) |
| `config_sha256`, `uv_lock_sha256`, `calibration_sha256` | str | `config_sha256` is the hash of `config.lock.json` (the fully resolved config, written into the run dir; §12.2). `calibration_sha256` is the calibration file's SHA-256, or the sentinel `sha256_json({"family":"uncalibrated"})` when uncalibrated (the same value as `verdict.calibration.sha256`) |
| `inputs` | [ {`name`, `sha256`} ] | from `case_manifest.inputs`; relative POSIX paths, sorted by `name` |
| `outputs` | [ {`name`, `sha256`} ] | every artifact in the run dir except `run_manifest.json`, `receipt.json` and `receipt.json.minisig`; relative POSIX paths, sorted by `name`; includes `config.lock.json`, `card.md`, `agent_trace.jsonl` and every cassette file |
| `ai` | {`mode`, `provider`?, `model`?, `gguf_sha256`?, `prompt_sha256`?, `schema_sha256`?, `cassette_sha256`?} | `mode` ∈ `ai_mode`. When several engines call an LLM, core merges their reports: `prompt_sha256` and `schema_sha256` are `manifest_hash` over every engine's `<engine>/<name>` entries, `provider`, `model` and `gguf_sha256` must agree across engines, and `cassette_sha256` is `manifest_hash` over `cassette/**`. With AI off: `{"mode": "off"}` and every other field null |
| `steps` | [ {`name`, `status`, `outputs`: [ {`name`, `sha256`} ]} ] | one entry per pipeline sub-step that ran before this manifest was written, in pipeline order. `name` is one of the 14 sub-step names, in order `infralume`, `alert`, `signalyth`, `anomara`, `causync`, `causalith`, `faultloom`, `causatrix`, `relentra`, `faultloom.claim_pass`, `causentra`, `causivra.card`, `manifest`, `causivra.receipt`; the list ends with `manifest`, because `causivra.receipt` runs afterwards. `status` is the step's `EngineResult.status` (`ok \| degraded \| skipped \| failed`; a failed step stops the run, so no manifest is written). `outputs` lists the files that sub-step wrote, in the same form as `outputs` above, sorted by `name`; empty for a skipped step; the `manifest` entry lists only `config.lock.json`. Reuse and replay compare per-step hashes (e.g. `evidence.parquet` after `faultloom` and after `faultloom.claim_pass`) |

No timestamps or timings anywhere in the manifest (P3); bench measures cost outside the artifacts. Order at the end of a run: Causivra writes `card` (step 10a) → core writes `config.lock.json` and `run_manifest.json` → Causivra writes `receipt.json` (step 10b).

### 12.1 `calibration` — `config/calibration/<family_id>.json` (written by bench, read by Causentra via `ctx.config`)

`family_id` = `<benchmark family>.<ai_arm>.<alert_protocol>.<fold>` (always four dot-separated parts), e.g. `rcaeval-re2.brief.oracle.foldA`. The per-system (Mondrian) variant puts the system into the first part (`<family>-<system>`, e.g. `rcaeval-re2-ob.brief.oracle.foldA`); the leave-one-system-out variant puts it into the fold part (`loso-<system>`, e.g. `rcaeval-re2.brief.oracle.loso-ob`) ([04 §5](04-evaluation-protocol.md)). One file per combination; Causentra treats a file whose arm or protocol does not match the run as a hard error.

| Field | Type | Notes |
|---|---|---|
| `schema_version` | str | |
| `family`, `ai_arm`, `alert_protocol` | str | the file applies only to runs with the same arm and protocol; `ai_arm` uses the `ai_arm` vocabulary (§1) |
| `alpha`, `n`, `rank_index` | float, int, int | `rank_index` = ⌈(n + 1)(1 − α)⌉; it may exceed `n` (then `q_hat` is null) |
| `q_hat`? | float | null = +∞ |
| `no_fault` | {`beta`, `m`, `rank_index`, `tau_nf`, `calibrated`: bool, `sources`: [str]} | `sources` ⊆ `synth-05 \| veyllab \| rcaeval_pre_injection`; `rank_index` may exceed `m` |
| `split` | {`seed`, `fold`, `cases_sha256`} | which calibration cases were used (hash only; no labels) |
| `scores_sha256`, `config_sha256`, `code_commit`, `experiment_id` | str | `scores_sha256` hashes the score list with +∞ scores written as `null` |

No per-case labels or case IDs are stored in the file. Fitting rules: [engines/09-causentra §3.7](engines/09-causentra.md) and [04-evaluation-protocol](04-evaluation-protocol.md).

### 12.2 `config_lock` — `config.lock.json` (written by core in the manifest step)

The fully resolved configuration of the run, so replay never depends on the repo's current `config/` files ([02 §4.1](02-architecture.md)). `run_manifest.config_sha256` is its hash, and `run_id` depends on it through `config_sha256`.

| Field | Type | Notes |
|---|---|---|
| `schema_version` | str | `"0.1.0"` |
| `sections` | {section: object} | one entry per config file, keyed by file stem (`core`, the ten engines, `llm`), each the section body after overrides. Every `paths` and `fetch` subtree is left out, and `config/gateway.yaml` never enters the lock. `ai.mode` is a run parameter, not a config key, so it is not in the lock. Path-valued keys are stored unexpanded, as POSIX paths relative to a named root (never absolute, never with backslashes) |
| `calibration`? | {`family_id`, `sha256`, `content`} | the calibration file selected for this run: its `family_id` (§12.1), its SHA-256 (the same value as `run_manifest.calibration_sha256`) and its content (a `calibration` object, §12.1); null when the run is uncalibrated |

---

## 13. Evaluation-only contracts (engines must never read these)

### 13.1 `answer_key` — key: `case_id`

| Column | Type | Notes |
|---|---|---|
| `case_id`, `dataset` | str | |
| `system`? | str | `system` vocabulary (§2.1) |
| `is_no_fault` | bool | |
| `root_service`?, `root_component`?, `fault_class`? | str | `fault_class` vocabulary (§1) |
| `fault_label`? | str | the dataset's raw fault label, before mapping to `fault_class` |
| `indicator`? | str | `indicator` vocabulary (§1) |
| `mode`? | str | `mode` vocabulary (§1) |
| `t_inject_ns`?, `t_end_ns`? | int64 | |
| `injection_json`? | str | tool + parameters: canonical JSON `{fault_id, tool, tool_version, params, severity, seed}` |
| `extra_roots_json`? | str | multi-fault cases |
| `decoy_changes_json`? | str | RCAEval-C decoys: canonical JSON `[{t_ns, entity, kind, is_true}]` |
| `validated`? | bool | lab cases: user-facing latency or error rate actually moved ([05](05-fault-lab-and-dataset.md)) |
| `sli_impact_json`? | str | lab cases: measured entry-service SLI change |

Normal windows (e.g. RCAEval pre-injection segments, [04 §5](04-evaluation-protocol.md)) have no answer-key rows of their own: they are keyed by the case's `case_id` plus the bench `variant` column of §13.2.

### 13.2 `bench_result`

`bench/results/<experiment_id>/per_case.csv` — UTF-8 CSV (committed to git, diffable; released with the paper), sorted by key `case_id, method, seed, variant` (unique). Columns: `case_id`, `dataset`, `system`, `method`, `ai_mode`, `seed` (empty = a deterministic method), `variant` (bench variant of the case, e.g. `shift-510` for an RCAEval normal window, `perm-3` for a proposal permutation; empty = the unperturbed run), `fold`, `protocol`, `run_outcome` (`ok | failed | timeout | no_alert | rejected`), `pool_hit` (truth in decision pool), `shift_s`, `sources_dropped` (`;`-joined), `status`, `ranks` (`;`-joined; empty for an unranked or non-`ok` run, [04 §7](04-evaluation-protocol.md)), `hit_at_1`, `hit_at_3`, `hit_at_5`, `retrieval_hit` (truth in slate), `fault_class_hit`, `in_set`, `set_size`, `onset_error_ms`, `decoy_present`, `decoy_ranked_first`, `wall_ms`, `peak_rss_mb`, `tokens_in`, `tokens_out`, `verdict_hash`. Booleans are `0/1`; missing values are empty. `run_outcome` comes from the run's outcome (`ok`, `failed`, `no_alert`, `rejected`; `rejected` covers cases that were not run, invalid cases and unsupported formats), except `timeout`, and `failed` for an `ok` run that wrote no verdict or slate, which bench sets itself ([04 §7](04-evaluation-protocol.md)).
`bench/results/<experiment_id>/summary.json` — metrics per (dataset, system, method) with bootstrap CIs (from `bench/stats`, O-14; until then "not run", [04 §9](04-evaluation-protocol.md)); `manifest.json` — the experiment and its hash, the code state, input and config hashes, and the run ids ([04 §9](04-evaluation-protocol.md) lists every field).

---

## 14. API types (gateway)

The gateway's FastAPI app is the source for HTTP types: `run_request`, `run_status`, `case_summary`, `replay_report`, `live_status` and the response wrappers listed in [06-gateway-and-console](06-gateway-and-console.md). Its OpenAPI document is exported to `packages/gateway/openapi.json` by the gateway (Explain lane, so no cross-lane edit is needed), and `scripts/gen_contracts.py` (lead) reads it and generates TypeScript types into `contracts/generated/ts/api/`. Run artifacts inside API responses reuse the schemas above; the API never redefines them. API types follow the same change process (§1) after M1.
