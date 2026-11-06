# AGENTS.md — contracts/

Adds to the root [AGENTS.md](../AGENTS.md); never overrides it.

**Lane:** Reason (the lead owns the files; each producer lane owns its contract's semantics). **Spec:** [docs/03-contracts.md](../docs/03-contracts.md) (field truth) and [schemas/CONVENTIONS.md](schemas/CONVENTIONS.md) (how schemas are written); process in [08 §5](../docs/08-collaboration-and-git.md).

## Purpose
The only shared surface between lanes: JSON Schemas for every artefact that crosses a package boundary, the predicate library, plus generated Pydantic, Arrow and TypeScript code.

## Layout
- `schemas/<name>.schema.json` — JSON Schema 2020-12, **source of truth**; `<name>` is the 03 contract name with dots kept (`telemetry.metrics.schema.json`); `$id: https://veyltrace.dev/schemas/<major>.<minor>/<name>.schema.json` (v0.1: `https://veyltrace.dev/schemas/0.1/…`; an identifier, never fetched).
- `schemas/common.schema.json` — shared vocabularies, identifier and hash formats under `$defs`; other schemas `$ref` it.
- `schemas/CONVENTIONS.md` — the binding rules for writing schemas (`x-veyltrace` block, nullability, Arrow types, sort annotations, examples, generated layout).
- `examples/<name>.example.json` — one valid instance per contract (a JSON object, or a JSON array of 2–3 rows for table kinds and JSONL), using the synth toy system's service names; validated by `--check`.
- `predicates.json` — machine-readable predicate library ([03 §7](../docs/03-contracts.md)): name, parameter names and types, polarity and window only. Ranges stay in `config/faultloom.yaml`, weights in `config/causentra.yaml`.
- `generated/` — produced by `scripts/gen_contracts.py`, deterministically (sorted, LF, no timestamps):
  - `generated/python/veyltrace_contracts/`: `models.py` (Pydantic v2 models, `extra="forbid"`, vocabularies as `Literal`), `arrow.py` (pyarrow schemas for table contracts), `registry.py` (name → kind, version, path, key, model, Arrow schema), `predicates.py` (from `predicates.json`), a copy of the schemas for runtime validation, and the package `pyproject.toml`.
  - `generated/ts/index.ts`: TypeScript types for the console.
  - `generated/ts/api/`: the gateway API types, generated from `packages/gateway/openapi.json` (Explain-owned export) by the same script ([03 §14](../docs/03-contracts.md)).

## Rules
- Schemas and [03](../docs/03-contracts.md) must match field for field; change both in the same PR, with the version bump. Schemas follow [CONVENTIONS.md](schemas/CONVENTIONS.md).
- `generated/` is never edited by hand; CI (`contracts-in-sync`) fails on any diff after regeneration.
- Before M1 (`0.x`): the lead may change fields after posting in the CCR issue and team channel. After M1 (`1.0`): additive optional fields only (minor bump) via a Contract Change Request issue + ADR + lead approval; removing or renaming needs all three lanes and a major bump.
- 03's `?` means **required and nullable**: the field is always present and may be `null`. A field without `?` is never null, and nothing is optional by omission. Closed vocabularies are `enum`s; adding a value is a CCR.
- JSON artefacts carry `schema_version`; Parquet files carry metadata `veyltrace.schema = <name>/<major>.<minor>.<patch>`.
- Every schema change keeps its `examples/` instance valid; a new contract adds one.
- `predicates.json`, the 03 §7 table and FaultLoom's code polarity must agree (a test checks it).
- Ground-truth fields (`answer_key`, `bench_result`) exist only in evaluation-only schemas; never add them to an engine contract.
- After a change, the producer refreshes its golden fixtures in a follow-up PR.

## Commands
| Task | Command |
|---|---|
| Regenerate code | `uv run scripts/gen_contracts.py` |
| Check schemas, examples and generated code (CI) | `uv run scripts/gen_contracts.py --check` |
| Check | `uv run python scripts/check.py --package contracts` |

## Never (this folder)
1. Never hand-edit `generated/` (including `predicates.py`; edit `predicates.json`) or work around a missing field with an ad-hoc file, column or key.
2. Never add a field, column or enum value that 03 does not list.
3. Never merge a schema change without the matching 03 edit and version bump.
4. Never relax a schema to make a failing producer pass; fix the producer or file a CCR.
