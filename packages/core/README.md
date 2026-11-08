# veyltrace-core (`veyltrace_core`)

The shared kernel of Veyltrace v2. It covers:

- canonical JSON, hashing, IDs and seeded randomness;
- config and calibration loading;
- contract I/O, the run context and dataset adapters;
- plugin discovery, the pipeline runner and its alert step;
- the `veyltrace` CLI, the bootstrap engine stubs and the test helpers.

The Reason lane owns it. Rules: [AGENTS.md](AGENTS.md). Master spec: [docs/02-architecture.md](../../docs/02-architecture.md). Field contracts: [docs/03-contracts.md](../../docs/03-contracts.md).

This README is the shared reference other lanes build against. It documents what is **implemented** on the R-02 branch. Signatures freeze at M1. After that, only additive changes are allowed (AGENTS.md).

> **Not yet available (M0).**
> - Missing pieces: `veyltrace_core.synth` (the `synth` adapter and fetcher, R-03) and all committed golden fixtures (`check.py --update-golden --cascade` generates them from the stubs; they are committed once R-03 lands).
> - Until R-03 lands, `--case synth-01` and `veyltrace data fetch synth` fail with "needs exactly one adapter … matched: none".
> - `veyltrace diagnose --dataset synth --case 59e0d31bcc42` (the 12-hex id of `synth-01`) runs the stub pipeline end to end. The determinism gate SKIPs.
> - While no `synth` adapter is installed, the stub Infralume writes a **placeholder case** for dataset `synth` only; `diagnose` then prints a "placeholder outputs" warning on stderr. Any other dataset without an adapter fails with `ConfigError` (exit 4).

## Conventions that apply to every module

- **Errors carry exit codes.** Every failure is a subclass of `veyltrace_core.errors.VeyltraceError`. `exit_code_for(exc, "diagnose" | "replay")` maps it to a process exit code. Catch the specific subclass, never bare `Exception`.
- **All file I/O is UTF-8 with LF**, through `veyltrace_core.textio` or `veyltrace_core.io`. Writes are atomic: the data goes to `<path>.tmp-<pid>`, then `os.replace` moves it into place. Never call bare `open()`.
- **Determinism.**
  - Analysis code has no wall clock and no unseeded randomness, and it iterates in sorted order.
  - `time.perf_counter` is used only in `pipeline`, for `RunSummary.wall_ms`, and never in artefacts.
- **Engine-facing modules never import `importlib.metadata` at import time.**
  - These are `canonical`, `hashing`, `ids`, `rng`, `errors`, `log`, `textio`, `yaml12`, `config`, `calibration`, `io`, `schemacheck`, `context`, `hint`, `adapters`, `duck`, `steps` and `fetch`.
  - `tests/test_isolation.py` checks each one in a fresh interpreter.
  - `plugins`, `pipeline`, `cli`, `stubs` and `testing` are not imported by engine algorithms.

## Public API

### Canonical JSON and hashing — `canonical`, `hashing` ([03 §1](../../docs/03-contracts.md))

**`canonical_json(obj) -> bytes`** produces `json.dumps(sort_keys, (",", ":"), ensure_ascii=False)` encoded as UTF-8, after these rules:
- floats are rounded to 9 decimals, `-0.0` becomes `0.0`, and NaN/±inf become `null`;
- `int` stays `int` (`4` ≠ `4.0`) and bool stays bool;
- tuples become lists, numpy scalars become Python scalars, and pydantic models are dumped with `mode="json", by_alias=True`;
- non-`str` keys, sets, bytes, dataclasses and datetimes raise `TypeError`.

| Name | Contract |
|---|---|
| `canonical_json_str(obj) -> str`, `normalize(obj)` | Decoded form for the `*_json` str columns; normalised JSON value. |
| `sha256_bytes(b)`, `sha256_json(obj)`, `sha256_file(path)` | Lowercase 64-hex, no prefix. `sha256_file` streams in 1 MiB chunks. |
| `sha256_text_lf(path)` | Hash after CRLF→LF (prompts, briefs, `uv.lock`). |
| `self_hash(contract, obj)`, `verify_self_hash(contract, obj)` | `verdict_hash` and `card_hash`. Excluded fields come from the generated registry; `verdict` also excludes `run_id` (D-4). |
| `manifest_hash(entries: Iterable[(name, sha256)])` | One hash over a set of named files, sorted by name (cassette, prompt and schema hashes). |
| `chain_hash(prev_hash, line)`, `verify_chain(lines, *, start_seq=0, …) -> str \| None` | The agent_trace hash chain. Genesis is `GENESIS_HASH = "0"*64`. Raises `ChainBroken(seq)`. |
| `fraction(*parts: str) -> float` | Stable value in [0, 1) for hash-keyed selection, e.g. Signalyth `fraction(case_id, trace_id)` (D-18). A part that is not UTF-8-encodable raises `ValueError`. |
| `is_sha256(x)` | True for 64 lowercase hex characters. |

### Identifiers — `ids`

| Function | Definition |
|---|---|
| `case_id(canonical_key) -> str` | First 12 hex of `sha256(key.encode("utf-8"))`. `synth-01` → `59e0d31bcc42`. |
| `run_id(case_id, config_sha256, code_commit, ai_mode) -> str` | First 16 hex of `sha256_json([case_id, config_sha256, code_commit, ai_mode])`. |
| `derived_run_id(run_id, external_proposal)` | `<run_id>-x<12 hex>`, for a derived MCP run (02 §4.1). |
| `atom_id(kind, candidate, args)` | `"E"` + 10 hex of `sha256_json([kind, candidate, args])`. Test vectors are in `packages/core/tests/test_ids.py`. |
| `short_id(prefix, n, obj)` | `change_id` (`C`, 10) and `template_id` (`T`, 8). |
| `snapshot_id(file_hashes, t_trigger_ns)` | 32 hex (06 §3.4). |
| `dirty_commit(commit, diff_sha256)` | `<sha>+dirty.<12 hex>` (lead decision §2.9). |
| `is_case_id`, `is_run_id`, `is_atom_id`, `is_code_commit` | Validators. `AI_MODES = ("off", "record", "replay")`. |

### Randomness — `rng`

- `rng(case_id, purpose) -> numpy.random.Generator` is PCG64 seeded with `int(sha256_json([case_id, purpose])[:16], 16)`. It is the only randomness allowed in analysis code.
- `seed_int(case_id, purpose) -> int` returns a seed in `[0, 2**31 - 1)` for external samplers (Relentra, Causivra; D-19).
- Both raise `ValueError` unless `case_id` is 12 hex.

### Errors and exit codes — `errors`

| Exception | `diagnose` exit | `replay` exit | Notes |
|---|---|---|---|
| `UsageError` | 2 | 1 | Bad CLI or `RunPlan` arguments. |
| `ConfigError` | 4 | 4 | Unknown config key, bad value, missing entry point, calibration arm/protocol mismatch. |
| `ArtifactMissing(name, path)` | 3 | 3 | Also a `FileNotFoundError`. |
| `ContractValidationError(name, detail)` | 1 | 1 | Also a `ValueError`. The message names the contract and the JSON pointer or column. |
| `CaseRejected(reason, detail="")` | 3 | 3 | `reason` comes from `CASE_REJECT_REASONS`: `no_hint`, `hint_outside_span`, `empty_window`, `no_telemetry`, `invalid_name`, `invalid_capture`, `unsupported_format`. |
| `NoAlert` | 7 | 3 | Detected protocol, no breach. |
| `CassetteMiss(key)` | 3 | 2 | Also a `KeyError`. `veyltrace_llm.CassetteMiss` subclasses it. Diagnose exit 3 ("inputs missing", lead decision §2.8, which reserves 2 for usage) instead of core_api_spec §4's 2. |
| `HashMismatch`, `InputChanged`, `NarrativeMismatch` | 1 / 3 / 1 | 2 / 3 / 6 | Replay outcomes. |
| `EnvironmentDrift` | 1 | 5 | |
| `ChainBroken(seq)` | 1 | 3 | |
| `RunDirUnavailable` | 1 | 1 | The run dir or its lock could not be created, cleared or locked (an `OSError`, kept as `__cause__`). |
| `StepFailed(step, cause)` | cause's code | cause's code | Raised by the runner; keeps `__cause__`. |

`DiagnoseExit` and `ReplayExit` are the `IntEnum`s behind these codes (02 §6.10; lead decision §2.8).

### Configuration — `config`, `calibration`, `yaml12`

```python
resolve_config(overrides={}, *, config_dir=None, dataset=None, ai_mode) -> ResolvedConfig
load_config(engine, overrides={}, *, config_dir=None, dataset=None, ai_mode="off") -> EngineConfig
config_sha256(resolved) -> str              # sha256 of config.lock.json; enters run_id
section_sha256(resolved, section) -> str    # e.g. Causentra's params_sha256
parse_assignment("k=v") / parse_assignments([...])   # CLI --set, values parsed as YAML 1.2
data_root() -> Path; data_path(relpath) -> Path      # $VEYLTRACE_DATA, else ~/veyltrace-data
load_section_file(name, *, config_dir=None)          # gateway.yaml / fetch subtrees, outside the lock
find_config_dir(start=None) -> Path                  # $VEYLTRACE_CONFIG_DIR, else walk up to config/core.yaml
```

- **Files.** Each section is the file stem, with no wrapper key: `config/core.yaml`, the ten engine files and `llm.yaml`.
  - Files are parsed from bytes using YAML 1.2 core-schema rules: `off` stays a string and `1e-6` is a float.
  - Duplicate keys are an error.
- **Overrides.** Keys are dotted and section-qualified: `core.alert.shift_s=-120`, `causentra.calibration.family=x`.
  - The key must exist in the base YAML. Otherwise you get "unknown key (add it with a default to config/<section>.yaml first)".
  - The value keeps the base type (an int may widen to a float) and replaces the old value whole.
- **`ResolvedConfig`** offers `.sections`, `.calibration`, `.environment`, `.lock_bytes()`, `.engine(name)`, `.with_overrides(...)`, `ResolvedConfig.from_lock(path)` and `.from_lock_bytes(data)`.
  - The lock is lossless: it rejects NaN, ±inf and floats that are not exact at 9 decimals.
  - The lock is machine-independent: it excludes `core.paths` and every `fetch` subtree at any depth. Any lock-bound string that is an absolute path (`/x`, `~/x`, `C:/x`, UNC) or a URL with credentials is a `ConfigError`.
  - Path-valued keys (`*_path`, `*_dir`) must be relative POSIX paths.
  - `ai_mode` is a run parameter, not a config key (D-3).
- **`EngineConfig`** (`ctx.config`) is a read-only `Mapping` over the engine's own section, e.g. `cfg["duckdb"]["threads"]`. It also has:
  - `.engine` and `.core`;
  - `.section(name)` for any other section (D-7);
  - `.get_path("a.b", default)`;
  - `.calibration` (the file content for Causentra, else `None`), `.calibration_family` and `.calibration_sha256`.
- **Calibration** (D-8).
  - `family_id = <family>.<ai_arm>.<alert_protocol>.<fold>`, built from `causentra.calibration.family`, `family_map` and `fold`.
  - The loader reads `config/calibration/<family_id>.json` when it is present. Otherwise the run is uncalibrated.
  - The file's content and SHA-256 go into the lock.
  - Helpers: `load_calibration`, `find_calibration`, `write_calibration` (bench), `make_family_id`, `select_family`, `ai_arm_for`.
- **`config/core.yaml` keys:**
  - `alert.{protocol, shift_s, reject_hint_outside_span}`;
  - `windows.{baseline_s, incident_s}`: `[-1200, -120]` and `[-120, 480]`, half-open ([02 §5.1](../../docs/02-architecture.md));
  - `thresholds.anomaly_z` and `universe.include_external`;
  - `paths.runs`, kept out of the lock. The data root is `$VEYLTRACE_DATA` (default `~/veyltrace-data`) and calibration files are `<config dir>/calibration/<family_id>.json` (exact, case-sensitive name); neither has a key.

### Contract I/O — `io`

```python
path_of(name, run_dir) -> Path;  exists(name, run_dir) -> bool;  is_run_dir_contract(name)
read(name, run_dir, *, columns=None, validate=False) -> BaseModel | pa.Table | list[BaseModel]
read_path(name, path, *, columns=None, validate=False)   # case_manifest comes back hint-redacted (D-15)
read_model(name, run_dir, Model) / read_table(name, run_dir, columns=…) / read_lines(name, run_dir, LineModel)
write(name, data, run_dir) -> sha256;  write_path(name, data, path) -> sha256;  encode(name, data) -> bytes
prepare(name, mapping_or_model) -> BaseModel      # validate + stamp schema_version + check x-sort orders
write_text(relpath, text, run_dir) -> sha256      # card.md: UTF-8, LF; refuses contract paths and ../
arrow_schema(name) / empty_table(name) / conform_table(name, table)
JsonlWriter(name, run_dir)  # .append(line) builds seq/prev_hash/line_hash; .close() -> sha256; context manager
TelemetryTables.from_run_dir(run_dir, *, columns=None) / .from_tables(**tables) / .items()
```

- **Names** are contract names from `veyltrace_contracts.registry.CONTRACTS`: `"evidence"`, `"graph.edges"`, `"telemetry.spans"`, `"config_lock"`, `"agent_trace"`, and so on. Run-dir paths come from the registry.
- **JSON write:**
  - checks the pydantic model and the JSON Schema; an `int` for a float field is rejected, not coerced;
  - stamps `schema_version` (a different value is an error);
  - **validates `x-sort` arrays and never re-sorts them**, so an out-of-order array raises "break the stated order"; semantic arrays such as `ranked` are written as given;
  - verifies `x-self-hash`;
  - rejects NaN and ±inf anywhere, naming the JSON pointer (they are never turned into null; write null yourself where the schema allows it);
  - writes the bytes as `canonical_json + "\n"`.
- **Parquet write:**
  - the Arrow schema must equal `arrow_schema(name)` exactly; `conform_table` casts an inferred table to it;
  - required columns may not be null, NaN/±inf are rejected, and duplicate `x-unique-key` rows are rejected;
  - rows are totally sorted: key columns first, strings by UTF-8 bytes, nulls first;
  - the file is stamped with `veyltrace.schema = <name>/<version>` metadata, and `PARQUET_OPTIONS` (zstd) is fixed;
  - the bytes do not depend on input row order, chunking or the destination path.
- **Read:**
  - checks the schema stamp and version (before M1: exact minor, any patch);
  - `validate=True` also re-checks every row and order;
  - a missing file raises `ArtifactMissing`.
- **`bench_result`** is CSV (`write_path` / `read_path`): booleans are `0`/`1`, lists are `;`-joined, lines end in LF.
- **`TelemetryTables`** is one class: `adapters.TelemetryTables is io.TelemetryTables`. Construction checks every table is a projection of its contract, in contract order, with contract types.

### Run context and results — `context`

```python
@dataclass(frozen=True)
class RunContext:
    case_id: str; run_id: str; dataset: str; run_dir: Path
    ai_mode: Literal["off", "record", "replay"]
    engine: str                    # entry-point name, or "core"
    config: EngineConfig           # own section + .core + .section() + calibration
    phase: Literal["main", "claim_pass", "card", "receipt"] = "main"   # FaultLoom / Causivra branch on it (D-5)
    step: str = ""                 # sub-step name from steps.STEPS
    cassette_dir: Path | None = None
    force_record: bool = False
    resolved: ResolvedConfig | None = None
    unredacted_hint: bool = False  # set by the pipeline for infralume and alert only (D-15)
    def read(name, *, columns=None, validate=False); def write(name, data) -> str
    def read_model(name, Model) -> Model; def read_table(name, *, columns=None) -> pa.Table   # typed, redacted too
    def write_text(relpath, text) -> str; def exists(name) -> bool; def path(name) -> Path
    def with_config(engine) -> RunContext      # e.g. Relentra calling FaultLoom's evidence_cards

@dataclass(frozen=True)
class EngineResult:
    engine: str
    status: Literal["ok", "degraded", "skipped", "failed"]
    outputs: tuple[tuple[str, str], ...] = ()   # (contract or run-dir file name, sha256), sorted on construction
    metrics: Mapping[str, int | float] = {}     # finite counters only; bench reads them, never in artefacts
    notes: tuple[str, ...] = ()
    ai_manifest: AIManifest | None = None       # provider, model, gguf_sha256, prompts, schemas
```

- **Hint redaction (D-15).** Every reader returns `case_manifest` with `t_alert_hint_ns = null` and `hint_source = "none"`: `io.read`, `io.read_path`, `io.read_model` and `ctx.read` alike. Only a context the pipeline built for `infralume` or `alert` (`unredacted_hint=True`) sees the hint through `ctx.read`; renaming the step with `dataclasses.replace` does not grant it. `io.read_unredacted` / `io.read_path_unredacted` exist for core's alert step and core testing; the isolation scan bans the hint field and the word "unredacted" (as a string, attribute, keyword or name) outside its allow-list.
- **Status.** `failed` stops the run and marks later steps `skipped`. `degraded` lets the run continue.
- **Output checks.** The pipeline checks each `outputs` hash against its file. A wrong hash, a missing file, or a file outside the step's outputs fails the step.

### Dataset adapters — `adapters`, `fetch`

- **The `Adapter` Protocol** (registered under `veyltrace.adapters`) requires:
  - attributes `name`, `version` (a per-adapter revision, D-21), `datasets` (fnmatchcase patterns) and `cacheable`;
  - `resolve(dataset, case, data_root) -> CaseRef`;
  - `list_cases(dataset, data_root)`;
  - `convert(ref, cfg) -> CanonicalCase`;
  - `alert_hint(ref)`.
- **`CanonicalCase`** carries:
  - `system` and `tables`;
  - `sources_present`, with keys `metrics/logs/traces/events`;
  - `inputs`, sorted `(name, sha256, bytes)` tuples;
  - `adapter_name`, `adapter_version`, `scrub` and the hint pair.
- **Lookup.** `find_adapter(dataset) -> Adapter | None` and `adapter_for(dataset) -> Adapter` require exactly one match. Several matches always raise `ConfigError`.
- **`AlertDetection(t_alert_ns, entry_services, signal, threshold)`** is the return value of the `veyltrace.alert_detectors:default` callable, `(TelemetryTables, CaseManifest, EngineConfig) -> AlertDetection | None` (D-2).
- **`fetch.FetchRequest(name, data_root, suite=None, source=None|"hf"|"zenodo", cases=None)`** is the argument of a `veyltrace.fetchers` entry point, `fetch(req) -> int`.

### Entry-point groups — `plugins`

- `load(group) -> dict[name, object]` returns the group's entry points, sorted by name.
- `load_one(group, name)` raises `ConfigError` and lists what is registered.
- `natural_key` orders names like T1…T10.
- `preflight(steps, ai_mode=, alert_protocol=)` resolves every engine before step 0, so a missing entry point fails before any directory is created.

| Group | Name → object | Declared by |
|---|---|---|
| `veyltrace.engines` | engine name → `run(ctx) -> EngineResult` | every engine (`api.py`) |
| `veyltrace.adapters` | adapter → `Adapter` (instance or class) | Infralume; core `synth` (R-03) |
| `veyltrace.fetchers` | name → `fetch(FetchRequest) -> int` | Infralume (`veyltrace_infralume.fetch`); core `synth` |
| `veyltrace.alert_detectors` | `default` → `detect_alert` | Anomara |
| `veyltrace.commands` | `replay`, `bench` → `main(argv) -> int` | Causivra, bench |
| `veyltrace.rankers` / `.trials` / `.predicates` | ranker / `T1`…`T10` / predicate | Causatrix / Causentra / FaultLoom |

### Pipeline — `steps`, `pipeline`, `alert`

`steps.STEPS` holds 14 sub-steps. Each `Step` has `index`, `name`, `stage` (the 02 §4 numbering), `engine` (None for core), `phase`, `outputs` (contract names) and `files` (non-contract paths).

| stage | sub-step | writes |
|---|---|---|
| 0 | `infralume` | case_manifest, telemetry.* |
| 1 | `alert` (core) | alert |
| 2 | `signalyth` | signal_cube.* |
| 3 | `anomara` | anomalies, onsets |
| 4 | `causync`, `causalith` (sequential) | alignment, changes; graph.* |
| 5 | `faultloom` | evidence |
| 6 | `causatrix` | slate |
| 7 | `relentra` (`skipped` with AI off) | proposals, agent_trace, cassette/ |
| 8 | `faultloom.claim_pass` | evidence (rewritten) |
| 9 | `causentra` | verdict |
| 10 | `causivra.card` → `manifest` (core) → `causivra.receipt` | card, card.md → config.lock.json, run_manifest.json → receipt |

```python
execute(plan: RunPlan, *, progress=None) -> RunSummary
run_case(dataset, case, ai_mode="off", overrides=None, *, progress=None, **plan_fields) -> RunSummary
RunPlan(dataset, case, ai_mode="off", overrides={}, config=None, run_id=None, out_dir=None,
        from_step="infralume", to_step="causivra.receipt", reuse_dir=None, cassette_dir=None,
        external_proposals=None, write_manifest=True, write_receipt=True, force_record=False,
        runs_root=None, config_dir=None, code_commit=None, env=None)
RunSummary(dataset, case_id, run_id, run_dir, outcome, reason, failed_step, results, outputs,
           wall_ms, steps, cached, exit_code, error)       # outcome: ok | failed | no_alert | rejected
code_commit(repo=None) -> (commit, dirty);  env_info();  uv_lock_sha256()
find_run(run_id, runs_root) -> Path | None;  is_finished(run_dir);  run_dir_for(...);  runs_root(resolved)
summary_dict(summary) / write_summary(summary, path)   # diagnose --summary-json
```

- **Run directory.** A run writes to `<paths.runs>/<dataset>/<case_id>/<run_id>/`. A partial plan (`to_step` before `causivra.receipt`) writes to `<run_id>~<last sub-step>/`.
- **Re-runs:**
  - a finished directory (one with `receipt.json`) is returned unchanged with `cached=True`;
  - except that a dirty tree always re-runs, and `ai_mode="record"` raises `UsageError` unless `force_record` is set;
  - an unfinished directory is cleared, but only if it holds nothing except run files ("refusing to clear" otherwise);
  - an OS lock (`fcntl.flock` / `msvcrt.locking`) on `<run_dir>.lock` guards against concurrent runs, including a second `PathLock` in the same process (`LockHeld`, exit 2); the kernel frees the lock of a killed process;
  - `from_step` with `reuse_dir` (or in place) checks every reused file against the step record of its last earlier writer (`run_manifest.steps`), so restarting between `faultloom` and `faultloom.claim_pass` on a finished run raises `InputChanged` instead of feeding the claim-pass evidence to steps that need the main version.
- **Dirty trees.** `code_commit` returns `<sha>+dirty.<12 hex>` when `packages/`, `contracts/`, `config/` (minus `config/calibration/`) or the root `uv.lock` / `pyproject.toml` differ from HEAD. Untracked files count. Outside git it returns `("unknown", True)`.
- **Manifest step:**
  - writes `config.lock.json`, then `run_manifest.json`;
  - `outputs` lists every run-dir file except `run_manifest.json`, `receipt.json` and `receipt.json.minisig`;
  - `steps[]` records each sub-step's status and files;
  - an unknown file in the run dir fails this step; `.duck-tmp/` and `.tmp/` are ignored.
- **Outcomes:**
  - `CaseRejected` → `rejected` (exit 3);
  - `NoAlert` → `no_alert` (exit 7);
  - an engine exception or `status="failed"` → `failed` (exit 1, or the cause's code);
  - after any of these, later steps are `skipped` and no manifest or receipt is written.
- **Alert step:** `alert.compute_alert(manifest, core_section, *, telemetry=None, detector=None, detector_config=None) -> Alert`, run in the pipeline by `alert.run_alert_step(ctx)`.
  - `oracle` and `live` use the hint. A missing hint gives `no_hint`; a hint outside the data span gives `hint_outside_span`.
  - `detected` calls the `default` alert detector with the run's Anomara config. A `None` result means `NoAlert`.
  - Then `t_alert += shift_s·10⁹`, and each window is clamped to `[data_start, data_end + 1)` (setting the `clamped` flag). An empty window gives `empty_window`.
- **`alert.provisional_manifest(system, tables, adapter="otlp_live", *, dataset="live", adapter_version="0") -> CaseManifest`** (gateway watcher): the data span, services and sources of live tables, a null hint, empty inputs and zero scrub counts; the case id hashes adapter, dataset, system and span.
- **`external_proposals`** must have `mode: "external"` and `model: null` (`UsageError` otherwise).

### CLI — `veyltrace` (`cli.main(argv) -> int`)

| Command | Does |
|---|---|
| `veyltrace diagnose --dataset D --case C [options]` | Runs one case and prints `outcome`, `run_id`, `run_dir`, plus `reason` and `failed_step` when set. Exit codes: `DiagnoseExit` (0, 1, 2, 3, 4, 7). Options are listed below. |
| `veyltrace replay <receipt.json> [--full] […]` | Delegates to `veyltrace.commands:replay` (Causivra); exit codes 0–6. Until Causivra provides it, exits 1 with "not installed yet". |
| `veyltrace bench run <experiment.yaml> […]` | Delegates to `veyltrace.commands:bench`. |
| `veyltrace data fetch <name> [--suite S] [--source hf\|zenodo] [--cases N]` | Calls `veyltrace.fetchers:<name>`. An unknown name exits 2 and lists the installed fetchers. |
| `veyltrace data list <dataset>` | Prints `adapter.list_cases`. |
| Global options | `--log-level debug\|info\|warning\|error`, `--log-format text\|json` (stderr). |

`diagnose` options:
- `--ai off|record|replay`;
- `--alert` or `--protocol` with `oracle|detected|live`;
- `--set k=v`, repeatable;
- `--from-step S` and `--to-step S`;
- `--force-record`;
- `--cassette-from RUN_ID|DIR`;
- `--summary-json PATH`. The file is written even when the run raises (any exception, not only `VeyltraceError`), always with the `schema`, `outcome`, `exit_code` and `reason` keys. PATH must lie outside the run dir.

The CLI sets `OMP/OPENBLAS/MKL_NUM_THREADS=1` with `setdefault` and reconfigures stdout/stderr to UTF-8.

### Support modules

- **`duck.connect(cfg, run_dir)`** is the only allowed `duckdb.connect` in engines (AST-checked).
  - It opens an in-memory database with `threads` and `memory_limit` from `<engine>.duckdb.*` (defaults 1 and `"2GB"`).
  - The temp directory is `<run_dir>/.duck-tmp`, and extension autoload is off.
  - `TimeZone` is `UTC` and `Calendar` is `gregorian` (set after connecting), so TIMESTAMPTZ functions give the same values on every host.
  - Unknown `duckdb.*` keys raise `ConfigError`.
- **`locks.PathLock(target)`** is an exclusive, non-re-entrant OS lock on `lock_path_for(target)` (`<target>.lock`, next to the target, never inside it). Use it as a context manager or call `.acquire()` / `.release()`; `.held` says whether it is taken.
  - A busy lock raises `LockHeld` (a `UsageError`, exit 2) at once instead of waiting, naming the owner pid. A lock left by a killed process is free again.
  - The pipeline uses it for run directories; use it for any other shared target, such as an Infralume cache key.
- **`log.get_logger(__name__)`** returns a `StructLogger` with `.debug/.info/.warning/.error(event, **fields)` and `.bind(**fields)`.
  - Names map into `veyltrace.<pkg>`.
  - Nothing it logs goes into artefacts, so no timestamps leak.
  - Only the CLI calls `log.configure`.
- **`textio`** provides `read_bytes`, `read_text`, `write_bytes`, `write_text`, `open_text`, `atomic_replace` and `AtomicTextWriter`, all UTF-8, LF and atomic.
- **`yaml12.load_yaml_bytes(data, source=)`** and **`schemacheck.validate_json_schema(name, obj)`** are the lower-level helpers behind `config` and `io`.
- **`stubs.run_stub(ctx, engine)`** is the R-02 bootstrap.
  - Every engine's `api.run` calls it until the owning lane replaces it (O-00 / R-00 / X-00).
  - It writes schema-valid placeholder outputs and tags its result with `STUB_NOTE`.
  - The stub Infralume converts through the dataset's adapter when one is registered. Otherwise it writes the placeholder case described at the top (dataset `synth` only).
  - It lives in core, not in `testing.stub` as lead decision §2.13 says, because engines may not import `veyltrace_core.testing` (AST ban); it is on the hint allow-list while it plays Infralume. Both go away when O-00/R-00/X-00 land.

### Testing — `veyltrace_core.testing` (tests and scripts only; engines never import it)

```python
golden(contract, case, *, variant=None, phase=None)        # same types as io.read; case "synth-01" or "synth-01@fake"
golden_path(contract, case, *, variant=None, phase=None) -> Path
golden_file(package, case, relpath, *, variant=None) -> Path   # non-contract fixtures (card.md, records)
assert_golden(actual, contract, case, *, variant=None, phase=None)   # canonical content, never Parquet bytes (D-16)
fixture_run_dir(case, tmp_path, *, through="causivra.card", include=(), variant=None) -> Path
synth_run_dir(case, tmp_path, *, variant=None) -> Path      # case_manifest + telemetry + alert
make_context(engine, run_dir, *, phase="main", ai_mode="off", overrides={}, case_id=None, dataset="synth",
             run_id=None, step=None, cassette_dir=None, force_record=False, config_dir=None) -> RunContext
SYNTH_CASES, VARIANTS, PRODUCER, TWO_PHASE, FIXTURE_CODE_COMMIT ("fixture")
upstream_fixtures / compute_upstream_lock / write_upstream_lock / read_upstream_lock / stale_upstream
```

- **Fixture layout:** `packages/<producer>/fixtures/<case>[@<variant>]/<run-dir path>`.
  - Evidence is phase-qualified: `phase="main"` or `phase="final"` (`evidence.main.parquet`, `evidence.final.parquet`).
  - Any other contract refuses a `phase`.
- **Variants:** `synth-01@{fake,detected,metrics,logs,traces,events,noevents}` and `synth-05@silent`. An unknown case or variant raises `KeyError` that lists the valid names.
- **`assert_golden`:**
  - JSON is compared as canonical model content.
  - Parquet is compared as schema plus rows sorted by key, with floats at 9 decimals.
  - A mismatch raises `AssertionError` with a unified diff of at most 50 changed lines.
- **Missing fixtures.** A missing golden fixture raises `ArtifactMissing`, with a note naming `check.py --package <producer> --update-golden` (and `--cascade`). No fixtures are committed yet in M0.
- **`testing.update_golden`** (`python -m veyltrace_core.testing.update_golden --package P [--step S]… [--case C]…`, normally via `check.py --update-golden [--cascade]`): runs each of P's sub-steps on `fixture_run_dir(through=<previous sub-step>)` with `code_commit="fixture"` and the constant `FIXTURE_ENV`, replaces P's fixtures (evidence phase-qualified) and rewrites `upstream.lock.json`. Cases whose plugins are not installed (e.g. `synth-01@detected` before Anomara's detector) or that need a synth generator variant print `SKIP`, and so do their downstream consumers (the upstream fixture cannot exist yet), so `--cascade` exits 0 before O-04 and R-03.
- **`tests/test_fixture_consistency.py`** asserts `stale_upstream(...) == ()` for every existing fixture dir; it runs only under `check.py --fixtures-stale` (non-required job).

## Develop

```bash
uv sync --all-packages
uv run python scripts/check.py --package core       # lint + types (strict) + tests + isolation
uv run python scripts/check.py --isolation          # import / literal / duckdb bans for every package
uv run python scripts/check.py --determinism        # SKIPs until the synth adapter (R-03) is registered
uv run pytest packages/core -q
VEYLTRACE_DATA=/tmp/vt-data uv run veyltrace diagnose --dataset synth --case 59e0d31bcc42 --ai off
```

`check.py` also accepts these flags:
- `--lint`, `--types`, `--tests`;
- `--contracts-in-sync`, `--changelog [--base REF]`, `--fixtures-stale`;
- with `--determinism`: `--require-synth`, `--require-real-case`, `--ai-fake`;
- `--update-golden [--cascade]`, which never runs in CI.

Exit codes: 0 pass or skip, 1 fail, 2 usage.
