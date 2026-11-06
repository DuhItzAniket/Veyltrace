# contracts

Versioned data contracts of Veyltrace v2: one JSON Schema (2020-12) per artefact that crosses a package boundary, the predicate library, and code generated from them. The field-level description is [docs/03-contracts.md](../docs/03-contracts.md); the schemas here are the source of truth and must match it. How schemas are written (identifiers, nullability, Arrow types, sort annotations, examples) is fixed in [schemas/CONVENTIONS.md](schemas/CONVENTIONS.md).

| Path | Content |
|---|---|
| `schemas/` | `<name>.schema.json` for `case_manifest`, `alert`, `telemetry.*`, `signal_cube.*`, `anomalies`, `onsets`, `alignment`, `changes`, `graph.*`, `evidence`, `slate`, `proposals`, `agent_trace`, `verdict`, `card`, `config_lock`, `run_manifest`, `receipt`, `calibration`, `answer_key`, `bench_result`; `$id` is `https://veyltrace.dev/schemas/<major>.<minor>/<name>.schema.json` (an identifier, never fetched) |
| `schemas/common.schema.json` | shared vocabularies and identifier/hash formats (`$defs`) |
| `schemas/CONVENTIONS.md` | binding rules for every schema file |
| `examples/` | `<name>.example.json`: one valid instance per contract, checked by `--check` |
| `predicates.json` | predicate library ([03 §7](../docs/03-contracts.md)): name, parameter names and types, polarity, window |
| `generated/python/veyltrace_contracts/` | workspace package: `models.py` (Pydantic v2), `arrow.py` (pyarrow schemas for table contracts), `registry.py` (name → kind, version, path, key, model, Arrow schema), `predicates.py`, a copy of the schemas, `pyproject.toml` |
| `generated/ts/index.ts` | TypeScript types for the console |
| `generated/ts/api/` | gateway API types, generated from `packages/gateway/openapi.json` ([03 §14](../docs/03-contracts.md)) |

Regenerate with `uv run scripts/gen_contracts.py`; `uv run scripts/gen_contracts.py --check` (CI) validates every schema and example and fails if the generated code would change. Never edit `generated/` by hand. Changes follow the Contract Change Request process in [docs/08-collaboration-and-git.md §5](../docs/08-collaboration-and-git.md). Rules for agents: [AGENTS.md](AGENTS.md).
