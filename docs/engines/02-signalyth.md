# 02 · Signalyth — turn canonical telemetry into typed signals: series, call edges, log templates, critical paths

> Status: v0.1-draft · Lane: Observe · Master: [docs/02-architecture.md §6.2](../02-architecture.md) · Contracts: [docs/03-contracts.md §3](../03-contracts.md) (reads §2, §2.6 `alert`) · Last updated: 2026-10-30

## 1. Purpose and scope

Signalyth converts raw rows into the typed signals every later engine uses. Each output series carries a `family` and a `klass` tag; the internal-versus-external split drives PRISM-style scoring in FaultLoom and Causatrix ([02 §6.2](../02-architecture.md); PRISM split described in [rcaeval_facts §Anomaly scoring methods][rf-methods]).

**In scope**: metric normalisation (units, counter → rate), the `family`/`klass` tagging table, trace series (latency p50/p99, error rate, request rate, self-time), the call-edge table, the critical-path table, Drain3 log templates and log series.

**Out of scope**: anomaly scores and onsets (Anomara); clock alignment (Causync — Signalyth uses source times); the dependency graph and entry detection (Causalith); LLM template refinement (an ablation arm only, [novel_building_blocks §Q2][nbb]; not scheduled in [07](../07-roadmap.md)).

## 2. Inputs and outputs

**Reads**

| Contract | Fields used |
|---|---|
| `case_manifest` | `case_id`, `data_start_ns`, `data_end_ns`, `sources`, `services` |
| `alert` | `windows.baseline`, `windows.incident` (03 §2.6) |
| `telemetry.metrics` | `t_ns, service, component, name, value, unit` |
| `telemetry.spans` | `trace_id, span_id, parent_span_id, service, operation, kind, start_ns, end_ns, status` |
| `telemetry.logs` | `t_ns, service, component, severity, body` |

`telemetry.events` is not read.

**Writes**

| Contract | Fields |
|---|---|
| `signal_cube.series` | `series_id, service, component, signal, family, klass, source, unit, t_ns, value` |
| `signal_cube.edges` | `caller, callee, window, calls, error_rate, p50_caller_ms, p99_caller_ms, p50_callee_ms, p99_callee_ms, p50_gap_ms, p99_gap_ms` |
| `signal_cube.templates` | `service, template_id, template, count_baseline, count_incident, error_level, first_seen_ns` |
| `signal_cube.critical_path` | `window, service, traces, cp_self_ms_p50, cp_self_ms_p99, cp_share_mean, traces_total, traces_slow, cp_share_sum_slow` |

`series_id = "{service}|{component}|{signal}|{source}"`. No field value may contain `|`; Infralume's name rules guarantee this for services and components, and §3.2 sanitises signals.

**Window independence.** `series`, template text and `template_id` cover the whole data range and do not depend on `alert.json`. Only `edges`, the `count_*` columns of `templates` and `critical_path` do. So an onset-shift run (`alert.shift_s`) changes only those tables, and series-level evidence stays comparable across protocols.

## 3. Algorithm

### 3.1 Grids

| Source | Grid | Bucket timestamp | Source |
|---|---|---|---|
| metrics | native observation times (no resampling below native step) | observation time | [02 §6.2](../02-architecture.md) |
| traces | 10 s buckets, epoch-aligned | `floor(t / b) · b` | a priori, same grid as logs |
| logs | 10 s buckets, epoch-aligned | `floor(t / b) · b` | [02 §6.2](../02-architecture.md) |

RCAEval metrics are 1 s rows that Prometheus scraped every 15 s, so values are step-held ([rcaeval_facts §Metric step and windows][rf-step]). Signalyth keeps the 1 s rows. Consumers that need the effective step compute it from runs of equal values (Anomara §3.1, Causync §3.1).

Count-type series (`rps`, `log_rate`, `log_error_rate`, `tmpl:*`) are **zero-filled** on every bucket from `data_start_ns` to `data_end_ns` once the service has any row of that source; otherwise a dead service would look like missing data, not silence. Quantile series (latency, self-time) and ratios (`error_rate`) are left missing in buckets without requests.

### 3.2 Metrics

1. **Map name → signal, family, klass** with the first matching rule (case-insensitive regex on `name`). The table is config (`metrics.family_rules`); defaults:

| # | Pattern on `name` | `signal` | `family` | `klass` |
|---|---|---|---|---|
| 0 | `spec\|quota\|limit\|request_bytes\|requests_bytes` | sanitised name | `other` | `context` |
| 1 | `^cpu$\|cpu_usage\|cpu_seconds\|^container[_.-]cpu\|process[_.]cpu` | `cpu` | `cpu` | `internal` |
| 2 | `^mem$\|memory\|working_set\|rss\|heap` | `mem` | `mem` | `internal` |
| 3 | `^diskio$\|disk\|^container[_.-]fs\|blkio` | `diskio` if name is `diskio`, else `disk` | `disk` | `internal` |
| 4 | `^socket$\|socket\|network\|tcp\|_rx\|_tx\|receive\|transmit` | `socket` if name is `socket`, else `net` | `net` | `internal` |
| 5 | `latency\|duration\|response_time` | `latency_p{q}` when a quantile is in the name (`-50`, `-90`, `p99`, `quantile=0.99`), else `latency` | `latency` | `external` |
| 6 | `^error$\|error\|fail\|5xx` | `error` | `errors` | `external` |
| 7 | `^workload$\|request\|rps\|qps\|throughput` | `workload` if name is `workload`, else `rps` | `traffic` | `context` |
| 8 | anything else | sanitised name | `other` | `context` |

Internal = cpu/mem/disk/socket and external = latency/error follows PRISM's property split ([rcaeval_facts §Anomaly scoring methods][rf-methods]). For RCAEval the signals are exactly `cpu, mem, diskio, socket, workload, error, latency_p50, latency_p90`, which keeps the RCAEval indicator recoverable from `signal`.

If two raw names map to the same `signal` for one (`service`, `component`), all of them use `"{signal}:{sanitised raw name}"` instead. Sanitising replaces `|` and whitespace with `-`.

2. **Units** (to canonical, written in `unit`): latency → `ms` (`s × 1000`, `us ÷ 1000`); memory → `bytes`; everything else unchanged (RCAEval CPU unit is unverified, [rcaeval_facts §Dataset layout][rf-layout]).

3. **Counter → per-second rate.** A metric is a counter if (a) its name matches `metrics.counter_name_patterns` (`_total$`, `_count$`, `_sum$`, `_bucket$`; Prometheus naming, and Infralume's OTLP converter appends `_total` to monotonic sums), or (b) the shape test passes: `metrics.counter_shape_test` is on, family ∉ {`mem`, `latency`, `disk`}, all values ≥ 0, at least `min_increases` (10) increases, and ≥ 99% of value changes are increases, where a drop to < 10% of the previous value counts as a reset, not a decrease. Rate between consecutive observations `(t₁, v₁) → (t₂, v₂)`: `(v₂ − v₁)/(t₂ − t₁)`, or `v₂/(t₂ − t₁)` on a reset (Prometheus reset semantics); written at `t₂`; the first point is dropped; `unit` becomes `<unit>/s` (or `1/s`). Families excluded from the shape test protect memory-leak gauges, which are monotone by nature.

### 3.3 Traces: span tree and services

Per trace, in a single pass over spans sorted by (`trace_id`, `start_ns`, `span_id`):

1. **Parents.** Use `parent_span_id`. If every non-first span of a trace lacks a parent and `traces.reconstruct_parents = if_missing`, rebuild parents by time containment: `parent(b) = argmin_{a: svc(a) ≠ svc(b), start_a ≤ start_b, end_b ≤ end_a} duration(a)` ([rcaeval_facts §Traces][rf-traces]). Spans whose parent is not in the trace are **orphans** and start their own subtree.
2. **Client spans.** A span is client-like if `kind = client`, or (when `kind = unspecified` and `traces.infer_client_spans`) it has exactly one child, that child is in another service, and the child lies inside it within `traces.skew_tolerance_ms`.
3. **Entry span of a service** = a span whose parent is null, an orphan, or in another service, and which is not client-like. Each entry span starts a **visit**: the entry span plus its same-service descendants, stopping at children in other services.
4. **Self-time.** For a non-client span: `self = duration − |∪ children intervals clipped to the span|`. For a client-like span: `self = 0`; its uncovered time is **gap** (network plus client overhead) and is reported on edges, not charged to any service. Visit self-time = Σ self over the visit's spans.
5. **Window of a span or visit** = the window containing its `start_ns`; traces for the critical path are assigned by their root's `start_ns`.
6. **Sampling hook.** `traces.keep_fraction < 1` keeps traces whose `sha256(case_id ‖ trace_id)` falls in the lowest fraction (deterministic; used for the sampling-rate robustness arm, [novel_building_blocks §Q6][nbb]).

**Trace series** per service, 10 s buckets, `source = traces`:

| `signal` | Value | `family` | `klass` | `unit` |
|---|---|---|---|---|
| `latency_p50`, `latency_p99` | quantile of entry-span durations | `latency` | `external` | `ms` |
| `error_rate` | errored entry spans / entry spans | `errors` | `external` | `ratio` |
| `rps` | entry spans / bucket seconds | `traffic` | `context` | `1/s` |
| `self_time_p50`, `self_time_p99` | quantile of visit self-times | `self_time` | `internal` | `ms` |

Quantiles are exact and linear-interpolated (numpy `method="linear"`, same as DuckDB `quantile_cont`); a bucket with fewer than `traces.min_spans_per_quantile` (5) values gets no quantile point. `component` = service for trace series (spans' `component` is optional and often absent).

**Edges** (`signal_cube.edges`), per window: every parent→child pair where the child is an entry span of service B and the parent (or the client-like span wrapping it) is in service A ≠ B. `calls` = number of pairs. `error_rate` = pairs where the child or its client span has `status = error`, divided by `calls`. `p50/p99_callee_ms` from child durations. When a client-like parent exists: `p50/p99_caller_ms` from client durations and `p50/p99_gap_ms` from per-pair `client − child`; otherwise these four are null (03 §3.2). Pairs with fewer than `traces.min_spans_per_quantile` samples give null quantiles.

### 3.4 Critical path (CRISP-style)

CRISP walks back from the end of a span, choosing the child that finished last before the current point ([novel_building_blocks §Q3][nbb]). For synchronous calls this is the longest path through the span tree.

```
walk(s, lo, hi):                      # s is on the critical path during [lo, hi]
    t = hi
    for c in children(s) sorted by (end desc, start desc, span_id asc):
        e = min(c.end, t) if c.end - t <= tol else None   # child ending after t overlaps the path: skip
        if e is None or e <= lo: continue
        b = max(c.start, lo)
        charge(s, e, t)                # time in s not covered by children
        walk(c, b, e)
        t = b
    charge(s, lo, t)
charge(s, x, y): add (y - x) to self(svc(s)) if s is not client-like, else to gap
```

- **Root.** Roots are spans with no parent in the trace. The primary root is the longest (ties: earlier start, then smaller `span_id`). A trace is CP-eligible if the primary root's subtree holds ≥ `cp.min_tree_fraction` (0.8) of its spans; other orphan subtrees are ignored.
- **Clock skew.** Children are clipped to the parent's interval; a child ending more than `tol = traces.skew_tolerance_ms` after the current point is treated as overlapping and skipped. Skew is not corrected here (Causync estimates it later).
- **Invariant.** For each trace, Σ self over services + gap = root duration. Property-tested.
- **Cap.** At most `cp.max_traces_per_window` eligible traces per window, chosen by ascending `sha256(case_id ‖ trace_id)` (deterministic, no RNG).

**Table** per (window, service): `traces` = eligible traces where the service's CP self-time > 0; `cp_self_ms_p50/p99` over those traces; `cp_share_mean` = Σ over all eligible traces in the window of (service CP self / root duration) ÷ number of eligible traces (absent traces count as 0). Hence Σ over services of `cp_share_mean` ≤ 1; the remainder is gap.

**Slow-trace spectrum** (03 §3.4; input to Causatrix's `cp_sbfl`): `traces_total` = number of eligible traces in the window after the cap (the population of `cp_share_mean`; same value on every row of the window). A trace is **slow** if its primary root's duration exceeds the baseline-window p95 (exact, linear) of root durations for the same entry operation (root `service`, `operation`); an operation with fewer than `traces.min_spans_per_quantile` baseline roots has no p95, so its traces are never slow (a priori). `traces_slow` = slow eligible traces on which the service's CP self-time > 0; `cp_share_sum_slow` = Σ over those traces of (service CP self / root duration).

**Micro-example.** Root A `[0,100]`; A has client span b1 `[10,60]` → B server `[12,58]`, and client span c1 `[20,90]` → C server `[22,88]`. Walk A: c1 ends last (90): charge A 90→100 (10); walk c1 over `[20,90]`: gap 88→90 (2), C 22→88 (66), gap 20→22 (2); t = 20. b1 ends at 60 > 20: off path. Charge A 0→20 (20). Result: A 30, C 66, gap 4, total 100; B is not on the path. Shares: A 0.30, C 0.66.

### 3.5 Logs and templates

1. **Line text.** First non-empty line of `body`, truncated to `logs.first_line_max_chars` (512). Multi-line stack traces keep their first line for mining; the error lexicon reads the full body.
2. **Masking** in DuckDB `regexp_replace`, fixed order: UUID → `<UUID>`; IPv4 with optional port → `<IP>`; hex runs of ≥ 8 → `<HEX>`; ISO-8601 timestamps → `<TS>`; numbers with duration units → `<DUR>`; then word-bounded numbers `\b\d+(\.\d+)?\b` → `<NUM>`. Word boundaries keep names such as `svc1` intact; a bare `\d+` mask over-merges ([rcaeval_facts §Engineering][rf-eng]).
3. **Distinct messages.** `GROUP BY service, masked` with total counts over the whole data range.
4. **Drain3**, one fresh in-memory `TemplateMiner` per service, services A→Z; within a service feed distinct masked messages ordered by (count desc, text asc). Config: `sim_th = 0.4`, `depth = 4`, `max_children = 100`, `max_clusters = None`, no Drain3 masking (done in step 2), no persistence. Drain is order-dependent, so the order rule is what makes templates reproducible ([rcaeval_facts §Engineering][rf-eng]; [02 §6.2](../02-architecture.md)). Record the cluster ID returned for each message; after the last message, each cluster's final template text is its `template`.
5. **IDs.** `template_id = "T" + sha256(canonical_json([service, template]))[:8]`. Clusters of one service with identical final text are merged. A collision of the 8-hex prefix within a case raises an error.
6. **Counts.** Join lines back through (service, masked) → template: `count_baseline`, `count_incident` from line timestamps in each `alert.windows` window; `first_seen_ns` = earliest line of the template in the data range.
7. **Error level.** A line is error-level if `severity ∈ {ERROR, FATAL}` or its full body matches the lexicon (`logs.error_lexicon`, case-sensitive unless marked):

| Pattern | Origin |
|---|---|
| `\bERROR\b`, `\bFATAL\b`, `Exception`, `Traceback \(most recent call last\)`, `panic:`, `DEADLINE_EXCEEDED`, `UNAVAILABLE` | [rcaeval_facts §Logs][rf-logs] |
| `(?i)\brefused\b`, `(?i)\btimed? ?out\b` | a priori |
| `(?i)\b(http\|status\|code)[ :=]+5\d\d\b` | a priori; a bare `5\d\d` is narrowed to avoid matching numbers such as "512ms" |
| `(?m)^\s+at [\w.$]+\(`, `goroutine \d+ \[`, `Exception in thread` | stack-trace detectors, a priori |

`templates.error_level` = any line of the template is error-level.

**Log series**, 10 s buckets, `source = logs`, `component` = service:

| `signal` | Value | `family` | `klass` | `unit` |
|---|---|---|---|---|
| `log_rate` | lines / bucket seconds | `logs` | `context` (open question 1) | `1/s` |
| `log_error_rate` | error-level lines / bucket seconds | `logs` | `internal` | `1/s` |
| `tmpl:{template_id}` | lines of the template in the bucket | `logs` | `internal` | `count` |

`tmpl:` series are written only for templates with total count ≥ `logs.min_template_count` (3, a priori), at most `logs.max_template_series_per_service` (200) per service by (total count desc, `template_id` asc). The `templates` table lists every template.

### 3.6 Summary klass table

| `signal` | Source | `family` | `klass` |
|---|---|---|---|
| `cpu` | metrics | cpu | internal |
| `mem` | metrics | mem | internal |
| `diskio`, `disk` | metrics | disk | internal |
| `socket`, `net` | metrics | net | internal |
| `latency*` | metrics, traces | latency | external |
| `error`, `error_rate` | metrics, traces | errors | external |
| `workload`, `rps` | metrics, traces | traffic | context |
| `self_time_p50`, `self_time_p99` | traces | self_time | internal |
| `log_error_rate`, `tmpl:*` | logs | logs | internal |
| `log_rate` | logs | logs | context |
| other metric | metrics | other | context |

## 4. Configuration — `config/signalyth.yaml`

| Key | Default | Unit | Rationale / source |
|---|---|---|---|
| `buckets.logs_s` | `10` | s | [02 §6.2](../02-architecture.md) |
| `buckets.traces_s` | `10` | s | a priori; shares the log grid |
| `metrics.family_rules` | table §3.2 | — | PRISM split ([rcaeval_facts §Anomaly scoring methods][rf-methods]); a priori patterns |
| `metrics.counter_name_patterns` | `["_total$", "_count$", "_sum$", "_bucket$"]` | — | Prometheus naming |
| `metrics.counter_shape_test` | `true` | — | a priori |
| `metrics.counter_shape.min_increases` | `10` | count | a priori |
| `metrics.counter_shape.min_increase_share` | `0.99` | ratio | a priori |
| `metrics.counter_shape.reset_ratio` | `0.1` | ratio | a priori |
| `metrics.counter_shape.exclude_families` | `[mem, latency, disk]` | — | protects leak gauges |
| `traces.reconstruct_parents` | `if_missing` | — | [rcaeval_facts §Traces][rf-traces] |
| `traces.infer_client_spans` | `true` | — | RCAEval spans have no kind |
| `traces.skew_tolerance_ms` | `1.0` | ms | a priori |
| `traces.min_spans_per_quantile` | `5` | count | a priori |
| `traces.keep_fraction` | `1.0` | ratio | sampling arm ([novel_building_blocks §Q6][nbb]) |
| `cp.min_tree_fraction` | `0.8` | ratio | a priori |
| `cp.max_traces_per_window` | `20000` | count | performance cap (*estimate*-based, §8) |
| `logs.first_line_max_chars` | `512` | chars | a priori |
| `logs.mask_patterns` | §3.5 step 2 | — | [rcaeval_facts §Engineering][rf-eng] |
| `logs.drain.sim_th` | `0.4` | — | fixed a priori (Drain3 default) |
| `logs.drain.depth` | `4` | — | fixed a priori (Drain3 default) |
| `logs.drain.max_children` | `100` | — | Drain3 default |
| `logs.min_template_count` | `3` | count | a priori |
| `logs.max_template_series_per_service` | `200` | count | a priori cost cap |
| `logs.error_lexicon` | §3.5 step 7 | — | a priori ([rcaeval_facts §Logs][rf-logs]) |
| `duckdb.threads` | `1` | — | determinism ([rcaeval_facts §Engineering][rf-eng]) |
| `duckdb.memory_limit` | `1.5GB` | bytes | §8 |

## 5. Determinism and isolation

- Services processed A→Z; traces by `trace_id`; children by the sort in §3.4; Drain3 input by (count desc, text asc). No set or dict iteration without sorting.
- Exact quantiles only; DuckDB single-threaded for aggregates; final arithmetic in float64 numpy.
- Trace caps and sampling use SHA-256 of IDs, never RNG.
- Drain3 runs in memory with no persistence handler; never import `drain3` Redis or Kafka persistence modules.
- Allowed imports: `duckdb`, `pyarrow`, `numpy`, `drain3`, stdlib. Banned per AGENTS §4.3.

## 6. Missing data and failure behaviour

| Situation | Behaviour |
|---|---|
| `sources.traces = false` | no trace series; `edges` and `critical_path` have zero rows |
| `sources.logs = false` | no log series; `templates` has zero rows |
| `sources.metrics = false` | no metric series |
| Spans without any parent IDs | containment reconstruction (§3.3) |
| Only orphan-heavy traces | excluded from the critical path; series and edges still computed |
| Child outside parent (skew) | clipped (§3.4) |
| Span `kind` missing | treated as `unspecified`; client inference applies |
| Log body empty | dropped from mining; still counts in `log_rate` |
| Drain3 raises | fall back to the masked string as the template for that service, logged as a warning; reported by bench |
| A window empty | that window's `edges`/`critical_path` rows absent; `count_*` = 0 |

## 7. Tests

**Unit**: every family rule (including RCAEval names and rule 0 exclusions); collision renaming; unit conversion; counter detection (named, shape, excluded families, resets); rate with reset; client-span inference; self-time with overlapping children; visit construction; edge gap only with client spans; the §3.4 micro-example exactly; masking order (`svc1` survives, UUIDs masked); lexicon true and false positives (`took 512ms` is not an error); template ID formula.

**Golden (synth-01…05)** against reviewed fixtures in `packages/signalyth/fixtures/<case>/`, and behaviour checks that need no answer key:
- synth-01 (CPU hog): one service's `cpu` series rises after `t_alert`; its `self_time_p99` rises if the toy system emits traces.
- synth-02 (network delay): one edge's incident `p99_gap_ms` or `p99_callee_ms` exceeds its baseline value; no service's CPU changes.
- synth-03 (error injection): an `error_rate` series rises; at least one template with `error_level = true` has `count_incident > count_baseline`.
- synth-04 (change-induced regression): latency or self-time of one service rises after the change time recorded in events.
- synth-05 (no fault): baseline and incident distributions of every series are similar (fixture comparison only).

**Property (hypothesis)**: random span trees → Σ self + gap = root duration, every self ≥ 0, every share in [0, 1], Σ `cp_share_mean` ≤ 1, `traces_slow` ≤ `traces` ≤ `traces_total`, `cp_share_sum_slow` ≤ `traces_slow`; shuffled input rows → byte-identical outputs; Drain3 templates invariant to input row order; counter rate ≥ 0 for any monotone-with-resets sequence; series values independent of windows (move windows, compare `series`).

**Two-laptop check** (O-03): template tables from two machines are byte-identical on 3 real cases.

**Real-case smoke**: RE2-OB, RE2-SS (no traces), RE2-TT, RE3-OB (stack traces): schema-valid, sorted, two runs identical, time within §8.

## 8. Performance budget

Per RE2 case: ≤ 10 s and ≤ 1.5 GB peak RSS (*estimate*, allocation of the 30 s / 3 GB budget). Drivers: RE2-TT spans (median ≈ 778k, max 1.54 M per case) and logs (median ≈ 268k lines) ([rcaeval_facts §Metric step and windows][rf-step]). Mining runs on distinct masked messages only, expected to be hundreds to low thousands per case (*estimate*, [rcaeval_facts §Engineering][rf-eng]). Critical path is the hot loop; if O-11 measures it above 4 s on RE2-TT, lower `cp.max_traces_per_window` and record the change in an ADR.

## 9. Evaluation hooks and ablations

| Arm | Bench measures |
|---|---|
| `traces.keep_fraction` ∈ {1.0, 0.1, 0.01} | accuracy vs trace sampling ([novel_building_blocks §Q6][nbb]) |
| Drain3 vs masked-string templates | effect of templates on accuracy (log-parsing quality vs RCA, [novel_building_blocks §Q2][nbb]) |
| critical-path weighting on/off in `cp_sbfl` | Causatrix ablation; Signalyth provides `critical_path` |
| `traces.infer_client_spans` on/off | edge-gap availability on RCAEval |
| Signalyth itself | wall time, peak RSS, number of series, templates per case |

## 10. Tasks and milestones

| ID | When | Scope | Acceptance (summary) |
|---|---|---|---|
| O-00 | by M0, Tue 3 Nov | stub writing schema-valid outputs; synth fixtures | e2e on `synth-01` |
| O-02 | Phase 1, by M1 Sun 8 Nov | metrics + traces: series, klass tags, edges, self-time, critical path | golden + 3 real cases; sorted; deterministic |
| O-03 | Phase 1, by M1 | logs: Drain3 templates with order rules; counts; error rates | same templates across two runs and two laptops |
| O-11 | Phase 3, by M3 | performance pass | ≤ 30 s and ≤ 3 GB per RE2 case (deterministic path), measured on the slowest laptop |
| O-12 | Phase 4 | docs, fixtures, paper section on signals | reviewed by lead |

## 11. Open questions

| # | Question | Default if unresolved |
|---|---|---|
| 1 | 02 §6.2 lists "own logs" as internal. Total log volume tracks traffic, so `log_rate` is tagged `context`; error lines and templates stay `internal`. | as tabled in §3.6 |
| 2 | Gap time on the critical path is charged to no service (Σ shares ≤ 1). Network faults then show up on edges, not in `critical_path`. Should FaultLoom's `critical_path_share` atom also see gap? | gap stays unattributed; FaultLoom uses `edges` gap for network evidence |
| 3 | Error lines are often written by the caller, not the faulty callee ([rcaeval_facts §Logs][rf-logs]); `log_error_rate` is still tagged internal to the logging service. Caller-blame is handled by Causalith's log-mention edges, not here. | unchanged |
| 4 | `other`-family metrics are tagged `context` so they never count as internal evidence. | as tabled |
| 5 | LLM template refinement arm is in 02 §6.2 but in no roadmap task. | not built for v1.0 |
| 6 | *Resolved in 03 §3.4 (2026-10-30):* the FaultLoom CCR adding `traces_total`, `traces_slow` and `cp_share_sum_slow` to `critical_path` was accepted; computed in §3.4 (slow-trace spectrum). | — |

## 12. References

- Master and contracts: [02 §6.2, §9](../02-architecture.md); [03 §2–3](../03-contracts.md); [07](../07-roadmap.md)
- Critical path (CRISP), trace statistics vs GNNs: [novel_building_blocks §Q3][nbb]
- Drain3 vs LLM parsers: [novel_building_blocks §Q2][nbb]; Drain3 config, distinct-message trick, order dependence: [rcaeval_facts §Engineering][rf-eng]
- Containment parents, self-time, lexicon, caller blame: [rcaeval_facts §Traces][rf-traces], [§Logs][rf-logs]
- RCAEval metric names, units, sampling, volumes: [rcaeval_facts §Dataset layout][rf-layout], [§Anomaly scoring methods][rf-methods], [§Metric step and windows][rf-step]
- CRISP: Zhang et al., USENIX ATC 2022 · Drain3: github.com/logpai/Drain3

[nbb]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/novel_building_blocks.md
[rf-layout]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#dataset-layout
[rf-step]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#metric-step-and-windows
[rf-methods]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#anomaly-scoring-methods
[rf-traces]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#traces-spectrum-and-timing
[rf-logs]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#logs
[rf-eng]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#engineering-duckdb-and-drain3


