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

**Status (X-00).** An empty app: `GET /api/v1/health` returns the `health` envelope (06 §3.2) built once at start-up from `config/gateway.yaml`, `config/llm.yaml` and the code commit; `ai.reachable` stays `null` until the provider probe lands (X-04), and `live.receiving` is `false` until the OTLP receiver exists (X-10). `python -m veyltrace_gateway` binds `api.host:api.port` (127.0.0.1:8000) and refuses a non-loopback host unless `--allow-lan` is given. `openapi.json` and the generated TypeScript types arrive with the first real routes in X-04.
