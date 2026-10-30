# 03 · Data contracts

> **Status:** v0.1-draft (frozen as v1.0 at milestone M1) · **Owner:** lead (file), producer lane (semantics) · **Last updated:** 2026-10-30
> Master spec: [02-architecture](02-architecture.md). This doc is the field-level truth for every artifact that crosses a package boundary. If a field is not here, no engine may rely on it.

## 1. How contracts work

| Item | Rule |
|---|---|
| Source of truth | `contracts/schemas/<name>.schema.json` (JSON Schema 2020-12). This doc and the schemas must match; the schemas are written from this doc in task `R-01` (see [07-roadmap](07-roadmap.md)). |
| Generated code | `contracts/generated/python/veyltrace_contracts/` (Pydantic v2) and `contracts/generated/ts/` (TypeScript). Regenerate with `uv run python scripts/gen_contracts.py`. Never edit by hand. CI fails if regeneration produces a diff. |
| Versioning | Every schema has `$id: https://veyltrace.dev/schemas/<name>/<major>.<minor>`. JSON artifacts carry `"schema_version": "<major>.<minor>.<patch>"`. Parquet files carry the key `veyltrace.schema` = `<name>/<version>` in file metadata. |
| Before M1 | `0.x`: the lead may change fields after posting in the team channel and the CCR issue. |
| After M1 (`1.0`) | Additive optional fields only (minor bump), via a Contract Change Request (CCR) issue + ADR + lead approval. Removing or renaming a field needs all three lanes' approval and a major bump. |
| Golden fixtures | Producer ships outputs for `synth-01` … `synth-05` in `packages/<producer>/fixtures/<case>/`. Consumers load them via `veyltrace_core.testing.golden("<contract>", "<case>")`. |
| Units | Time: int64 **nanoseconds** since Unix epoch (UTC), suffix `_ns`. Durations in JSON: `_ms` (float). Scores: unitless float. |
| Identifiers | `case_id` = first 12 hex of SHA-256(original folder name or capture id). `run_id` = first 16 hex of SHA-256(case_id, config_sha256, code_commit, ai.mode). `atom_id` = `E` + first 10 hex of SHA-256(kind, candidate, canonical args). |
| Hashes | Lowercase 64-hex SHA-256, no prefix. `canonical_json`: sorted keys, `(",", ":")` separators, UTF-8, floats rounded to 9 decimals, NaN/Inf → `null`. |
| Nulls | A column is nullable only if this doc marks it `?`. |
| Parquet hashes | File bytes depend on the writer (pyarrow version, compression). Hashes are compared only within one pinned environment; a different pyarrow version is "environment drift" (replay exit 5), not a mismatch. |
| Sorting | Every Parquet table is written sorted by its **key** column list (given per table). JSON arrays are sorted as stated. |

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
| `run_manifest` | JSON | core | Causivra, bench |
| `receipt` | JSON | Causivra | `veyltrace replay`, gateway |
| `calibration` | JSON (`config/calibration/<family>.json`) | bench | Causentra (via `ctx.config`) |
| `answer_key` | Parquet | bench / lab | **bench only** |
| `bench_result` | CSV + JSON | bench | paper tables |
| API types (§14) | OpenAPI → TS | gateway | console, MCP clients |

Gateway and console may read every run artifact above for display; they never write them.

Closed vocabularies used below:

- `family`: `cpu | mem | disk | net | latency | errors | traffic | logs | self_time | other`
- `klass`: `internal | external | context`
- `mode`: `resource | network | code | change | dependency | unknown`
- `fault_class`: `cpu | mem | disk | socket | delay | loss | error | exception | availability | config | dependency | unknown` (`socket`: RCAEval RE2 socket exhaustion; `availability`: pod kill, container restart, pod failure)
- `source`: `metrics | logs | traces | events`
- `event_kind`: `deploy | config | flag | scale | restart | k8s_event | commit | other`
- `status` (verdict): `CONFIRMED | LIKELY | INCONCLUSIVE | NO_FAULT`

---

## 2. Infralume outputs

### 2.1 `case_manifest.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version` | str | `"0.1.0"` |
| `case_id` | str | 12 hex |
| `dataset` | str | e.g. `synth`, `re1-ob`, `re2-ob`, `re2-ss`, `re2-tt`, `re3-ob`, `nezha-ob`, `fse26-tt`, `veyllab-ob`, `veyllab-otel`, `live` |
| `system` | str | `ob \| ss \| tt \| otel \| other` |
| `t_alert_hint_ns`? | int | set only when the run's `alert.protocol` is `oracle` (the dataset's published injection time) or `live` (trigger time); null under `detected`, so the injection time never reaches engines in detected runs. Only core's alert step reads it ([02 §5.1](02-architecture.md)). |
| `hint_source` | str | `oracle \| live \| none`; `none` whenever `t_alert_hint_ns` is null (including every detected-protocol run) |
| `data_start_ns`, `data_end_ns` | int | span of available data |
| `sources` | object | `{metrics: bool, logs: bool, traces: bool, events: bool}` |
| `services` | [str] | sorted A→Z |
| `inputs` | [{`name`, `sha256`, `bytes`}] | sorted by `name`; `name` is relative and never contains the original folder name |
| `adapter` | {`name`, `version`} | |
| `scrub` | {`rules_version`, `dropped_attributes`, `dropped_rows`} | counts |

### 2.2 `telemetry.metrics` — key: `service, component, name, t_ns`

Labels that distinguish series (for example per-endpoint or per-status-code) are folded into `name` by the adapter, so the key stays unique; `attrs_json` keeps the remaining labels for display only.

| Column | Type | Notes |
|---|---|---|
| `t_ns` | int64 | |
| `service` | str | normalised name (lowercase, no pod hash) |
| `component` | str | container/pod/db name; equals `service` if unknown |
| `name` | str | original metric name after scrubbing |
| `metric_type`? | str | `gauge \| counter \| histogram_bucket \| summary \| unknown` (OTLP-native when known) |
| `attrs_json`? | str | canonical JSON of remaining labels, scrubbed |
| `value` | float64 | |
| `unit`? | str | |
| `source_system` | str | `prom \| otlp \| csv` |

### 2.3 `telemetry.logs` — key: `service, t_ns, body`

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
| `trace_id`, `span_id` | str | |
| `parent_span_id`? | str | |
| `service` | str | |
| `component`? | str | |
| `operation` | str | |
| `kind` | str | `server \| client \| internal \| producer \| consumer \| unspecified` |
| `start_ns`, `end_ns` | int64 | |
| `status` | str | `ok \| error \| unset` |
| `status_code`? | int32 | HTTP or gRPC code; error rule in [engines/01-infralume](engines/01-infralume.md) |
| `attrs_json`? | str | scrubbed |

### 2.5 `telemetry.events` — key: `t_ns, entity, kind`

| Column | Type | Notes |
|---|---|---|
| `t_ns` | int64 | |
| `entity` | str | service or component |
| `kind` | str | `event_kind` |
| `source_system` | str | `k8s \| flagd \| git \| ci \| manual \| synthetic` |
| `detail_json` | str | canonical JSON (e.g. `{"image":"…","from":"…","to":"…"}`) |
| `actor`? | str | |

### 2.6 `alert.json` (produced by core's alert step, pipeline step 1)

| Field | Type | Notes |
|---|---|---|
| `schema_version` | str | |
| `protocol` | str | `oracle \| detected \| live` |
| `t_alert_ns` | int | after `alert.shift_s` is applied |
| `shift_ns` | int | 0 unless an onset-shift robustness run |
| `detector`? | {`entry_services`: [str], `signal`, `threshold`} | set for `detected` |
| `windows.baseline` | [int, int] | ns, clamped to available data |
| `windows.incident` | [int, int] | ns, clamped to available data |
| `clamped` | bool | true if either window was shortened |

---

## 3. Signalyth outputs

### 3.1 `signal_cube.series` — key: `series_id, t_ns`

| Column | Type | Notes |
|---|---|---|
| `series_id` | str | `"{service}\|{component}\|{signal}\|{source}"` |
| `service`, `component` | str | |
| `signal` | str | e.g. `cpu`, `mem`, `latency_p99`, `error_rate`, `rps`, `self_time_p99`, `log_error_rate`, `tmpl:{template_id}` |
| `family` | str | closed vocabulary |
| `klass` | str | closed vocabulary |
| `source` | str | `metrics \| logs \| traces` |
| `unit`? | str | |
| `t_ns` | int64 | bucket start |
| `value` | float64 | |

### 3.2 `signal_cube.edges` — key: `caller, callee, window`

| Column | Type | Notes |
|---|---|---|
| `caller`, `callee` | str | services |
| `window` | str | `baseline \| incident` |
| `calls` | int64 | |
| `error_rate` | float64 | |
| `p50_caller_ms`, `p99_caller_ms` | float64? | client-observed duration |
| `p50_callee_ms`, `p99_callee_ms` | float64? | server-side duration |
| `p50_gap_ms`, `p99_gap_ms` | float64? | caller − callee; null when no client span |

### 3.3 `signal_cube.templates` — key: `service, template_id`

| Column | Type | Notes |
|---|---|---|
| `service` | str | |
| `template_id` | str | `T` + first 8 hex of SHA-256(service, template) |
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
| `cp_self_ms_p50`, `cp_self_ms_p99` | float64 | self time on the critical path |
| `cp_share_mean` | float64 | mean share of end-to-end latency (0–1) |
| `traces_total` | int64 | eligible traces in the window after the per-window trace cap (`cp.max_traces_per_window`); same value on every row of that window |
| `traces_slow` | int64 | traces on which this service is on the critical path **and** the trace is slow (end-to-end latency above the baseline p95 of its entry operation) |
| `cp_share_sum_slow` | float64 | sum of this service's critical-path share over slow traces (spectrum numerator for `cp_sbfl`) |

---

## 4. Anomara outputs

### 4.1 `anomalies` — key: `series_id, detector`

| Column | Type | Notes |
|---|---|---|
| `series_id`, `service`, `component`, `family`, `klass`, `source` | str | copied from series |
| `detector` | str | `robust_z \| nsigma \| bocpd \| silence \| tsfm` |
| `score` | float64 | detector-native, ≥ 0 |
| `score_norm` | float64 | log1p-compressed, scale-floored (comparable across series) |
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
| `slo_breach_ns`? | int | first entry-service SLO breach |
| `entry_services` | [str] | sorted |
| `per_service` | [{`service`, `external_onset_ns`?, `external_onset_source`?, `internal_onset_ns`?, `internal_onset_source`?, `silent`: bool}] | sorted by `service`; `*_source` ∈ `metrics \| logs \| traces`, so Causync's per-source offsets can be applied |

---

## 5. Causync outputs

### 5.1 `alignment.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version` | str | |
| `reference` | str | `traces` if present, else `metrics` |
| `offsets` | [{`source`, `service`?, `offset_ns`, `method`, `confidence`}] | add `offset_ns` to source times to align; `method` ∈ `reference \| trace_pairs \| log_span_join \| comovement \| none`; sorted by (`source`, `service`) with null service first |
| `tolerance_ns` | int | coarsest step among present sources |

### 5.2 `changes` — key: `t_ns, entity, change_id`

| Column | Type | Notes |
|---|---|---|
| `change_id` | str | `C` + first 10 hex of SHA-256(row) |
| `t_ns` | int64 | aligned |
| `entity` | str | |
| `kind` | str | `event_kind` |
| `scope` | str | `service \| component \| cluster` |
| `detail_json` | str | |
| `latest_before_onset` | bool | latest change on this entity before its onset |
| `delta_to_onset_ms`? | float64 | negative = before onset |
| `proximity` | float64 | `exp(−Δt/τ_change)` for changes before onset, else 0 |
| `peer_contrast`? | float64 | changed-vs-peer anomaly gap, null if no peers |

---

## 6. Causalith outputs

### 6.1 `graph.nodes` — key: `node`

| Column | Type | Notes |
|---|---|---|
| `node` | str | service |
| `kind` | str | `service \| db \| cache \| queue \| external \| entry` |
| `is_entry` | bool | receives external traffic |
| `provenance` | list<str> | `traces \| topology \| logs \| metrics` |

### 6.2 `graph.edges` — key: `src, dst`

| Column | Type | Notes |
|---|---|---|
| `src`, `dst` | str | caller → callee |
| `provenance` | list<str> | `traces \| topology \| logs \| metrics` |
| `calls_incident`? | int64 | from traces |
| `weight` | float64 | normalised call share (1.0 if unknown) |
| `anomalous`? | bool | edge latency/error anomaly in incident window; null when the edge has no trace data |

### 6.3 `graph.paths` — key: `candidate, path_rank`

| Column | Type | Notes |
|---|---|---|
| `candidate` | str | |
| `path_rank` | int32 | 1 = best |
| `nodes` | list<str> | candidate → … → entry (reverse call direction) |
| `anomalous_fraction` | float64 | share of nodes with external anomaly |

---

## 7. FaultLoom output: `evidence` — key: `candidate, kind, atom_id`

| Column | Type | Notes |
|---|---|---|
| `atom_id` | str | stable ([§1](#1-how-contracts-work)) |
| `candidate` | str | service |
| `component`? | str | |
| `kind` | str | `internal_anomaly \| external_anomaly \| onset_precedence \| propagation \| change_proximity \| peer_contrast \| spectrum \| critical_path_share \| self_time_share \| log_new_template \| log_error_rate \| silence \| edge_gap \| intervention \| claim_check` (`intervention`: Causalith's restricted conditional-independence test for trial T8, computed in the claim pass for decision-pool candidates) |
| `predicate`? | str | library predicate name (always set for `claim_check`) |
| `args_json` | str | canonical JSON of predicate args |
| `value` | float64 | |
| `unit`? | str | |
| `window` | str | `baseline \| incident \| onset` |
| `refs` | list<str> | source row hashes or `series_id`s |
| `origin` | str | `engine \| claim_check` |
| `holds`? | bool | for `claim_check`: predicate result |
| `producer` | str | `faultloom@<version>` |

Predicate library (v0.1; extended only through CCR). The first argument is always the **subject** service; in the claim pass FaultLoom substitutes every pool candidate for it (symmetric evaluation, [02 §2 P2](02-architecture.md)) and writes one `claim_check` atom per (predicate, candidate) with `holds` set. Polarity and default weight are fixed here; weights live in `config/causentra.yaml` under `predicates.<name>.weight`.

| Predicate | Arguments after subject | Polarity | Default weight |
|---|---|---|---|
| `zscore_above` | `signal`, `k` | supports | 0.10 |
| `onset_before` | `other_service` | supports | 0.10 |
| `edge_anomalous` | `callee` | refutes (the subject is a victim of its callee) | 0.10 |
| `self_time_share_above` | `x` | supports | 0.10 |
| `change_before_onset` | `max_ms` | supports | 0.10 |
| `template_new_in_incident` | `min_count` | supports | 0.05 |
| `error_rate_above` | `x` | supports | 0.05 |
| `silent` | — | supports (silence is a symptom of the root, not health) | 0.10 |
| `on_critical_path` | `min_share` | supports | 0.05 |
| `peer_gap_above` | `x` | supports | 0.10 |

---

## 8. Causatrix output: `slate.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version`, `case_id` | str | |
| `k` | int | default 5 |
| `rankers_active` | [str] | sorted; rankers that abstained are absent |
| `fusion` | {`method`: `"rrf"`, `k`: 60, `weights`: {ranker: float}} | |
| `candidates` | [ {`rank`, `service`, `component`?, `indicator`, `mode`, `fault_class`, `fused_score`, `ranker_ranks`: {ranker: int?}, `ranker_scores`: {ranker: float?}} ] | sorted by `rank`; length ≤ `k` |
| `all_scores` | [ {`service`, `fused_score`} ] | every service, sorted by score desc then name — gives Causentra the base score `S0` for proposed candidates outside the top-K, and bench its full ranking |

---

## 9. Relentra outputs

### 9.1 `proposals.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version`, `case_id` | str | |
| `status` | str | `complete \| budget_exhausted \| failed \| skipped` |
| `mode` | str | `brief \| investigate \| external` (`external`: hypotheses submitted through the MCP `verify_hypothesis` tool, [06](06-gateway-and-console.md)) |
| `model` | {`provider`, `name`, `gguf_sha256`?, `params`: {`temperature`, `seed`, `top_k`?, `top_p`?, `presence_penalty`?, `thinking`?: bool, `max_tokens`}} | null fields for `external` |
| `budget_used` | {`turns`, `tokens_in`, `tokens_out`, `wall_ms`} | `wall_ms` comes from the cassette in replay, so replays match |
| `proposals` | [ {`proposal_id`, `hypothesis`: {`service`, `component`?, `fault_class`, `indicator`?}, `claims`: [ {`claim_id`, `predicate`, `args`, `cites`: [str]} ], `requested_trials`: [`T1`…`T10`], `rationale`: str ≤ 280 chars} ] | `rationale` is display-only and never read by code |
| `asks` | [ {`kind`: `telemetry \| trial \| context`, `target`, `why`} ] | |

`service` must be a `graph.nodes.node`; `predicate` must be in the library (§7). `args` holds only the arguments **after** the subject (the subject is the hypothesis `service`, and the claim pass substitutes every pool candidate); a `subject` key in `args` is invalid (`bad_args`). The JSON schema used for constrained decoding enumerates both per case. `cites` holds atom IDs (`E…`, both modes) or tool-call IDs (`tc:<seq>`, `investigate` mode); citations are for display and audit, while the decision uses only the claim pass result.

### 9.2 `agent_trace.jsonl` — one JSON object per line

| Field | Type | Notes |
|---|---|---|
| `seq` | int | from 0 |
| `type` | str | `state \| llm_call \| tool_call` |
| `prev_hash` | str | `"0"*64` for `seq = 0` |
| `line_hash` | str | SHA-256 over the bytes: ASCII hex of `prev_hash`, then UTF-8 `canonical_json(line without line_hash)` |
| `request_sha256`?, `response_sha256`? | str | `llm_call` |
| `tool`?, `args`?, `result_sha256`?, `summary`? | | `tool_call` (`tool_call_id` = `seq`) |
| `state`? | str | state-machine transition name |

---

## 10. Causentra output: `verdict.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version`, `case_id`, `run_id` | str | |
| `status` | str | closed vocabulary |
| `root` | {`service`, `component`?, `indicator`, `fault_class`, `mode`} \| null | null for `NO_FAULT` and `INCONCLUSIVE` with no leader |
| `candidate_set` | [ {`service`, `component`?, `v`, `nonconformity`} ] | conformal set, sorted by `v` desc |
| `ranked` | [ {`rank`, `service`, `component`?, `indicator`, `fault_class`, `v`, `fused_score`, `origin`: `slate \| proposal`, `trials`: [ {`id`, `result`: `pass \| fail \| untestable`, `reason`?, `atoms`: [atom_id]} ]} ] | all pool candidates, sorted by tie-break rule ([02 §6.9](02-architecture.md)) |
| `confidence` | {`level`: `high \| medium \| low \| none`, `margin`, `alpha`, `q_hat`?, `set_size`} | `q_hat` null means +∞; `margin = (V_top − V_runner-up) / V_top`; level: CONFIRMED → high, LIKELY → medium, INCONCLUSIVE with a leader → low, else none ([02 §6.9](02-architecture.md)) |
| `asks` | [ {`kind`, `target`, `why`} ] | |
| `ranks_rcaeval` | [str] | `"{service}_{indicator}"`, for RCAEval scoring |
| `proposals_accepted` | [str] | proposal IDs |
| `proposals_rejected` | [ {`proposal_id`, `reason`: `unknown_entity \| unknown_predicate \| bad_args \| claim_false \| trial_failed \| budget`} ] | |
| `calibration` | {`family`, `sha256`} | |
| `params_sha256` | str | Causentra config section |
| `verdict_hash` | str | SHA-256 of canonical JSON of this object without `verdict_hash` |

---

## 11. Causivra outputs

### 11.1 `card.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version`, `case_id`, `verdict_hash` | str | |
| `title` | str | |
| `status`, `root`, `confidence` | | copied from verdict |
| `candidate_set`? | [ {`service`, `component`?} ] | copied from verdict; empty for `NO_FAULT` |
| `summary` | [ {`text`, `cites`: [atom_id]} ] | filled text (no placeholders) |
| `timeline` | [ {`t_ns`, `label`, `cites`} ] | |
| `path` | [str] | propagation path |
| `evidence_table` | [ {`atom_id`, `label`, `value`, `unit`?} ] | |
| `why_not` | [ {`service`, `text`, `cites`} ] | runner-ups |
| `asks` | [ {`text`} ] | |
| `next_steps` | [ {`text`, `playbook_id`} ] | deterministic playbooks |
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

---

## 12. Core output: `run_manifest.json`

| Field | Type | Notes |
|---|---|---|
| `schema_version`, `run_id`, `case_id`, `dataset` | str | |
| `code` | {`commit`, `dirty`: bool} | dirty runs are marked and never used for paper tables |
| `env` | {`python`, `os`, `libs`: {name: version}} | sorted. Replay exit 5 compares only Python major.minor, `libs` and `uv_lock_sha256`; `os` is reported, never compared (a Windows-recorded receipt must replay on Linux CI) |
| `config_sha256`, `uv_lock_sha256`, `calibration_sha256` | str | `config_sha256` is the hash of `config.lock.json` (the fully resolved config, written into the run dir) |
| `inputs` | [ {`name`, `sha256`} ] | from `case_manifest.inputs` |
| `outputs` | [ {`name`, `sha256`} ] | every artifact in the run dir except `run_manifest.json` and `receipt.json` |
| `ai` | {`mode`, `provider`?, `model`?, `gguf_sha256`?, `prompt_sha256`?, `schema_sha256`?, `cassette_sha256`?} | |

No timestamps anywhere in the manifest (P3). Order at the end of a run: Causivra writes `card` (step 10a) → core writes `config.lock.json` and `run_manifest.json` → Causivra writes `receipt.json` (step 10b).

### 12.1 `calibration` — `config/calibration/<family_id>.json` (written by bench, read by Causentra via `ctx.config`)

`family_id` = `<benchmark family>.<ai_arm>.<alert_protocol>.<fold>`, e.g. `rcaeval-re2.brief.oracle.foldA`. One file per combination; Causentra treats a file whose arm or protocol does not match the run as a hard error.

| Field | Type | Notes |
|---|---|---|
| `schema_version` | str | |
| `family`, `ai_arm`, `alert_protocol` | str | the file applies only to runs with the same arm and protocol |
| `alpha`, `n`, `rank_index` | float, int, int | `rank_index` = ⌈(n + 1)(1 − α)⌉ |
| `q_hat`? | float | null = +∞ |
| `no_fault` | {`beta`, `m`, `rank_index`, `tau_nf`, `calibrated`: bool, `sources`: [str]} | `sources` ⊆ `synth-05 \| veyllab \| rcaeval_pre_injection` |
| `split` | {`seed`, `fold`, `cases_sha256`} | which calibration cases were used (hash only; no labels) |
| `scores_sha256`, `config_sha256`, `code_commit`, `experiment_id` | str | |

No per-case labels or case IDs are stored in the file. Fitting rules: [engines/09-causentra §3.7](engines/09-causentra.md) and [04-evaluation-protocol](04-evaluation-protocol.md).

---

## 13. Evaluation-only contracts (engines must never read these)

### 13.1 `answer_key` — key: `case_id`

| Column | Type | Notes |
|---|---|---|
| `case_id`, `dataset` | str | |
| `is_no_fault` | bool | |
| `root_service`?, `root_component`?, `fault_class`?, `indicator`? | str | |
| `t_inject_ns`?, `t_end_ns`? | int64 | |
| `injection_json`? | str | tool + parameters |
| `extra_roots_json`? | str | multi-fault cases |
| `decoy_changes_json`? | str | RCAEval-C decoys |
| `validated`? | bool | lab cases: user-facing latency or error rate actually moved ([05](05-fault-lab-and-dataset.md)) |
| `sli_impact_json`? | str | lab cases: measured entry-service SLI change |

### 13.2 `bench_result`

`bench/results/<experiment_id>/per_case.csv` — UTF-8 CSV (committed to git, diffable; released with the paper), sorted by key `case_id, method, seed`. Columns: `case_id`, `dataset`, `system`, `method`, `ai_mode`, `seed`, `fold`, `protocol`, `run_outcome` (`ok | failed | timeout | no_alert`), `pool_hit` (truth in decision pool), `shift_s`, `sources_dropped` (`;`-joined), `status`, `ranks` (`;`-joined), `hit_at_1`, `hit_at_3`, `hit_at_5`, `retrieval_hit` (truth in slate), `fault_class_hit`, `in_set`, `set_size`, `onset_error_ms`, `decoy_present`, `decoy_ranked_first`, `wall_ms`, `peak_rss_mb`, `tokens_in`, `tokens_out`, `verdict_hash`. Booleans are `0/1`; missing values are empty.
`bench/results/<experiment_id>/summary.json` — metrics per (dataset, system, method) with bootstrap CIs; `manifest.json` — experiment config hash, code commit, dataset hashes.

---

## 14. API types (gateway)

The gateway's FastAPI app is the source for HTTP types: `run_request`, `run_status`, `case_summary`, `replay_report`, `live_status` and the response wrappers listed in [06-gateway-and-console](06-gateway-and-console.md). Its OpenAPI document is exported to `packages/gateway/openapi.json` by the gateway (Explain lane, so no cross-lane edit is needed), and `scripts/gen_contracts.py` (lead) reads it and generates TypeScript types into `contracts/generated/ts/api/`. Run artifacts inside API responses reuse the schemas above; the API never redefines them. API types follow the same change process (§1) after M1.
