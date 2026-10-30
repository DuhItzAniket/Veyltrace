# AGENTS.md — packages/infralume (`veyltrace_infralume`)

Adds to the root [AGENTS.md](../../AGENTS.md); never overrides it.

**Lane:** Observe. **Spec:** [docs/engines/01-infralume.md](../../docs/engines/01-infralume.md). **Master:** [02 §5.1, §6.1](../../docs/02-architecture.md). **Contract:** [03 §2.1–2.5](../../docs/03-contracts.md).

## Purpose
Engine 1, pipeline step 0. The only code that touches raw data: adapters (`rcaeval`, `nezha`, `fse26_tt`, `veyllab`, `otlp_live`) turn one case into canonical `telemetry.*` over the full available span, normalise service names, apply the span error-status rule and scrub leakage. Also ships the OTLP → canonical converter (used by the gateway and the lab) and the dataset fetcher behind `veyltrace data fetch`. The `synth` adapter is not here: it lives in `veyltrace_core.synth`.

## Inputs / outputs
In: raw case under `${VEYLTRACE_DATA}`, `config/infralume.yaml`, optional events overlay. Out: `case_manifest.json` (with `t_alert_hint_ns`, null under the detected protocol, and `hint_source`), `telemetry/{metrics,logs,spans,events}.parquet`.

## Package rules
- Core's alert step, not Infralume, sets `t_alert` and windows. Infralume only writes the hint (reading `alert.protocol` solely to blank it under `detected`) and never reads `alert.shift_s`.
- Each adapter has an allow-list of readable file names; `cases.parquet`, `root_cause*`, answer keys and fault-list root-cause fields are never opened. Canonical case key → `case_id` only inside the adapter.
- No path under `bench/` or `lab/` (02 §9 rule 3). Data roots come only from `${VEYLTRACE_DATA}`.
- Scrubbing and normalisation must stay idempotent (property tests).
- Absent and dropped sources look identical: zero-row table, `sources.<s> = false`.
- Determinism: sorted file discovery, DuckDB `threads = 1`, exact functions, `canonical_json`.
- Allowed imports: `veyltrace_core`, `veyltrace_contracts`, `duckdb`, `pyarrow`, `numpy`, `opentelemetry-proto`/`protobuf`, stdlib. Banned: `veyltrace_llm`, LLM/HTTP clients, `socket`, `torch`, `transformers`.
- Exception: `veyltrace_infralume/fetch/` (entry-point group `veyltrace.fetchers`) may use stdlib `urllib.request` and is never imported by `api.py` or adapters. It is the single network exemption ([02 §6.1, §9](../../docs/02-architecture.md)); the isolation test enforces it.

## Commands
| Task | Command |
|---|---|
| Check | `uv run python scripts/check.py --package infralume` |
| Determinism | `uv run python scripts/check.py --determinism` |
| Lanes | `uv run scripts/check_lanes.py --lane observe` |
| Refresh fixtures | `uv run python scripts/check.py --package infralume --update-golden` |
| Fetch data | `uv run veyltrace data fetch rcaeval --suite re2-ss` |

## Never (this package)
1. Never write a folder name, path component, injection label or deny-listed attribute key into any output.
2. Never copy the injection time anywhere except `t_alert_hint_ns`, and write that only when `alert.protocol` is `oracle` or `live`.
3. Never forward-fill or resample: unobserved metric points are dropped.
4. Never download into the git work tree, and never commit data or cache files.
5. Never rewrite log bodies except to replace folder tokens.
