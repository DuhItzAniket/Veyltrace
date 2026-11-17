# bench (`veyltrace_bench`)

The evaluation harness of Veyltrace v2. It implements the pre-registered protocol in [docs/04-evaluation-protocol.md](../docs/04-evaluation-protocol.md): answer keys, baselines (chance, prior-only, RCAEval's N-Sigma / BARO and others in an isolated venv, SimpleRCA-style alert count, PRISM re-implementation), metrics (AC@k, Avg@5, Retrieval@K, Rerank@1, onset error, coverage, risk–coverage, `NO_FAULT` rates, cost, replay), calibration fitting, the experiment runner and the result tables.

| Path | Owner | Content |
|---|---|---|
| `bench/experiments/*.yaml` | Reason | experiment configs ([04 §9](../docs/04-evaluation-protocol.md)) |
| `bench/results/<id>/` | Reason | `per_case.csv` (committed), `summary.json`, `manifest.json` |
| `bench/results/tables/` | Reason | generated Markdown tables for the paper |
| `bench/decoys/` | **Observe** (O-13) | RCAEval-C decoy-change generator |
| `bench/stats/` | **Observe** (O-14) | cluster bootstrap, sign-flip permutation, McNemar, Holm |
| `config/calibration/<family>.json` | Reason (written by bench) | fitted q̂ and τ_nf, read by Causentra through config |

Rules for agents: [AGENTS.md](AGENTS.md).

## Running an experiment

```bash
export VEYLTRACE_DATA=/tmp/vt-data      # outside the repo
uv run veyltrace data fetch synth       # synth answer keys
uv run veyltrace bench run bench/experiments/synth-smoke.yaml --out /tmp/vt-results --runs-root /tmp/vt-runs
```

- `bench run` runs every case × method through core's pipeline, scores it (`metrics`, aggregated by `summary`) against the answer keys (`answer_keys`) and writes `<out>/<experiment_id>/{per_case.csv, summary.json, manifest.json}` (contracts `bench_result`, `bench_summary`, `bench_manifest`, [03 §13.2–13.4](../docs/03-contracts.md), validated on write); `--out` defaults to `bench/results` (synth requires an `--out` outside the repo). Runs go to `<runs root>/bench/<experiment_id>/` (`--runs-root`, default `core.paths.runs`), which bench empties first, so every run is executed and timed. Each run is a child process (`veyltrace_bench.child`): bench kills it at `resources.timeout_s` (row `timeout`, a miss) and records its peak RSS as `peak_rss_mb` (MiB; null for a killed run).
- `kind: causatrix` methods (`causatrix:<ranker>` with `overrides: {causatrix.rankers.enabled: [<ranker>]}`, and `causatrix:rrf`; [04 §3, §9](../docs/04-evaluation-protocol.md)) report each ranker alone: they are scored on the slate, not the verdict. The id must match what runs (`causatrix:rrf`: no ranker override; `causatrix:<r>`: `[<r>]`, a configured ranker), or the experiment is refused. `causatrix:rrf` shares the `veyltrace:off` run when both are in one experiment.
- **Baselines** (R-05, [04 §4](../docs/04-evaluation-protocol.md)) run the pipeline through the alert step only, in their own runs directory per method, so they read Infralume's normalised tables and `alert.json` (the same `t_alert` as Veyltrace) and are scored on their ranks alone (no slate, pool, set or fault type). Settings and their sources: [`baselines.yaml`](baselines.yaml); a method's manifest config hash covers its section.
  - `{id: simplerca, kind: internal_baseline}`: Fang et al.'s alert count (`veyltrace_bench.simplerca`); ranks are service names, so fine AC@k is 0.
  - `{id: "rcaeval:<m>", kind: rcaeval, rcaeval: {method: <m>, length: 20}}` with `<m>` in `rcaeval.methods` (`baro`, `nsigma`): each case is exported in RCAEval's layout (`simple_metrics.csv` rebuilt from `telemetry.metrics`, `inject_time.txt` = `t_alert`), then RCAEval's own `main.py --report-chance --report-decomposition 5` runs once per dataset in `bench/.venv-rcaeval/` (set up by `uv run python scripts/rcaeval/setup.py`, pinned commit in `baselines.yaml`) with its `output/` deleted first; its time is shared equally among the cases, and its printed report is kept as `<out>/<experiment_id>/rcaeval/<dataset>.<method>.txt`.
  - RCAEval environment: RCAEval tag 1.12.0, commit `90b63a46ac1e969f1fa9015318b51e455c62f8c4` (pinned in `baselines.yaml`), cloned into the git-ignored `bench/.venv-rcaeval/src/RCAEval`; Python 3.12 uv venv in `bench/.venv-rcaeval/`; its `core` extra (no torch) installed from the committed lock `scripts/rcaeval/requirements.lock`, then `-e` RCAEval with `--no-deps`. Command: `uv run python scripts/rcaeval/setup.py` (`--check` verifies, `--lock` recompiles the lock after a commit bump).
  - `chance` is not a method: Chance@k and Lift are the `chance` and `lift` metrics of every group. `prior-only`, `prism-plain` and `naive-change` are not built yet and are refused by name.
- The YAML ([04 §9](../docs/04-evaluation-protocol.md)) is strict: unknown keys are an error, `metrics` is required (summary.json holds just those) and the defaults cite their source (`veyltrace_bench/experiment.py`). Features v0 cannot run yet (the baselines named above, AI arms, AI perturbations, splits, calibration, decoys, normal-window variants, parallel workers, `max_rss_mb` (no outcome is defined for a run over it), coverage/set-size/risk-coverage/selective-accuracy/`NO_FAULT`/decoy/permutation metrics) fail before the first case, naming each one and, where known, the task that adds it or why v0 cannot run it. `statistics` is recorded as not run until `bench/stats` (O-14). The `cost` metric is the nearest-rank p50 and p95 of `wall_ms`, `peak_rss_mb` and the token columns over the rows that have them, plus `n_cost` (03 §13.3, #316).
- `cases` (`all` or a path) and `exclude` (a path) name YAML lists of 12-hex case ids; ids are unique across datasets, so one list (e.g. `bench/dev_cases.yaml`) serves every part.
- An `ok` run with empty `ranks` or a slate with `rankers_active == []` (the R-00 stubs) is unranked ([04 §7](../docs/04-evaluation-protocol.md)): empty `ranks`, every hit a miss, counted (fault cases only) as `n_unranked`. No-fault cases (synth-05) have no truth: null hits, outside every accuracy denominator. Chance@k's n_i is the number of the case's `case_manifest.services` ([04 §7](../docs/04-evaluation-protocol.md)), and Chance@k is null unless every fault case has one.
- `--table` is for results that feed a table: it refuses a dirty work tree (core's `code.dirty` or uncommitted `bench/` files; [AGENTS.md](AGENTS.md) Never 3) and synth (04 §3).
- Exit codes: 0 results written (failed, rejected, `no_alert` and timeout runs are rows); 1 error; 2 usage, `--table` refused, or synth without an `--out` outside the repo; 3 input missing (answer keys: `veyltrace data fetch`); 4 invalid or unsupported experiment.
