# Veyltrace console

React + TypeScript (strict) UI built with Vite 8 and pnpm. It shows Veyltrace runs: case list; run view with status banner, conformal candidate set, ranked candidates with trial badges, evidence atoms, propagation graph (Cytoscape.js), timeline (ECharts 6), incident card, receipt and replay status; and a live view for the lab cluster.

- Spec: [docs/06-gateway-and-console.md §5](../docs/06-gateway-and-console.md)
- Types: generated only, from `contracts/generated/ts`
- Data: the local gateway API (`http://127.0.0.1:8000/api/v1`)

```sh
pnpm -C console install
pnpm -C console dev      # start the gateway first: uv run python -m veyltrace_gateway
pnpm -C console check
```

**Status (X-05 console v0).** Case list (`/`) and run view (`/runs/:runId`): run progress, status banner, conformal candidate set, ranked table with trial badges and trial drawer, evidence table with filters and atom drawer, and the card's propagation path and timeline as plain lists. Toolchain: Vite 8, React 19, TypeScript 5.9 (`strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`), type-checked ESLint (`no-explicit-any` is an error), Prettier (Markdown and `src/fixtures/` excluded) and Vitest with Testing Library on jsdom, over gateway responses captured in `src/fixtures/`. API calls go through a thin typed `fetch` wrapper (`src/api.ts`) because `contracts/generated/ts/api` has no `paths` map for openapi-fetch yet. The live view, propagation graph (Cytoscape.js), timeline chart (ECharts 6.1) and receipt view arrive with X-10. Set `VITE_GATEWAY_ORIGIN` (e.g. in `.env.development.local`) to point the dev server at a gateway other than `http://127.0.0.1:8000`. `packageManager` pins pnpm 12.11.2 for Corepack and CI; CI runs Node 24.
