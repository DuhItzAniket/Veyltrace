# AGENTS.md — bench/ (`veyltrace_bench`)

Adds to the root [AGENTS.md](../AGENTS.md); never overrides it.

**Lane:** Reason, except `bench/decoys/` and `bench/stats/`, which are **Observe-owned** (tasks O-13, O-14; see [.github/lanes.yml](../.github/lanes.yml)). **Spec:** [docs/04-evaluation-protocol.md](../docs/04-evaluation-protocol.md). **Contracts:** [03 §13](../docs/03-contracts.md).

## Purpose
Dataset loaders for answer keys, baselines, metrics, calibration fitting, the experiment runner (`veyltrace bench run`) and result tables.

## Inputs / outputs
In: experiment YAMLs, run directories (`verdict`, `slate`, `proposals`, `run_manifest`), answer keys. Out: `bench/results/<id>/{per_case.csv, summary.json, manifest.json}`, `config/calibration/<family>.json`, `bench/results/tables/*.md`.

## Package rules
- bench **may** read `answer_key` and ground truth; it is the only Python package that may. It never passes ground truth to engines, except as the published alert hint the oracle protocol defines ([02 §5.1](../docs/02-architecture.md)).
- bench **may** use `pandas`, `scipy` and plotting libraries (engines may not).
- RCAEval baselines run in an isolated venv (`bench/.venv-rcaeval/`, Python 3.12, pinned commit) as a subprocess; never import RCAEval into the workspace. Clear its `output/` before each run.
- Calibration is fitted only on calibration folds and written to `config/calibration/`; coverage and false-alarm rates are measured only on held-out folds.
- Every number comes from a committed experiment YAML; `prereg: true` YAMLs change only with a row in [04 §12](../docs/04-evaluation-protocol.md) and an ADR.
- Splits are grouped by (system, root service, fault) and seeded; never let repetitions straddle folds.
- `per_case.csv` is committed; answer keys and raw data are not.
- Agents in the Reason lane do not edit `bench/decoys/` or `bench/stats/`; open an issue for Observe instead.

## Commands
| Task | Command |
|---|---|
| Check | `uv run python scripts/check.py --package bench` |
| Run an experiment | `uv run veyltrace bench run bench/experiments/<name>.yaml` |
| Smoke | `uv run veyltrace bench run bench/experiments/synth-smoke.yaml` |

## Never (this package)
1. Never tune or select a parameter on RE2, RE3, Nezha, FSE'26 or VeylLab test folds.
2. Never copy a published number into a results table; re-run in this harness or mark "not run".
3. Never use a run with `code.dirty = true` for a table.
4. Never write calibration from a fold that the same experiment reports as test.
5. Never commit answer keys, telemetry, Parquet files or `runs/`.
