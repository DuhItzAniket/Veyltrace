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
