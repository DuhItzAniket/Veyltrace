# veyltrace-infralume (`veyltrace_infralume`)

Engine 1 of Veyltrace v2 (Observe lane). Infralume ingests one case from a benchmark folder, a lab capture or a live snapshot into the canonical telemetry store, and removes anything that could leak the answer (folder names, chaos and feature-flag attributes, fault-tool telemetry).

- Adapters: `rcaeval` (RE1/RE2/RE3), `nezha`, `fse26_tt` (format unverified), `veyllab`, `otlp_live`; entry point group `veyltrace.adapters`.
- `veyltrace_infralume.otlp`: OTLP → canonical converter used by the gateway and the lab.
- `veyltrace data fetch <dataset>`: downloads into `${VEYLTRACE_DATA}`, never into the repo.

Spec: [docs/engines/01-infralume.md](../../docs/engines/01-infralume.md). Rules for agents: [AGENTS.md](AGENTS.md).

| | |
|---|---|
| Reads | raw case files under `${VEYLTRACE_DATA}` |
| Writes | `case_manifest.json`, `telemetry/{metrics,logs,spans,events}.parquet` |
| Config | `config/infralume.yaml` |

Built so far (O-01): the `rcaeval` adapter (Hugging Face Parquet and Zenodo CSV layouts), the fetcher (Hugging Face mirror), name normalisation, the span error-status rule, scrubbing and the convert cache. Modules: `adapters/rcaeval.py` (resolve, layouts, allow-list, hint), `adapters/rcaeval_tables.py` (rows), `names.py`, `status.py`, `scrub.py`, `cache.py`, `casekey.py`, `index.py`, `fetch/rcaeval.py`.

```bash
uv run veyltrace data fetch rcaeval --suite re2-ss          # into ${VEYLTRACE_DATA}, default ~/veyltrace-data
uv run veyltrace data list re2-ss                           # fetched case ids
uv run veyltrace diagnose --dataset re2-ss --case <case_id> --ai off
uv run python scripts/observe/ingest_check.py re2-ob re2-ss re2-tt --expect-cases 90   # all RE2, <= 10 s each
uv run python scripts/check.py --package infralume
```
