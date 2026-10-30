# AGENTS.md — contracts/

Adds to the root [AGENTS.md](../AGENTS.md); never overrides it.

**Lane:** Reason (the lead owns the files; each producer lane owns its contract's semantics). **Spec:** [docs/03-contracts.md](../docs/03-contracts.md); process in [08 §5](../docs/08-collaboration-and-git.md).

## Purpose
The only shared surface between lanes: JSON Schemas for every artefact that crosses a package boundary, plus generated Pydantic and TypeScript models.

## Layout
- `schemas/<name>.schema.json` — JSON Schema 2020-12, **source of truth**; `$id: https://veyltrace.dev/schemas/<name>/<major>.<minor>`.
- `generated/python/veyltrace_contracts/` and `generated/ts/` — produced by `scripts/gen_contracts.py`. `generated/ts/api/` holds the gateway API types, generated from `packages/gateway/openapi.json` (Explain-owned export) by the same script ([03 §14](../docs/03-contracts.md)).

## Rules
- Schemas and [03](../docs/03-contracts.md) must match field for field; change both in the same PR, with the version bump.
- `generated/` is never edited by hand; CI (`contracts-in-sync`) fails on any diff after regeneration.
- Before M1 (`0.x`): the lead may change fields after posting in the CCR issue and team channel. After M1 (`1.0`): additive optional fields only (minor bump) via a Contract Change Request issue + ADR + lead approval; removing or renaming needs all three lanes and a major bump.
- A field is nullable only if 03 marks it `?`. Closed vocabularies are `enum`s; adding a value is a CCR.
- JSON artefacts carry `schema_version`; Parquet files carry metadata `veyltrace.schema = <name>/<version>`.
- Ground-truth fields (`answer_key`, `bench_result`) exist only in evaluation-only schemas; never add them to an engine contract.
- After a change, the producer refreshes its golden fixtures in a follow-up PR.

## Commands
| Task | Command |
|---|---|
| Regenerate models | `uv run python scripts/gen_contracts.py` |
| Check | `uv run python scripts/check.py --package contracts` |

## Never (this folder)
1. Never hand-edit `generated/` or work around a missing field with an ad-hoc file, column or key.
2. Never add a field, column or enum value that 03 does not list.
3. Never merge a schema change without the matching 03 edit and version bump.
4. Never relax a schema to make a failing producer pass; fix the producer or file a CCR.
