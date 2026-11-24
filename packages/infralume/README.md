# veyltrace-infralume (`veyltrace_infralume`)

Engine 1 of Veyltrace v2 (Observe lane). Infralume ingests one case from a benchmark folder, a lab capture or a live snapshot into the canonical telemetry store, and removes anything that could leak the answer (folder names, chaos and feature-flag attributes, fault-tool telemetry).

- Adapters: `rcaeval` (RE1/RE2/RE3) and `nezha`; entry point group `veyltrace.adapters`.
- `veyltrace data fetch <name>` (`rcaeval`, `nezha`): downloads into `${VEYLTRACE_DATA}`, never into the repo.
- The OTLP → canonical converter (`veyltrace_infralume.otlp`: `spans`, `metrics`, `logs`) is built (O-07). Not here yet: the `otlp_live` adapter, in review (#508). The `veyllab` adapter is not built: moved to v1.1 (lead decision, 23 Nov 2026). `fse26_tt` is cut (07 §1.1 cut item 2): no module, adapter or fetcher.

Spec: [docs/engines/01-infralume.md](../../docs/engines/01-infralume.md). Rules for agents: [AGENTS.md](AGENTS.md).

| | |
|---|---|
| Reads | raw case files under `${VEYLTRACE_DATA}` |
| Writes | `case_manifest.json`, `telemetry/{metrics,logs,spans,events}.parquet` |
| Config | `config/infralume.yaml` |

Built (O-01, O-08, O-09): the `rcaeval` adapter (Hugging Face Parquet and Zenodo CSV layouts) and its fetcher (Hugging Face mirror), the `nezha` adapter and its fetcher (pinned commit), name normalisation, the span error-status rule, scrubbing, the convert cache and the events overlay. Modules: `api.py` (engine entry point, materialise), `adapters/rcaeval.py` (resolve, layouts, allow-list, hint), `adapters/rcaeval_tables.py` (rows, shared by both adapters), `adapters/nezha.py` (resolve, allow-list, slice, hint), `adapters/nezha_layout.py` (days, fault times, keys, index), `adapters/nezha_tables.py` (reshape to the shared row functions), `names.py`, `status.py`, `scrub.py`, `overlay.py`, `cache.py`, `casekey.py`, `index.py`, `fetch/rcaeval.py`, `fetch/nezha.py`.

```bash
uv run veyltrace data fetch rcaeval --suite re2-ss          # into ${VEYLTRACE_DATA}, default ~/veyltrace-data
uv run veyltrace data fetch nezha                          # all 101 Nezha cases (2.8 GB), pinned commit
uv run veyltrace data list re2-ss                           # fetched case ids
uv run veyltrace diagnose --dataset re2-ss --case <case_id> --ai off
uv run python scripts/observe/ingest_check.py re2-ob re2-ss re2-tt --expect-cases 90   # all RE2, <= 10 s each
uv run python scripts/check.py --package infralume
```
