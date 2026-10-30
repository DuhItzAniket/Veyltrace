# 01 · Infralume — ingest any source into one canonical telemetry store and scrub leakage

> Status: v0.1-draft · Lane: Observe · Master: [docs/02-architecture.md §6.1](../02-architecture.md), §4 (step 0), §5.1 · Contracts: [docs/03-contracts.md §2.1–2.5](../03-contracts.md) · Last updated: 2026-10-30

## 1. Purpose and scope

Infralume is the only engine that touches raw data. It reads one case from a benchmark folder, a lab capture or a live snapshot, and writes the canonical tables every other engine reads, over the **full available time span** (pipeline step 0; no windows exist yet). It is also the leakage firewall (P7): after Infralume, no artefact may carry a folder name, an injection label or a fault-injection attribute. The one deliberate exception is the alert hint `t_alert_hint_ns`, written only under the oracle or live protocol and read only by core's alert step (§3.7).

**In scope**

- Adapters: `rcaeval` (RE1, RE2, RE3), `nezha`, `fse26_tt` (format unverified), `veyllab`, `otlp_live`.
- The dataset fetcher behind `veyltrace data fetch <dataset>`.
- Canonical table construction, service-name normalisation, the span error-status rule.
- Leakage scrubbing, the opaque `case_id`, the `sources` map.
- The alert hint: `t_alert_hint_ns` (null under the detected protocol) and `hint_source` in `case_manifest`.
- Robustness hooks (O-09): `sources.drop`, the change-event overlay used by RCAEval-C (§3.10), and the config key `alert.shift_s`, which core's alert step applies.
- The OTLP → canonical converter library used by `veyllab`, the lab's release build and the gateway (O-07).

**Out of scope**

- Choosing `t_alert` and the windows: core's alert step writes `alert.json` (03 §2.6), using Anomara's `detect_alert` under the detected protocol ([03-anomara §3.8](03-anomara.md)).
- Synthetic cases: the `synth` adapter (dataset `synth`) lives in `veyltrace_core.synth` and writes canonical tables and `case_manifest` directly ([02 §6.1](../02-architecture.md)); it registers under the same `veyltrace.adapters` group.
- Any derived signal (rates, quantiles, templates): Signalyth.
- Clock alignment: Causync. Infralume writes source times as given.
- Answer keys. Infralume never writes root-cause service, fault class or injection parameters anywhere, and never reads files under `bench/` or `lab/` ([02 §9](../02-architecture.md), rule 3).

## 2. Inputs and outputs

**Inputs**

| Input | Read by | Notes |
|---|---|---|
| Raw case folder or capture under `${VEYLTRACE_DATA}` | adapter only | located through the private index `${VEYLTRACE_DATA}/index/<dataset>.json` (`case_id → relative path`), written by the fetcher; never copied into a run directory |
| `config/infralume.yaml` | all steps | §4 |
| Optional events overlay file under `${VEYLTRACE_DATA}/overlays/` | §3.10 | written by the RCAEval-C generator (O-13); path given through `events.overlay_path` |

**Outputs** (all fields from [03 §2.1–2.5](../03-contracts.md); writers from `veyltrace_core.io` sort and stamp versions)

| Artefact | Fields written |
|---|---|
| `case_manifest.json` | every field in 03 §2.1: `schema_version`, `case_id`, `dataset`, `system`, `t_alert_hint_ns?`, `hint_source`, `data_start_ns`, `data_end_ns`, `sources`, `services`, `inputs`, `adapter`, `scrub` |
| `telemetry/metrics.parquet` | `t_ns, service, component, name, metric_type?, attrs_json?, value, unit?, source_system` |
| `telemetry/logs.parquet` | `t_ns, service, component, severity?, body, trace_id?, span_id?, attrs_json?` |
| `telemetry/spans.parquet` | `trace_id, span_id, parent_span_id?, service, component?, operation, kind, start_ns, end_ns, status, status_code?, attrs_json?` |
| `telemetry/events.parquet` | `t_ns, entity, kind, source_system, detail_json, actor?` |

A source that is absent or dropped is written as a schema-valid table with zero rows, and its flag in `sources` is `false`. Downstream engines must not be able to tell "absent" from "dropped".

## 3. Algorithm

### 3.1 Two phases

1. **Convert (first time per case).** Adapter reads raw files, builds canonical tables, normalises names, scrubs, and writes them to the cache `${VEYLTRACE_DATA}/cache/<dataset>/<case_id>/`. This phase is excluded from the 30 s budget ([02 §9](../02-architecture.md)); its own target is ≤ 10 s per RE2 case (O-01).
2. **Materialise (every run).** Copy cached tables into the run directory, apply `sources.drop` and the events overlay, read the alert hint (kept only when `alert.protocol` is `oracle` or `live`, §3.7), write `case_manifest.json`. Tables cover the full available span; core's alert step then writes `alert.json`.

Cache entries are keyed by (`case_id`, adapter version, `scrub.rules_version`, config hash of the convert-phase keys). A stale key forces re-conversion.

### 3.2 Opaque `case_id`

`case_id` = first 12 hex of SHA-256 of the **canonical case key** (03 §1). The canonical key is layout-independent, so the same case gets the same ID whichever mirror was downloaded:

| Adapter | Canonical case key |
|---|---|
| `rcaeval` | Hugging Face case name `{suite}{system}_{service}_{fault}_{rep}`, lowercase, e.g. the HF directory name. A Zenodo path `RE2/RE2-OB/<svc>_<fault>/<rep>` is converted to the same string. |
| `nezha` | `nezha-{system}-{date}-{index}` (index = order of the fault in the day's fault list) |
| `fse26_tt` | to define at O-08 |
| `veyllab` | the capture id (already opaque, set by the lab packager) |
| `otlp_live` | the snapshot id written by the gateway |

The canonical key encodes ground truth for RCAEval (the folder name is the label, [rcaeval_facts §Dataset layout][rf-layout]). It exists only inside the adapter and the private index. `case_id` hides it from engines; it is not a secret against a deliberate brute-force over 735 names, and it is not meant to be.

### 3.3 Adapters

All adapters are modules under `veyltrace_infralume.adapters`, registered under the entry-point group `veyltrace.adapters`. Each implements `convert(case_ref, cfg) -> CanonicalCase` and `alert_hint(case_ref) -> tuple[int | None, str]` (`t_alert_hint_ns`, `hint_source`). `veyltrace_core.synth` registers the `synth` adapter in the same group (§1).

**`rcaeval`** — layouts from [rcaeval_facts §Dataset layout][rf-layout]. Detect layout by file presence: HF Parquet (`metrics.parquet`), Zenodo CSV (`simple_metrics.csv`, or `data.csv` for RE1), figshare (`metrics.json`, optional).

| Raw | Canonical mapping |
|---|---|
| metrics, wide (`time` + one column per `{service}_{metric}`) | Unpivot. Split the column name at the **first** `_`: prefix → service (normalised, §3.4), remainder → `name` (e.g. `cpu`, `mem`, `diskio`, `socket`, `workload`, `error`, `latency-50`, `latency-90`). `t_ns = time × 10⁹`. Drop the duplicate `time.1` column. Drop NaN and ±inf points (never forward-fill; RCAEval stores unobserved points as NaN). `unit`: `mem` → `bytes`, `latency-*` → `s`, others null (CPU unit is unverified). `metric_type` and `attrs_json` null (not published). `source_system = prom` (data came from Prometheus queries, [rcaeval_facts §Metric step and windows][rf-step]). Default table: `simple_metrics` / HF `metrics.parquet`; raw Zenodo `metrics.csv` is not read. |
| logs (`timestamp` ns, `container_name`, `message`, optional `level`, `pod_name`, `req_path`, …) | `t_ns = timestamp`. service from `container_name`; `component = pod_name` normalised if present, else service. `severity` from `level` (map `warning→WARN`, `err/error→ERROR`, `critical/fatal→FATAL`, `debug→DEBUG`, `info→INFO`, `trace→TRACE`, else null). `body = message` unchanged (multi-line stack traces stay in one row). `req_path` and other unknown columns → `attrs_json`. The dataset's own `cluster_id` and `log_template` columns are dropped: Signalyth mines its own templates. Never use the `time` "HH:MM" string. |
| traces (`traceID, spanID, parentSpanID, serviceName, methodName, operationName, startTime` µs, `duration` µs, `statusCode`) | `start_ns = startTime × 1000` (fallback `startTimeMillis × 10⁶`); `end_ns = start_ns + duration × 1000`. `parent_span_id` = null when NaN or empty. `operation = methodName` if non-empty else `operationName` (TraceRCA convention). `kind = unspecified` (no kind column). `status_code` = `statusCode` cast to int32, null if NaN. `status` by §3.5. IDs kept as strings (leading zeros preserved). |
| events | none in RCAEval → zero rows, `sources.events = false` |
| `inject_time.txt` | read **only** by `alert_hint()`: `t_alert_hint_ns = seconds × 10⁹`, `hint_source = oracle` (§3.7) |

Never opened by the adapter (enforced by an allow-list of readable file names per layout): `cases.parquet`, `root_cause.txt`, `pod-node-*.csv`, any `*.png`, `*.log`. A header-only `logs.csv` or `traces.csv` means the source is absent ([rcaeval_facts §Data quirks][rf-quirks]).

Hint sanity: if the hint lies outside `[data_start_ns, data_end_ns]` (two RE1-OB cases have broken inject times, [rcaeval_facts §Data quirks][rf-quirks]), Infralume still writes it unchanged and logs a warning; the alert step decides what to do (open question 8).

**`nezha`** — format partially unverified. Notes confirm only: two systems (OB `hipster`, TT `ts`), 101 faults, metrics/logs/traces plus fault-free `construct_data/`, ground truth in `*-fault_list` files and `root_cause_*.json` ([benchmarks_and_testbed §Q1][bt]). Plan for O-08: one case per fault-list entry; slice `[t_fault − 12 min, t_fault + 12 min]` clipped to the midpoint between neighbouring faults (mirrors RCAEval's 12 + 12 min shape, [rcaeval_facts §Metric step and windows][rf-step]). The fault list is read only for its timestamps (slice bounds and the oracle hint); the root-cause fields and `root_cause_*.json` are never opened. Fault-free `construct_data` is not ingested as no-fault cases (open question 6).

**`fse26_tt`** — "format unverified". Zenodo DOI 10.5281/zenodo.17105974, 1,430 cases; size, file format, injection tool and licence not verified ([benchmarks_and_testbed §Q1][bt]). Until R-07 confirms them, the module exists and raises `UnsupportedFormat`. Cut-list item 2 ([07 §1.1](../07-roadmap.md)).

**`veyllab`** — reads a packaged capture from `${VEYLTRACE_DATA}/veyllab/<dataset>/<capture_id>/`, the layout in [05 §9](../05-fault-lab-and-dataset.md): `otlp/{traces,metrics,logs}.jsonl` (protobuf-JSON mapping, already scrubbed by the packager), `events.jsonl` in `telemetry.events` shape, `oracle_alert.json` (`{"t_alert_ns": …}` → hint, `hint_source = oracle`), `capture.json` (`capture_id`, `system`). Raw captures and answer keys stay under `lab/captures/`, which Infralume never reads. Conversion uses the OTLP converter (§3.9); scrubbing is re-applied (idempotent).

**`otlp_live`** — reads a gateway snapshot: canonical-shape Parquet for the four sources plus `snapshot.json` (`snapshot_id`, trigger time). It re-applies normalisation and scrubbing (both idempotent) and writes `t_alert_hint_ns` = trigger time, `hint_source = live`, `dataset = live`. `synth` cases do not go through this reader: `veyltrace_core.synth` registers its own adapter (§1).

### 3.4 Service-name normalisation

Applied to every service, component and entity value, in this order:

1. Trim; lowercase.
2. If the value came from a pod-name field (`pod_name`, `k8s.pod.name`): strip Kubernetes generated suffixes. Deployment pods: `-[bcdfghjklmnpqrstvwxz2456789]{6,10}-[bcdfghjklmnpqrstvwxz2456789]{5}$`; DaemonSet/Job pods: `-[bcdfghjklmnpqrstvwxz2456789]{5}$`; StatefulSet: `-\d+$`. (A priori, from the Kubernetes name generator's vowel-free alphabet; checked against real `pod_name` values at O-01.) The unstripped pod name is kept as `component`.
3. Drop the row if the name is in `normalise.drop_containers` (sidecars such as `istio-proxy`).
4. Apply the per-system alias map, e.g. OB `frontendservice → frontend` (trace vs metric naming, [rcaeval_facts §Dataset layout][rf-layout]).
5. Fold component suffixes: a name ending in a listed suffix (default `-db`) becomes `service = base`, `component = original`. This matches RCAEval's scorer, which strips `-db` ([rcaeval_facts §Ground truth and scoring][rf-scoring]).
6. Replace `_` with `-`. RCAEval ranks use `_` as the service/indicator separator, so a service name must not contain it ([rcaeval_facts §Ground truth and scoring][rf-scoring]).
7. Validate against `^[a-z0-9][a-z0-9.-]*$`; anything else raises `InvalidName` (adapter bug, not data).

Normalisation is idempotent: `n(n(x)) = n(x)` (property test).

### 3.5 Span error-status rule

Let `C` be the set of non-null, non-NaN `status_code` values over all spans of the case.

1. If `C ⊆ {0, 1, 2}`: interpret codes as OTel status (0 unset, 1 ok, 2 error). A span is `error` iff its code is 2.
2. Otherwise, per span: if `code ≥ 100`, HTTP: `error` iff `code ≥ 500`. If `1 ≤ code < 100`, gRPC: `error` (any non-zero gRPC code).
3. `code` null, NaN or 0 is never an error.

`status` = `error` when the rule says so; `ok` when a code is present and not an error (and, under rule 1, the code is 1); `unset` otherwise. For OTLP sources (§3.9) the native OTel status wins: `STATUS_CODE_ERROR → error`; for `UNSET` spans the HTTP/gRPC rule is applied to `http.response.status_code` / `rpc.grpc.status_code`.

Known limit: under rule 1, gRPC `CANCELLED` (1) is read as OTel ok. Rule 1 only fires when no other code appears in the whole case.

Micro-example: codes `{0, 2}` → rule 1, code 2 is error. Codes `{0, 2, 14}` → rule 2, codes 2 and 14 are errors. Codes `{200, 503, 0}` → rule 2, 503 is error, 0 is not.

### 3.6 Leakage scrubbing (P7)

Rules version `scrub.rules_version` (default `scrub-1`); counts go to `case_manifest.scrub`.

| Rule | Applies to | Action |
|---|---|---|
| Deny-listed attribute keys: key starts with `feature_flag.`, or any dot-separated key segment matches `chaos*`, `fault*`, `inject*` (case-insensitive) | `attrs_json`, `detail_json`, OTLP resource and span attributes | drop the attribute; count `dropped_attributes` |
| Fault-tool services: `flagd`, `flagd-ui`, Chaos Mesh components (`scrub.drop_services`) | all telemetry rows | drop rows; count `dropped_rows` |
| Chaos objects in events (any detail key or value containing `chaos`, case-insensitive) | events | drop row |
| Folder tokens: canonical case key, original relative path, original directory names, capture id | every string column and JSON value | replace by `<case>` |
| Flag-change events (`kind = flag`) | events | keep; any flag key in `detail_json` that is not already an 8-hex digest is replaced by the first 8 hex of its SHA-256, the same rule the lab packager applies ([05 §7](../05-fault-lab-and-dataset.md)); kept as decided in [02 §6.1](../02-architecture.md) |

Log bodies are not rewritten except for folder tokens: rewriting words like "fault" would destroy legitimate evidence.

**Scrub test** (O-01, `tests/test_scrub.py`). Builds a raw fixture with planted tokens in attribute keys, bodies, file names, service names and events; runs the adapter; then reads every output (Parquet string columns and JSON) and asserts: (a) no folder token appears anywhere; (b) no key in any `attrs_json`/`detail_json` matches the deny-list; (c) no row has a service, component or entity in `scrub.drop_services`; (d) `scrub` counts equal the planted counts; (e) scrubbing twice equals scrubbing once. The same assertions (a)–(c) run on three real RCAEval cases in the real-data smoke tests, with the real directory names as tokens.

### 3.7 Alert hint and how the alert step uses it

Infralume reads the run's protocol (shared key `alert.protocol` in `config/core.yaml`, via `ctx.config`) only to decide whether the hint may be written. Under `oracle` and `live` it writes what the dataset publishes (first table); under `detected` it writes `t_alert_hint_ns = null` and `hint_source = none`, so the injection time never reaches engines in detected runs ([03 §2.1](../03-contracts.md)). Core's alert step (pipeline step 1, [02 §5.1](../02-architecture.md)) then sets `t_alert` (second table):

| Dataset | `t_alert_hint_ns` (oracle or live protocol) | `hint_source` |
|---|---|---|
| `rcaeval` | `inject_time.txt` × 10⁹ | `oracle` |
| `nezha` | fault-list timestamp of the case | `oracle` |
| `veyllab` | `oracle_alert.json` | `oracle` |
| `otlp_live` | watcher breach time or "Diagnose now" time | `live` |
| `fse26_tt` | to define at O-08 | `oracle` or `none` |
| `synth` | as written by the generator | as written |
| no published time | null | `none` |

| Protocol (alert step) | `alert.t_alert_ns` |
|---|---|
| `oracle` | the hint, copied by core |
| `detected` | Anomara's `detect_alert(telemetry)` on the full-span `telemetry.*` ([03-anomara §3.8](03-anomara.md)); the hint is ignored |
| `live` | the hint |

Core then adds `alert.shift_s` (recorded as `alert.shift_ns`) and computes the clamped windows. Writing telemetry over the full available span is what lets `detect_alert` scan for the first breach.

**Who may read the hint.** Only core's alert step. No Observe engine reads `t_alert_hint_ns`; every engine uses `alert.json`. An Observe test checks the five packages' sources for the field name; under the detected protocol the field is null anyway ([03 §2.1](../03-contracts.md)).

**Why the oracle protocol is not leakage.** It is the RCAEval literature protocol: every published method receives the injection time ([rcaeval_facts §Ground truth and scoring][rf-scoring]). Engines learn one fact — the incident started near `t_alert` — which an on-call alert also gives. They never learn the service, fault class or parameters. The raw injection value appears only as the hint, and under `alert.shift_s` engines cannot tell whether `t_alert` equals the injection time. Onset sensitivity is real (a 2-minute late shift dropped N-Sigma from 0.80 to 0.07 AC@1 on RE2 in one 2026 preprint, [benchmarks_and_testbed §Q2][bt]), which is why both protocols and the shift test are reported.

### 3.8 Manifest fields

- `data_start_ns`, `data_end_ns`: min/max timestamp over all non-dropped sources (span `start_ns`/`end_ns` included).
- `services`: sorted union of normalised services in metrics, logs and spans (events entities that are not telemetry services are excluded).
- `inputs`: one entry per raw file that contributed to a non-empty emitted table, named `<source>/<basename>` (e.g. `traces/traces.parquet`), never containing a folder name; plus `overlay/events.parquet` when an overlay is used.
- `system`: from the adapter (`ob | ss | tt | otel | other`).

### 3.9 OTLP → canonical converter (O-07)

Module `veyltrace_infralume.otlp`: pure functions from decoded `ExportTraceServiceRequest`, `ExportMetricsServiceRequest`, `ExportLogsServiceRequest` (protobuf objects or the protobuf-JSON mapping, [stack_and_market §A1][sm]) to Arrow tables in canonical shape, already normalised and scrubbed. No I/O, no sockets. Used by `veyllab` and by the gateway's live buffer (X-10).

| OTLP | Canonical |
|---|---|
| resource `service.name` | `service` (§3.4) |
| `k8s.pod.name`, else `service.instance.id`, else service | `component` |
| span ids (bytes) | lowercase hex; empty parent → null |
| `SPAN_KIND_*` | `kind` lowercase |
| span name | `operation` |
| status + `http.response.status_code` / `rpc.grpc.status_code` | `status`, `status_code` (§3.5) |
| span attributes (scrubbed) | `attrs_json` (canonical JSON) |
| Gauge point | `value`; `metric_type = gauge` |
| monotonic cumulative Sum | `value`; `metric_type = counter`; name gets suffix `_total` if missing (Prometheus naming, so Signalyth's counter rule applies) |
| Histogram | two series `<name>_count`, `<name>_sum` (`metric_type = counter`); buckets dropped |
| metric point attributes | keys in `otlp.metric_label_keys` are encoded into the name as `name{k=v,…}` (sorted keys) and written to `attrs_json` (scrubbed, canonical JSON); other attributes are dropped and points with equal (`service, component, name, t_ns`) are combined (sum for counters, mean for gauges) |
| log `time_unix_nano` (or `observed_time_unix_nano` if 0) | `t_ns` |
| `severity_number` 1–4/5–8/9–12/13–16/17–20/21–24 | `TRACE/DEBUG/INFO/WARN/ERROR/FATAL` |
| log body (non-string → canonical JSON) | `body` |

The name encoding stays even with `attrs_json?`, because the 03 key (`service, component, name, t_ns`) does not include `attrs_json` and must stay unique (open question 1).

### 3.10 Robustness hooks (O-09)

| Hook | Effect |
|---|---|
| `sources.drop: [logs, …]` | materialise step writes zero-row tables for those sources and sets `sources.<s> = false`; their raw files leave `inputs` |
| `alert.shift_s: <int>` | shared key in `config/core.yaml` (next to `alert.protocol`); O-09 maps the experiment's `protocol.shift_s` ([04 §5.2](../04-evaluation-protocol.md)) to it; **applied by core's alert step**, which records it as `alert.shift_ns`. Infralume does not read it |
| `events.overlay_path` | merges an events file (03 §2.5 shape) produced by the RCAEval-C generator in `bench/decoys/` (O-13). The generator writes overlays to `${VEYLTRACE_DATA}/overlays/<experiment_id>/<case_id>/events.parquet`, never under `bench/` or `lab/`, because Infralume may not read there. Every overlay row gets `source_system = synthetic` and `actor = null`, so no column separates true changes from decoys; entities are normalised and scrubbed; the file is listed in `inputs` as `overlay/events.parquet`; `sources.events = true` if any row survives |

All three come from config, so they change the config hash and therefore `run_id`.

### 3.11 Dataset fetcher

`veyltrace data fetch <dataset> [--suite re2-ob] [--source hf|zenodo] [--cases N]` downloads into `${VEYLTRACE_DATA}` (default `~/veyltrace-data`; the fetcher refuses a target inside the git work tree, so data cannot be committed and nothing lands under `bench/` or `lab/`) and writes `${VEYLTRACE_DATA}/index/<dataset>.json` plus a `fetch.lock.json` with the SHA-256 and size of every file.

| Dataset | Source (from [rcaeval_facts §Downloads and licence][rf-downloads], [benchmarks_and_testbed §Q1][bt]) | Size |
|---|---|---|
| `rcaeval` (default `--source hf`) | Hugging Face `phamquiluan/RCAEval`, file list from the tree API `https://huggingface.co/api/datasets/phamquiluan/RCAEval/tree/main?recursive=true`; files via the standard HF `resolve/main/<path>` URL (verify at O-01) | 3.44 GB total; RE2-SS ≈ 101 MB, RE2-OB ≈ 923 MB, RE2-TT ≈ 1.97 GB |
| `rcaeval --source zenodo` | Zenodo record 14590730, `https://zenodo.org/records/14590730/files/RE2-OB.zip?download=1` pattern | ≈ 5.2 GB zips, ≈ 38 GB extracted |
| `nezha` | GitHub `IntelligentDDS/Nezha` archive at a pinned commit (`rca_data/`, `construct_data/`) | unverified |
| `fse26_tt` | Zenodo DOI 10.5281/zenodo.17105974 | unverified |

`cases.parquet` (the HF ground-truth index) is downloaded only into `${VEYLTRACE_DATA}/rcaeval/answers/` for bench; the adapter's allow-list never opens it. Licence: code MIT; dataset MIT on HF/figshare, CC BY 4.0 on Zenodo — cite the RCAEval paper either way ([rcaeval_facts §Downloads and licence][rf-downloads]).

Isolation: the fetcher needs HTTP, which engines 1–7 must not import (AGENTS §4.3). It lives in `veyltrace_infralume.fetch`, uses only stdlib `urllib.request`, is registered under a `veyltrace.fetchers` entry point consumed by the core CLI, and is never imported by `api.py` or any adapter. It is the single network exemption ([02 §6.1, §9](../02-architecture.md)); the isolation test enforces both rules.

## 4. Configuration — `config/infralume.yaml`

| Key | Default | Unit | Rationale / source |
|---|---|---|---|
| `alert.shift_s` | `0` (in `config/core.yaml`) | s | O-09 hook; shared core key, read and applied by core's alert step, not by Infralume; grid −120…+120 s ([04 §5.2](../04-evaluation-protocol.md)) |
| `sources.drop` | `[]` | — | O-09 telemetry ablation ([04 §5.2](../04-evaluation-protocol.md)) |
| `events.overlay_path` | `null` | path | RCAEval-C overlay from O-13; must be under `${VEYLTRACE_DATA}` |
| `rcaeval.layout` | `auto` | — | `auto \| hf \| zenodo` |
| `rcaeval.metrics_table` | `simple` | — | the table RCAEval's own runner reads ([rcaeval_facts §Dataset layout][rf-layout]) |
| `normalise.aliases` | `{ob: {frontendservice: frontend}}` | — | [rcaeval_facts §Dataset layout][rf-layout] |
| `normalise.component_suffixes` | `["-db"]` | — | RCAEval scorer convention ([rcaeval_facts §Ground truth and scoring][rf-scoring]) |
| `normalise.drop_containers` | `[istio-proxy, istio-init, POD]` | — | a priori; sidecars are not services; verify on RE2 logs |
| `scrub.rules_version` | `scrub-1` | — | bump on any rule change |
| `scrub.deny_key_patterns` | `["feature_flag.*", "chaos*", "fault*", "inject*"]` | — | [02 §6.1](../02-architecture.md) |
| `scrub.drop_services` | `[flagd, flagd-ui, chaos-controller-manager, chaos-daemon, chaos-dashboard, chaos-dns-server]` | — | [02 §6.1](../02-architecture.md); flag-key leak risk [benchmarks_and_testbed §Q3][bt] |
| `status.otel_code_set` | `[0, 1, 2]` | — | §3.5 |
| `status.http_error_min` | `500` | — | §3.5 |
| `otlp.metric_label_keys` | `[http.response.status_code, http.route, rpc.method]` | — | a priori; HTTP stable semconv, RPC release candidate ([stack_and_market §A1][sm]) |
| `duckdb.threads` | `1` | — | deterministic aggregates ([rcaeval_facts §Engineering][rf-eng]) |
| `duckdb.memory_limit` | `1GB` | bytes | share of the 3 GB budget (§8) |
| `fetch.rcaeval.hf_repo` | `phamquiluan/RCAEval` | — | [rcaeval_facts §Downloads and licence][rf-downloads] |
| `fetch.rcaeval.zenodo_record` | `14590730` | — | [rcaeval_facts §Downloads and licence][rf-downloads] |
| `fetch.nezha.commit` | pin at O-08 | — | reproducible fetch |

## 5. Determinism and isolation

- No wall clock: times come from data; the cache key has no timestamps.
- File discovery: list, then sort by relative path (byte order). Never iterate an unsorted glob or `os.listdir`.
- DuckDB `threads = 1` for any aggregate; exact functions only (no `approx_*`).
- Output order is the 03 key; ties (e.g. identical log rows) are broken by all remaining columns.
- `canonical_json` for `attrs_json`, `detail_json` and the manifest.
- Allowed imports: `duckdb`, `pyarrow`, `numpy`, `opentelemetry-proto`/`protobuf` (O-07), stdlib. Banned: any HTTP client, `socket`, LLM clients, `torch`, `transformers`. The `fetch` subpackage is the only network code and is unreachable from `api.py`.
- Infralume never reads `answer_key` files, `cases.parquet`, `root_cause*` files, or fault-list root-cause fields, and never opens a path under `bench/` or `lab/` ([02 §9](../02-architecture.md), rule 3; the isolation test scans for those path literals). Data roots come only from `${VEYLTRACE_DATA}`.

## 6. Missing data and failure behaviour

| Situation | Behaviour |
|---|---|
| Source file missing or header-only | zero-row table, `sources.<s> = false` |
| All four sources empty | `InvalidCase("no_telemetry")` |
| Metric value NaN/inf | point dropped |
| Span with `end < start` | dropped, counted in a structured log line (not an artefact) |
| Span with unknown parent | kept; `parent_span_id` stays as given (Signalyth treats it as an orphan) |
| Duplicate span id within a trace | keep the first in key order, drop the rest, log count |
| Log without timestamp | dropped |
| Unknown severity string | `severity = null` |
| Hint outside the data span | written unchanged, warning logged; alert step decides |
| No published alert time | `t_alert_hint_ns = null`, `hint_source = none` (only the detected protocol can run) |
| `alert.protocol = detected` | `t_alert_hint_ns = null`, `hint_source = none`, whatever the dataset publishes |
| Malformed OTLP payload | `InvalidCapture` naming the file; no partial output |
| Unknown columns | ignored for metrics; stored in `attrs_json` for logs |

## 7. Tests

**Unit**: layout detection; wide→long unpivot and first-`_` split; unit mapping; severity map; error-status rule table (every row of §3.5, including the micro-examples); pod-suffix regexes on real-looking names (and non-matches such as `frontend-proxy`, `ts-ui-dashboard`); alias and `-db` folding; `_`→`-`; canonical case key from HF and Zenodo paths gives one `case_id`; allow-list refuses `cases.parquet`/`root_cause.txt`; hint and `hint_source` per adapter, and both blanked under `alert.protocol = detected`; overlay rewrite of `source_system`/`actor`; flag-key hashing leaves already-hashed keys alone; no Observe package source mentions `t_alert_hint_ns` outside Infralume, or a `bench/`/`lab/` path literal.

**Scrub test**: §3.6.

**Golden (synth-01…05)** through the `synth` adapter: manifest equals the reviewed fixture; `sources` matches what the generator declares; tables are byte-identical to fixtures. FR-4: for each single-source variant of `synth-01` (built with `sources.drop`), the manifest flags are correct and the run completes.

**Property (hypothesis)**: normalisation idempotent; scrub idempotent; error rule — null/NaN/0 never error, 5xx always error when any code ≥ 100; permuting raw row order leaves outputs byte-identical; outputs do not depend on `alert.shift_s` (Infralume ignores it).

**Real-case smoke** (marked `real_data`, skipped without `${VEYLTRACE_DATA}`): one RE2 case per system (OB, SS, TT), one RE3 case, one RE1 case; checks: schema-valid, `sources` correct (SS has no traces, [rcaeval_facts §Datasets and telemetry][rf-data]), scrub assertions, convert ≤ 10 s, two runs hash-identical. CI's determinism job uses one RE2-SS case (≈ 1.1 MB on HF, [rcaeval_facts §Downloads and licence][rf-downloads]) fetched with `--cases 1`.

## 8. Performance budget

Per RE2 case: materialise ≤ 2 s and ≤ 0.5 GB peak RSS (*estimate*, allocation from the 30 s / 3 GB budget). Convert (excluded from the budget) ≤ 10 s (O-01 criterion). RE2-TT is the stress case: median ≈ 778k spans, max 1.54 M ([rcaeval_facts §Metric step and windows][rf-step]); read traces with column pruning through DuckDB, never pandas `read_csv` of the whole file.

## 9. Evaluation hooks and ablations

| Hook | Bench measures |
|---|---|
| hint (oracle) vs `detect_alert` (detected), set in the alert step | AC@k, Retrieval@K per protocol (M2) |
| `alert.shift_s` ∈ {−120, −60, −30, +30, +60, +120} (applied by core) | accuracy vs shift curve ([04 §5.2](../04-evaluation-protocol.md)) |
| `sources.drop` (each source; metrics only) | accuracy, set size, abstention per pattern (NFR-8) |
| `events.overlay_path` | RCAEval-C decoy robustness (O-13) |
| Infralume itself | convert time, materialise time, peak RSS, `scrub` counts per dataset |

## 10. Tasks and milestones

| ID | When | Scope | Acceptance (summary) |
|---|---|---|---|
| O-00 | by M0, Tue 3 Nov | stub `run(ctx)` (runs the `synth` adapter from `veyltrace_core.synth`); fixtures | e2e on `synth-01` through Observe |
| O-01 | Phase 1, by M1 Sun 8 Nov | fetcher for `rcaeval`; `rcaeval` adapter (RE1 metrics; RE2/RE3 metrics, logs, traces); scrub + test; manifest with alert hint; error rule | all RE2 cases ingest; scrub test passes; ≤ 10 s/case |
| O-07 | Phase 2, by M2 Sun 15 Nov | OTLP converter; `veyllab` adapter ([05 §9](../05-fault-lab-and-dataset.md) layout) | lab captures ingest |
| O-08 | Phase 3, by M3 Sun 22 Nov | `nezha`; `fse26_tt` if R-07 confirms size/format/licence | Nezha cases ingest |
| O-09 | Phase 3 | `sources.drop`; `alert.shift_s` wiring (applied by core); `events.overlay_path` (for O-13) | bench can drive all hooks |
| O-13 | Phase 3 (Observe-owned, in `bench/decoys/`) | RCAEval-C generator writing overlays; see [04-causync §3.6](04-causync.md) | decoys reproducible from seed |
| O-11 | Phase 3 | performance pass with the other Observe engines | ≤ 30 s, ≤ 3 GB on the slowest laptop |
| O-12 | Phase 4 | final docs, fixtures | reviewed by lead |

## 11. Open questions

| # | Question | Default if unresolved |
|---|---|---|
| 1 | ~~CCR: add `metric_type?` and `attrs_json?` to `telemetry.metrics`.~~ **Resolved in 03 §2.2 (2026-10-30)**: both added. Remaining: the 03 key does not include `attrs_json`. | §3.9: converter fills both and keeps label keys in `name` for key uniqueness |
| 2 | ~~Isolation exemption and entry-point group for the fetcher.~~ **Resolved in 02 §6.1, §9 and 08 §3.1 (2026-10-30)**: `veyltrace_infralume.fetch` is the single network exemption; `veyltrace.fetchers` is a listed group. | — |
| 3 | ~~Keep flagd flag-change events?~~ **Resolved in 02 §6.1 (2026-10-30)**: flagd telemetry dropped, flag-change events kept with hashed keys. | bench reports flag-fault cases with and without `events` |
| 4 | Is `frontend-external` (RCAEval OB metrics) its own service or an alias of `frontend`? | own service (faithful to source and to RCAEval's candidate count) |
| 5 | ~~Overlay hook missing from O-09.~~ **Resolved in 07 (2026-10-30)**: O-09 provides `events.overlay_path`. | — |
| 6 | Use Nezha `construct_data` as no-fault cases for `NO_FAULT` calibration? | no: 02 §6.9 and 03 §12.1 fix the normal-window sources (`synth-05`, VeylLab, RCAEval pre-injection); adding Nezha needs a CCR |
| 7 | ~~No `synth` dataset or adapter.~~ **Resolved in 02 §6.1 and 03 §2.1 (2026-10-30)**: `veyltrace_core.synth` registers adapter `synth`, dataset `synth`. | — |
| 8 | A hint outside the data span (broken RE1-OB cases): reject, or run? | core's alert step rejects the case under the oracle protocol; bench reports it as "not run" |
| 9 | ~~Hint visible under the detected protocol.~~ **Resolved in 03 §2.1 (2026-10-30)**: the hint is null under `detected` and only core's alert step reads it (§3.7). | — |

## 12. References

- Master and contracts: [02 §4, §5.1, §6.1, §9](../02-architecture.md); [03 §1–2](../03-contracts.md); [04 §5.2](../04-evaluation-protocol.md) (perturbation hooks); [05 §7, §9](../05-fault-lab-and-dataset.md) (lab changes, capture layout); [07](../07-roadmap.md); [08](../08-collaboration-and-git.md)
- RCAEval layouts, units, sizes, quirks, licence: [rcaeval_facts][rf-all]
- Other datasets, onset sensitivity, flagd leak risk: [benchmarks_and_testbed §Q1–Q3][bt]
- OTLP ingestion, semantic-convention stability: [stack_and_market §A1][sm]; DuckDB/ASOF: [stack_and_market §A2][sm]
- DuckDB determinism and ingest pattern: [rcaeval_facts §Engineering][rf-eng]
- RCAEval paper: arXiv 2412.17015 · HF dataset `phamquiluan/RCAEval` · Zenodo 14590730 · OTLP protocol (opentelemetry-proto)

[rf-all]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md
[rf-data]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#datasets-and-telemetry-per-system
[rf-layout]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#dataset-layout
[rf-scoring]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#ground-truth-and-scoring
[rf-step]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#metric-step-and-windows
[rf-downloads]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#downloads-and-licence
[rf-quirks]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#data-quirks
[rf-eng]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#engineering-duckdb-and-drain3

[bt]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md
[sm]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/stack_and_market.md
