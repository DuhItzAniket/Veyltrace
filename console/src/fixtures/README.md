# Console test fixtures

Gateway responses captured verbatim with `curl` from a local gateway (`uv run python -m veyltrace_gateway`) after AI-off runs of the five `synth` cases (`POST /api/v1/runs`, commit `948fb049`). Served to the views by the fetch stub in `src/test/gateway.tsx`; not formatted by Prettier, so they stay byte-identical to the API output.

`datasets.json`, `cases-synth.json` and `runs-synth.json` are the case-list routes (`/datasets`, `/cases?dataset=synth`, `/runs?dataset=synth`).

| Folder | Run | Verdict status |
|---|---|---|
| `synth-confirmed/` | `72d3d6973cb2c78b` (case `067c1ba0c360`) | `CONFIRMED` |

Each folder holds the run's `GET /runs/{run_id}` as `status.json`. Regenerate by re-running the cases and repeating the `curl` calls; run ids change when config or code change.
