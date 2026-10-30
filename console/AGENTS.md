# AGENTS.md — console/

Adds to the root [AGENTS.md](../AGENTS.md) and never overrides it.

- **Lane:** Explain. Edit only Explain paths (root AGENTS.md §2).
- **Purpose:** the React + TypeScript UI: case list, run view (status, candidate set, ranked table with trial badges, evidence, graph, timeline, card, receipt and replay), live view.
- **Spec:** [docs/06-gateway-and-console.md §5](../docs/06-gateway-and-console.md) · master [02 §8](../docs/02-architecture.md).
- **Inputs:** the gateway API only (`/api/v1`, SSE). **Outputs:** a static build in `console/dist/` (git-ignored), served by the gateway.

## Package rules

1. TypeScript `strict`, plus `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`. No `any`; no `@ts-ignore` or `eslint-disable` without a reason comment.
2. Types come **only** from `contracts/generated/ts` (contracts and the gateway's OpenAPI). Never hand-write a copy of a contract type; if a field is missing, ask for a CCR.
3. API calls through `openapi-fetch`; server state in TanStack Query; UI selection in the URL; no global store.
4. Charts use the ECharts 6 API (agents often produce v5 options: check against the v6 docs). Graphs use Cytoscape.js with a deterministic layout.
5. UX rules (spec §5.3): `INCONCLUSIVE` and `NO_FAULT` as prominent as `CONFIRMED`; an empty candidate set is shown as empty; every number links to its atom or verdict field; confidence as level + set + trials, never a probability; model rationale labelled "not verified"; colour never the only signal.
6. Accessibility target WCAG 2.1 AA: keyboard operable, visible focus, table alternatives for charts and graph, `aria-live` for progress.
7. pnpm only. Dependency changes go in their own `chore(deps)` PR; only the Explain lane touches `pnpm-lock.yaml`.

## Commands

| Task | Command |
|---|---|
| Install | `pnpm -C console install` |
| Check (types, lint, format, tests) | `pnpm -C console check` |
| Dev server | `pnpm -C console dev` (expects the gateway on `127.0.0.1:8000`) |

## Never

- Never compute statistics, scores or verdict logic in the browser; show artifact values only.
- Never display answer keys, injection times or `case_manifest.t_alert_hint_ns`.
- Never call an LLM or any origin other than the gateway; no runtime CDN loads.
- Never edit `contracts/generated/ts` by hand.
