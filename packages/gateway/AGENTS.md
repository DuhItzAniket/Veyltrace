# AGENTS.md — packages/gateway

Adds to the root [AGENTS.md](../../AGENTS.md) and never overrides it.

- **Lane:** Explain. Edit only Explain paths (root AGENTS.md §2).
- **Purpose:** `veyltrace_gateway`: FastAPI HTTP API over run directories, job runner, live OTLP receiver with buffer, snapshot and alert watcher, MCP server.
- **Spec:** [docs/06-gateway-and-console.md](../../docs/06-gateway-and-console.md) · master [02 §5, §8, §9](../../docs/02-architecture.md).
- **Inputs:** run directories (contract artifacts), OTLP/HTTP from the lab Collector, `config/gateway.yaml`.
- **Outputs:** HTTP/SSE responses, MCP tool results, live snapshots (canonical Parquet + `snapshot.json`), queued runs, `openapi.json`.

## Package rules

1. No analysis logic. Every verdict comes from `veyltrace_core.pipeline.run_case` on files on disk.
2. Artifact routes return contract objects unchanged (generated Pydantic models). Gateway-only envelopes live in `api_models.py`.
3. Regenerate and commit `openapi.json` with every API change; the console gets types only through `contracts/generated/ts`.
4. Bind `127.0.0.1` by default; a non-loopback bind needs `--allow-lan`. There is no auth in v1, so keep it local.
5. Validate every path parameter (`case_id` 12 hex, `run_id` 16 hex, known dataset) before touching the filesystem.
6. OTLP decoding goes through Infralume's converter `veyltrace_infralume.otlp`; the snapshot is written and hashed before its run starts.
7. May import `veyltrace_llm`, only for the health probe.
8. MCP inputs are untrusted: validate against enums and FaultLoom `validate()`; never interpolate them into SQL, paths or shell. `verify_hypothesis` hypotheses are written as `proposals.json` with `mode = external` (03 §9.1) and go through the same claim pass and Causentra.

## Commands

| Task | Command |
|---|---|
| Check this package | `uv run python scripts/check.py --package gateway` |
| Run the API | `uv run python -m veyltrace_gateway` |
| Run the MCP server (stdio) | `uv run python -m veyltrace_gateway.mcp` |
| Export OpenAPI | `uv run python -m veyltrace_gateway.export_openapi` |

## Never

- Never write to the cluster: no Kubernetes or Docker client, no remediation endpoints.
- Never serve answer keys, injection times or `case_manifest.t_alert_hint_ns` to the console.
- Never call an LLM from a request handler or return model text that did not pass Causivra's checker.
- Never add or rename fields in a contract response; propose a CCR instead.
- Never start a shell or build file paths from unvalidated input.
