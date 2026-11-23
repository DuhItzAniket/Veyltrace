# Console test fixtures

Gateway responses captured verbatim with `curl` from a local gateway (`uv run python -m veyltrace_gateway`) after AI-off runs of the five `synth` cases (`POST /api/v1/runs`, commit `948fb049`). Served to the views by the fetch stub in `src/test/gateway.tsx`; not formatted by Prettier, so they stay byte-identical to the API output.

| Folder | Run | Verdict status |
|---|---|---|
| `synth-confirmed/` | `72d3d6973cb2c78b` (case `067c1ba0c360`) | `CONFIRMED` |
| `synth-inconclusive/` | `22f74b437440ffca` (case `0ad66f75c9ac`) | `INCONCLUSIVE` |
| `synth-no-fault/` | `cbc71a0d761a51e3` (case `3263e227fcbe`) | `NO_FAULT` |

Each folder holds `GET /runs/{run_id}`, `/verdict`, `/card` and `/alert`; `synth-confirmed/evidence.json` is `/evidence?limit=1000` (every atom). `datasets.json`, `cases-synth.json` and `runs-synth.json` are the case-list routes. Regenerate by re-running the cases and repeating the `curl` calls; run ids change when config or code change.
