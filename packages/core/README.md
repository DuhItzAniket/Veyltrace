# veyltrace-core (`veyltrace_core`)

The shared kernel of Veyltrace v2: hashing and IDs, deterministic randomness, configuration (including calibration), contract I/O, the run context, plugin discovery, the pipeline runner and its alert step, the `veyltrace` CLI, test helpers and the synthetic case generator. Owned by the Reason lane. Rules: [AGENTS.md](AGENTS.md). Master spec: [docs/02-architecture.md](../../docs/02-architecture.md).

The API below is what other lanes build against. Names are the planned module paths for task R-02; signatures are fixed at M1.

## Public API

### Canonical JSON and hashing — `veyltrace_core.canonical`, `veyltrace_core.hashing`

| Function | Contract |
|---|---|
| `canonical_json(obj) -> bytes` | sorted keys, `(",", ":")` separators, UTF-8, floats rounded to 9 decimals, NaN/±inf → `null` ([03 §1](../../docs/03-contracts.md)) |
| `sha256_bytes(b) -> str` | lowercase 64-hex, no prefix |
| `sha256_json(obj) -> str` | `sha256_bytes(canonical_json(obj))` |
| `sha256_file(path) -> str` | streamed file hash (used for every artefact and input) |

### Identifiers — `veyltrace_core.ids`

| Function | Definition |
|---|---|
| `case_id(original_name: str) -> str` | first 12 hex of `sha256(original_name.encode("utf-8"))` |
| `run_id(case_id, config_sha256, code_commit, ai_mode) -> str` | first 16 hex of `sha256_json([case_id, config_sha256, code_commit, ai_mode])` ([02 §4.1](../../docs/02-architecture.md)) |
| `atom_id(kind, candidate, args) -> str` | `"E"` + first 10 hex of `sha256_json([kind, candidate, args])` ([06 §3.2](../../docs/engines/06-faultloom.md)) |
| `short_id(prefix, n, obj) -> str` | `prefix` + first `n` hex of `sha256_json(obj)`; used for `change_id` (`C`, 10) and `template_id` (`T`, 8) |

### Randomness — `veyltrace_core.rng`

`rng(case_id: str, purpose: str) -> numpy.random.Generator`: PCG64 seeded with `int(sha256_json([case_id, purpose])[:16], 16)`. The only allowed source of randomness in analysis code.

### Configuration — `veyltrace_core.config`

- `load_config(engine: str, overrides: Mapping[str, Any] = {}) -> EngineConfig`: merges `config/core.yaml` (section `core`) with `config/<engine>.yaml`, then dotted-key overrides from the CLI or an experiment YAML; unknown keys are an error.
- `config_sha256(all_engine_configs) -> str`: SHA-256 of `config.lock.json`, the fully resolved config of every engine, which core writes into the run dir (enters `run_id`; replay uses the stored file, not the repo's `config/`).
- `section_sha256(engine) -> str`: hash of one engine's effective section (e.g. Causentra's `params_sha256`).
- Shared keys in `config/core.yaml`: `alert.protocol` and `alert.shift_s`; windows (baseline `[-20 min, -2 min]`, incident `[-2 min, +8 min]` around `t_alert`, [02 §5.1](../../docs/02-architecture.md)); `thresholds.anomaly_z`; `universe.include_external`; `ai.mode`; paths (`runs/`, `${VEYLTRACE_DATA}`, `config/calibration/`).
- **Calibration.** When Causentra's `calibration.family` (or its dataset → family map) names a file `config/calibration/<family>.json`, the loader puts its content in Causentra's `ctx.config.calibration` and records its SHA-256 as `run_manifest.calibration_sha256`. Bench writes these files; engines never open anything under `bench/` or `lab/` ([02 §9](../../docs/02-architecture.md), isolation rule 3).

### Contract I/O — `veyltrace_core.io`

- `read(name: str, run_dir) -> Model | pyarrow.Table` for every contract in [03](../../docs/03-contracts.md) (`"evidence"`, `"slate"`, `"graph.edges"`, …), validated against the generated models in `veyltrace_contracts`.
- `write(name: str, data, run_dir) -> str`: validates, sorts by the contract key (Parquet) or the stated array order (JSON), stamps `schema_version` / Parquet metadata `veyltrace.schema = <name>/<version>`, writes Parquet with zstd, returns the file SHA-256.
- `exists(name, run_dir) -> bool` for optional inputs (`proposals`, `agent_trace`).

### Run context and results — `veyltrace_core.context`

```python
@dataclass(frozen=True)
class RunContext:
    case_id: str
    run_id: str
    dataset: str
    run_dir: Path
    ai_mode: Literal["off", "record", "replay"]
    config: EngineConfig          # this engine's merged section + core section
    def read(self, name: str): ...
    def write(self, name: str, data) -> str: ...

@dataclass(frozen=True)
class EngineResult:
    engine: str
    status: Literal["ok", "degraded", "skipped", "failed"]
    outputs: tuple[tuple[str, str], ...]   # (contract name, sha256), sorted
    metrics: Mapping[str, int | float]     # counters only; no timings in artefacts
    notes: tuple[str, ...]
```

### Entry-point groups — `veyltrace_core.plugins`

`load(group) -> dict[name, object]`, sorted by name. Groups, each declared in the owning package's `pyproject.toml`:

| Group | Name → object | Declared by |
|---|---|---|
| `veyltrace.engines` | engine name → `run(ctx) -> EngineResult` | every engine |
| `veyltrace.adapters` | dataset adapter → ingest function | Infralume; core (`synth`) |
| `veyltrace.fetchers` | dataset → download function (stdlib `urllib` only, never imported by `api.py`) | Infralume (`veyltrace_infralume.fetch`) |
| `veyltrace.rankers` | ranker name → ranker object | Causatrix |
| `veyltrace.trials` | `T1`…`T10` → trial object | Causentra |
| `veyltrace.predicates` | predicate name → predicate object | FaultLoom |

### Pipeline — `veyltrace_core.pipeline`

`run_case(dataset, case, ai_mode, overrides) -> RunSummary` runs the fixed order of [02 §4](../../docs/02-architecture.md): Infralume (step 0) → **alert step** (step 1) → Signalyth → Anomara → Causync, Causalith → FaultLoom → Causatrix → Relentra (skipped when `ai.mode = off`) → FaultLoom claim pass → Causentra → Causivra `card` (10a); then core writes `config.lock.json` and `run_manifest.json` (`outputs` = every artifact except itself and `receipt.json`, [03 §12](../../docs/03-contracts.md)) → Causivra `receipt` (10b).

**Alert step** (`veyltrace_core.alert`, writes `alert.json`, [03 §2.6](../../docs/03-contracts.md)): `oracle` and `live` copy `case_manifest.t_alert_hint_ns`; `detected` calls Anomara's `detect_alert(telemetry)` (`veyltrace_anomara.alert`, resolved at run time so core has no build dependency on Anomara; it reads `telemetry.*` only and `t_alert_hint_ns` is null); then `alert.shift_s` is added (`shift_ns`), the windows are computed from `config/core.yaml` and clamped to `[data_start_ns, data_end_ns]` (`clamped` flag). A missing hint under `oracle`, or no breach under `detected`, stops the run with a clear error that bench records. A failed engine stops the run; later steps are marked `skipped`. Live mode calls the same function on a frozen snapshot.

### CLI — `veyltrace`

| Command | Does |
|---|---|
| `veyltrace diagnose --dataset D --case C --ai off\|record\|replay [--alert oracle\|detected] [--set key=value …] [--force-record]` | one case → `runs/<dataset>/<case_id>/<run_id>/`; `record` refuses to overwrite an existing `run_id` without `--force-record` |
| `veyltrace replay <receipt.json> [--full]` | delegates to Causivra's replay: by default re-hashes the stored outputs of steps 0–4, `config.lock.json`, the calibration file and the cassette, then re-runs steps 5–10; `--full` re-runs 0–10; exit codes per [02 §6.10](../../docs/02-architecture.md) |
| `veyltrace bench run <experiment.yaml>` | delegates to `bench` ([04 §9](../../docs/04-evaluation-protocol.md)) |
| `veyltrace data fetch <dataset>` | delegates to the fetcher registered under `veyltrace.fetchers`; `synth` is generated locally by `veyltrace_core.synth` |

### Testing — `veyltrace_core.testing`

- `golden(contract: str, case: str)`: loads the producer's fixture from `packages/<producer>/fixtures/<case>/`.
- `assert_golden(actual, contract, case)`: byte comparison of canonical forms with a readable diff.
- `synth_run_dir(case, tmp_path)`: a run directory with `case_manifest` and `telemetry.*` for `synth-0N`.
- Fixture refresh: `uv run python scripts/check.py --package <name> --update-golden` (reviewed like code).

### Synthetic generator — `veyltrace_core.synth`

Registers the adapter `synth` (dataset `synth`, [02 §6.1](../../docs/02-architecture.md)), which writes canonical tables and `case_manifest` directly. `generate(case: Literal["synth-01", …, "synth-05"], telemetry_dir, answer_key_dir)`: a seeded 6-service toy system with one entry service and all four sources; faults: CPU hog, network delay, error injection, change-induced regression (with a deploy event), no fault. Two runs give identical hashes (R-03). Answer keys go only to `answer_key_dir` (default `${VEYLTRACE_DATA}/answer_keys/`).

## Develop

```bash
uv sync --all-packages
uv run python scripts/check.py --package core
```
