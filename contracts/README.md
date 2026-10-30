# contracts

Versioned data contracts of Veyltrace v2: one JSON Schema (2020-12) per artefact that crosses a package boundary, and models generated from them. The field-level description is [docs/03-contracts.md](../docs/03-contracts.md); the schemas here are the source of truth and must match it.

| Path | Content |
|---|---|
| `schemas/` | `<name>.schema.json` for `case_manifest`, `alert`, `telemetry.*`, `signal_cube.*`, `anomalies`, `onsets`, `alignment`, `changes`, `graph.*`, `evidence`, `slate`, `proposals`, `agent_trace`, `verdict`, `card`, `run_manifest`, `receipt`, `calibration`, `answer_key`, `bench_result` |
| `generated/python/veyltrace_contracts/` | Pydantic v2 models (workspace package) |
| `generated/ts/` | TypeScript types for the console |
| `generated/ts/api/` | gateway API types, generated from `packages/gateway/openapi.json` ([03 §14](../docs/03-contracts.md)) |

Regenerate with `uv run python scripts/gen_contracts.py`; never edit `generated/` by hand. Changes follow the Contract Change Request process in [docs/08-collaboration-and-git.md §5](../docs/08-collaboration-and-git.md). Rules for agents: [AGENTS.md](AGENTS.md).
