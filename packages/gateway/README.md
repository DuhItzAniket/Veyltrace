# veyltrace-gateway

`veyltrace_gateway`: the local HTTP API and MCP server of Veyltrace.

- HTTP API (`/api/v1`): cases, runs (async diagnose + status + SSE), verdict, card, receipt, evidence, graph, series, replay; health.
- Live mode: OTLP/HTTP receiver (`/v1/traces`, `/v1/metrics`, `/v1/logs`), 30-minute buffer, alert watcher on the entry service, "Diagnose now". Each live diagnosis is a snapshot on disk, so it replays like an offline case.
- MCP tools: `diagnose`, `verify_hypothesis`, `get_receipt`, so other agents can check their hypotheses against code-run evidence.
- Binds to `127.0.0.1`; no authentication in v1.
- Spec: [docs/06-gateway-and-console.md](../../docs/06-gateway-and-console.md); settings in `config/gateway.yaml`.

```sh
uv run python -m veyltrace_gateway              # API on http://127.0.0.1:8000
uv run python -m veyltrace_gateway.mcp          # MCP over stdio
uv run python scripts/check.py --package gateway
```
