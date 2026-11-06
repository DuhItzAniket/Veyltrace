# Schema conventions (contracts v0.1)

> Owner: lead. Every file in `contracts/schemas/` follows these rules; `scripts/gen_contracts.py --check` enforces the mechanical ones. Field-level truth is [docs/03-contracts.md](../../docs/03-contracts.md).

## 1. Files and identifiers

| Rule | Value |
|---|---|
| File name | `<name>.schema.json`, where `<name>` is the contract name exactly as in 03 (dots kept): `case_manifest`, `alert`, `telemetry.metrics`, `signal_cube.series`, `graph.edges`, `answer_key`, … |
| Shared definitions | `common.schema.json` holds every closed vocabulary from 03 §1 and the identifier/hash formats under `$defs`. Other schemas reference it as `"$ref": "common.schema.json#/$defs/<def>"`. |
| `$schema` | `https://json-schema.org/draft/2020-12/schema` |
| `$id` | `https://veyltrace.dev/schemas/<major>.<minor>/<name>.schema.json` (version folder first, so the relative `common.schema.json` reference resolves to the sibling file). v0.1 → `https://veyltrace.dev/schemas/0.1/…`. Nothing is ever fetched from that URL; it is an identifier. |
| `title` | the generated model name, PascalCase: `CaseManifest`, `Alert`, `TelemetryMetricsRow`, `SignalCubeSeriesRow`, `Verdict`, … Table contracts (Parquet, CSV, JSONL) describe **one row** and end in `Row` (`AgentTraceLine` for JSONL). |
| `description` | one or two sentences: what the artifact is and who produces it. |

## 2. The `x-veyltrace` block (required on every contract schema, not on `common`)

```json
"x-veyltrace": {
  "name": "telemetry.metrics",
  "version": "0.1.0",
  "kind": "parquet",
  "producer": "infralume",
  "path": "telemetry/metrics.parquet",
  "key": ["service", "component", "name", "t_ns"]
}
```

| Field | Meaning |
|---|---|
| `name` | contract name (matches the file name) |
| `version` | full SemVer of the contract; JSON artifacts carry it in `schema_version`, Parquet files in metadata `veyltrace.schema = <name>/<version>` |
| `kind` | `json` (one object per file), `jsonl` (one object per line), `parquet` (one object = one row), `csv` (one object = one row) |
| `producer` | engine or component name in lowercase: `infralume`, `core`, `bench`, … |
| `path` | path relative to the run directory ([02 §4.1](../../docs/02-architecture.md)); for files outside a run dir, the repo-relative pattern (`config/calibration/<family_id>.json`, `bench/results/<experiment_id>/per_case.csv`) |
| `key` | table kinds only: the sort key from 03. Writers sort by the key columns, then by every remaining column in schema order, nulls first, strings by UTF-8 bytes |
| `unique` | table kinds only: `true` if the key is unique (metrics, spans, series, edges, templates, critical_path, anomalies, changes, graph.*, evidence); `false` for logs and events. Writers reject duplicate keys when `true` |
| `self_hash` | optional: `{"field": "verdict_hash", "exclude": ["run_id"]}`. The field holds the SHA-256 of the canonical JSON of the object without `field` and the `exclude` fields (verdict: excludes `run_id`; card: `card_hash` only) |

## 3. Objects and fields

1. Every object (top level and nested) has `"type": "object"`, `"additionalProperties": false` and `"required"` listing **all** its properties, sorted. A field is always present.
2. 03's `?` means **nullable**, not optional: `"type": ["integer", "null"]` for primitives, `"anyOf": [{…}, {"type": "null"}]` for references, objects and arrays.
3. Maps with free keys (`ranker_ranks`, `weights`, `libs`) are `"type": "object"` with `"additionalProperties": {<value schema>}` and no `properties`. Canonical JSON sorts their keys.
4. Arrays: `"type": "array"`, `"items": {…}`. If 03 states an order, add `"x-sort"` on the array: a list of `{"pointer": "<field or '.' for the item itself>", "order": "asc"|"desc"|"enum", "round": <int, optional>, "nulls": "first"|"last" (default "first")}`, applied left to right. Example (03 §8 `all_scores`): `[{"pointer": "fused_score", "order": "desc", "round": 9}, {"pointer": "service", "order": "asc"}]`. `"order": "enum"` sorts by position in the field's enum, for vocabularies whose order is not byte order (trial ids: T1 < T2 < … < T10). A pointer may be a `/`-separated path into nested objects (`hypothesis/service`). Strings compare by UTF-8 bytes; a pointer to an object-valued field (e.g. `proposals` claim `args`) compares the UTF-8 bytes of its `canonical_json` (08 §3.6: claims sorted by predicate, then canonical args). Writers **validate** the order (they never re-sort a producer's domain order); arrays whose order is semantic but not sortable (e.g. `graph.paths.nodes`) get `"x-order": "semantic"` instead.
5. Strings that are closed vocabularies use `enum` (inline if used by one contract, else a `common` `$defs` entry). Adding a value is a contract change.
6. JSON contracts have `"schema_version": {"type": "string", "pattern": "^0\\.1\\.[0-9]+$"}` as their first property.
7. Times are integers in nanoseconds (`_ns`); durations in JSON are numbers in milliseconds (`_ms`). Scores are numbers.
8. Constraints only where 03 states them (`minimum: 0` for counts, patterns for IDs and hashes, `maxLength: 280` for `rationale`). Do not invent ranges.

## 4. Table columns (`parquet`, `csv`)

Every property of a row schema carries `"x-arrow"`, the Arrow type the writer uses: `int64`, `int32`, `float64`, `bool`, `string`, `list<string>`. Nullable columns combine `x-arrow` with a null-permitting `type`. NaN and ±inf are rejected in every float column (nullable columns use null). CSV columns use the same `x-arrow` (booleans are written `0/1`, lists `;`-joined, per 03 §13.2).

Name patterns (`common`): `service_name` = `^[a-z0-9][a-z0-9.-]*$` (no `_`, because RCAEval ranks are `service_indicator`), used for service, component, entity and node columns; `dataset` = `^[a-z0-9]+(-[a-z0-9]+)*$` (a pattern, not an enum).

## 5. Identifier and hash formats (`common.schema.json#/$defs`)

| Def | Pattern |
|---|---|
| `sha256` | `^[0-9a-f]{64}$` |
| `case_id` | `^[0-9a-f]{12}$` |
| `run_id` | `^[0-9a-f]{16}(-x[0-9a-f]{12})?$` (the `-x…` suffix marks a derived `verify_hypothesis` run, 03 §1) |
| `atom_id` | `^E[0-9a-f]{10}$` |
| `change_id` | `^C[0-9a-f]{10}$` |
| `template_id` | `^T[0-9a-f]{8}$` |
| `proposal_id` | `^P[0-9a-f]{8}$` |
| `semver_0_1` | `^0\.1\.[0-9]+$` |

Vocabularies (`family`, `klass`, `mode`, `fault_class`, `source`, `event_kind`, `verdict_status`, `window`, `confidence_level`, `trial_id`, `trial_result`, `ai_mode`, `alert_protocol`, `hint_source`, `predicate`, `atom_kind`, `rejection_reason`, `severity`, `span_kind`, `span_status`, …) are defined once in `common` with exactly the values in 03.

## 6. Examples

Each contract has `contracts/examples/<name>.example.json`: one valid instance (a JSON object for `json`, a JSON array of 2–3 rows for table kinds and `jsonl`). Examples use the synthetic toy system's service names (see `veyltrace_core.synth`; e.g. `frontend`, `checkout`, `cart`, `payment`, `catalog`, `recommend`) and no real case data. `scripts/gen_contracts.py --check` validates every example against its schema.

## 7. Generated code (never edit by hand)

`scripts/gen_contracts.py` reads only these schemas and writes, deterministically (sorted, LF, no timestamps):

- `contracts/generated/python/veyltrace_contracts/`: `models.py` (Pydantic v2, `extra="forbid"`, closed vocabularies as `Literal`), `arrow.py` (pyarrow schemas for table kinds), `registry.py` (name → kind, version, path, key, model, Arrow schema), a copy of the schemas for runtime validation, and the package `pyproject.toml`.
- `contracts/generated/ts/index.ts`: TypeScript types (`export type` unions for vocabularies, `export interface` per object).
