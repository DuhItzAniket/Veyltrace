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

**Status (X-00 scaffold).** A page shell only (heading and main landmark) with its toolchain: Vite 8, React 19, TypeScript 5.9 (`strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`), type-checked ESLint (`no-explicit-any` is an error), Prettier (Markdown excluded) and Vitest with Testing Library on jsdom. Runtime libraries of 06 §5.1 (openapi-fetch, TanStack Query, React Router, ECharts 6.1, Cytoscape.js) are pinned exactly but not used yet; views arrive in X-05 and X-10. `packageManager` pins pnpm 12.11.2 for Corepack and CI; CI runs Node 24.
