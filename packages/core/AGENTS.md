# AGENTS.md — packages/core (`veyltrace_core`)

Adds to the root [AGENTS.md](../../AGENTS.md); never overrides it.

**Lane:** Reason (lead). **Spec:** [02 §4, §9](../../docs/02-architecture.md), [03 §1, §12](../../docs/03-contracts.md). **Public API:** [README.md](README.md).

## Purpose
Shared kernel: canonical JSON, hashing, IDs, `rng`, config and calibration loading, contract I/O, `RunContext` / `EngineResult`, entry points, the pipeline runner and its alert step, the `veyltrace` CLI, test helpers, the synthetic generator (`synth-01…05`).

## Inputs / outputs
Reads `config/*.yaml`, `config/calibration/*.json`, run-directory contracts, receipts. Writes `alert.json`, `config.lock.json` and `run_manifest.json`; engines write the rest through core's writers.

## Package rules
- The README API is a shared surface. After M1 only additive changes; any signature change needs an issue announced to all lanes first.
- No engine algorithms here. The only engine-specific knowledge is the step order of [02 §4](../../docs/02-architecture.md).
- `canonical_json`, `atom_id`, `case_id`, `run_id` follow [03 §1](../../docs/03-contracts.md) exactly; changing them changes every hash and needs an ADR.
- Every helper is deterministic: no wall clock, no `random`, sorted iteration, `math.fsum` for float sums.
- Allowed deps: stdlib, `pyarrow`, `numpy`, `duckdb`, `pyyaml`, `jsonschema`, `typer`, `veyltrace_contracts`. Banned: `veyltrace_llm`, LLM/HTTP clients, `socket`, `torch`, `transformers`, `pandas`.
- The alert step is the only reader of `case_manifest.t_alert_hint_ns`; it writes `alert.json` ([03 §2.6](../../docs/03-contracts.md)). Calibration is loaded from `config/calibration/` only; core never reads `bench/` or `lab/`.
- End of run ([03 §12](../../docs/03-contracts.md)): Causivra writes `card` (step 10a) → core writes `config.lock.json` and `run_manifest.json` (`outputs` = every artifact except `run_manifest.json` and `receipt.json`) → Causivra writes `receipt` (step 10b). `--ai record` refuses to overwrite an existing `run_id` unless `--force-record` is given.
- `veyltrace_core.synth` registers the adapter `synth` (dataset `synth`). It writes answer keys only to `${VEYLTRACE_DATA}/answer_keys/`; nothing in core reads them. The CLI delegates `bench run` to `bench` and `replay` to Causivra.

## Commands
| Task | Command |
|---|---|
| Check | `uv run python scripts/check.py --package core` |
| Determinism gate | `uv run python scripts/check.py --determinism` |
| Synth cases | `uv run veyltrace data fetch synth` |
| One case | `uv run veyltrace diagnose --dataset synth --case synth-01 --ai off` |

## Never (this package)
1. Never add a registry dict or import list of engines, adapters, rankers, trials or predicates; use entry points.
2. Never write timestamps, hostnames or user names into manifests or artefacts.
3. Never seed `rng` from anything but `(case_id, purpose)`.
4. Never read an `answer_key`, `inject_time.txt` or original case folder name (Infralume adapters own raw datasets; bench owns answer keys).
5. Never let a writer skip schema validation or sorting.
