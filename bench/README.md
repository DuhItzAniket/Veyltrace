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
  - **Upstream reuse** (R-16 B5, #413; [04 §12](../docs/04-evaluation-protocol.md) deviation of 2026-11-21, [ADR](../docs/adr/20261121-ak-slate-method-upstream-reuse.md)): a `causatrix:<ranker>` method (only `causatrix.*` overrides, AI off) restarts at FaultLoom on the `veyltrace:off` run of the same case and stops after Causatrix (`veyltrace_bench.upstream`; FaultLoom re-runs because the claim pass rewrites a finished run's evidence), when the upstream `config.lock.json` sections, the code commit and every reused output hash match; otherwise it runs in full. Its slate is byte-identical to a full run's. **Its `wall_ms` and `peak_rss_mb` then cover the FaultLoom and Causatrix steps only**, its timeout is what is left of `timeout_s` after the source's run, and the summary `cost` entry of every `kind: causatrix` group is null: RQ5 cost numbers come only from `veyltrace:off` rows. Each decision is logged as `bench.upstream_reuse`.
- **Baselines** (R-05, [04 §4](../docs/04-evaluation-protocol.md)) run the pipeline through the alert step only, in their own runs directory per method, so they read Infralume's normalised tables and `alert.json` (the same `t_alert` as Veyltrace) and are scored on their ranks alone (no slate, pool, set or fault type). Settings and their sources: [`baselines.yaml`](baselines.yaml); a method's manifest config hash covers its section.
  - `{id: simplerca, kind: internal_baseline}`: Fang et al.'s alert count (`veyltrace_bench.simplerca`); ranks are service names, so fine AC@k is 0.
  - `{id: naive-change, kind: internal_baseline}`: RCAEval-C's change baseline (`veyltrace_bench.naive_change`): the services with a change in `telemetry.events` before `t_alert`, latest first; it has no `baselines.yaml` section.
  - `{id: "rcaeval:<m>", kind: rcaeval, rcaeval: {method: <m>, length: 20}}` with `<m>` in `rcaeval.methods` (`baro`, `nsigma`): each case is exported in RCAEval's layout (`simple_metrics.csv` rebuilt from `telemetry.metrics`, `inject_time.txt` = `t_alert`), then RCAEval's own `main.py --report-chance --report-decomposition 5` runs once per dataset in `bench/.venv-rcaeval/` (set up by `uv run python scripts/rcaeval/setup.py`, pinned commit in `baselines.yaml`) with its `output/` deleted first; its time is shared equally among the cases, and its printed report is kept as `<out>/<experiment_id>/rcaeval/<dataset>.<method>.txt`.
  - RCAEval environment: RCAEval tag 1.12.0, commit `90b63a46ac1e969f1fa9015318b51e455c62f8c4` (pinned in `baselines.yaml`), cloned into the git-ignored `bench/.venv-rcaeval/src/RCAEval`; Python 3.12 uv venv in `bench/.venv-rcaeval/`; its `core` extra (no torch) installed from the committed lock `scripts/rcaeval/requirements.lock`, then `-e` RCAEval with `--no-deps`. Command: `uv run python scripts/rcaeval/setup.py` (`--check` verifies, `--lock` recompiles the lock after a commit bump).
  - `{id: prior-only, kind: internal_baseline}`: the 04 §4 floor (`veyltrace_bench.prior_only`, #561). It ranks every service of the case's `case_manifest.services` by how often it is the root among the fault cases of the same dataset part in the calibration fold that fits the case, ties A→Z. It needs `split.scheme: crossfit2`, so the case's own cluster never counts. Its run stops after Infralume, so it reads no alert and no telemetry signal, and it has no `baselines.yaml` section.
  - `chance` is not a method: Chance@k and Lift are the `chance` and `lift` metrics of every group. `prism-plain` is not built yet and is refused by name.
- **RCAEval-C** (`protocol.decoys`, #326, [04 §5.2](../docs/04-evaluation-protocol.md)): before the methods run, each case gets one Infralume-only run for its `case_manifest.services`, then `veyltrace_decoys` (Observe, O-13) writes its overlay to `${VEYLTRACE_DATA}/overlays/<experiment_id>/<case_id>/events.parquet`; every method's run of the case sets `infralume.events.overlay_path` to it, and its answer-key row gets `decoy_changes_json`, which fills `decoy_present` and `decoy_ranked_first` in `per_case.csv`. The `decoy_ranked_first` summary metric needs a `bench_summary` entry first.
- The YAML ([04 §9](../docs/04-evaluation-protocol.md)) is strict: unknown keys are an error, `metrics` is required (summary.json holds just those) and the defaults cite their source (`veyltrace_bench/experiment.py`). Features v0 cannot run yet (the baselines named above, AI arms, AI perturbations, splits, calibration, normal-window variants, parallel workers, `max_rss_mb` (no outcome is defined for a run over it), coverage/set-size/risk-coverage/selective-accuracy/`NO_FAULT`/decoy/permutation metrics) fail before the first case, naming each one and, where known, the task that adds it or why v0 cannot run it. `statistics` is recorded as not run until `bench/stats` (O-14). The `cost` metric is the nearest-rank p50 and p95 of `wall_ms`, `peak_rss_mb` and the token columns over the rows that have them, plus `n_cost` (03 §13.3, #316).
- **Statistics** (`summary.json` `statistics`, bench_summary 1.1, #357; `veyltrace_bench.stats_summary` over Observe's `veyltrace_stats`, O-14): a 95% cluster-bootstrap interval per group for every listed case-mean metric, with clusters (system, root service, fault) and the experiment's seeds. An experiment with `statistics.noninferiority` also gets its paired comparisons on `primary_metric`:
  - **Per system:** non-inferiority with margin 0 against the best baseline of that system (ties go to the earlier listed), and superiority in `holm_family`.
  - **Pooled:** superiority over all clusters of the benchmark (`dataset` `re2`, `system` null), with the sign-flip test, McNemar, and `low`/`high` from the system-stratified cluster bootstrap (`veyltrace_stats.cluster.stratified_cluster_bootstrap`, #427); H1b needs that interval to exclude 0 and Holm significance (04 §2). Holm runs over the family. Every method also gets pooled `intervals[]` rows (system null), stratified the same way, on per-case seed means.
  - **Method A** is the first listed method that is not compared against.
- `cases` (`all` or a path) and `exclude` (a path) name YAML lists of 12-hex case ids; ids are unique across datasets, so one list (e.g. `bench/dev_cases.yaml`) serves every part.
- An `ok` run with empty `ranks` or a slate with `rankers_active == []` (the R-00 stubs) is unranked ([04 §7](../docs/04-evaluation-protocol.md)): empty `ranks`, every hit a miss, counted (fault cases only) as `n_unranked`. No-fault cases (synth-05) have no truth: null hits, outside every accuracy denominator. Chance@k's n_i is the number of the case's `case_manifest.services` ([04 §7](../docs/04-evaluation-protocol.md)), and Chance@k is null unless every fault case has one.
- `--table` is for results that feed a table: it refuses a dirty work tree (core's `code.dirty` or uncommitted `bench/` files; [AGENTS.md](AGENTS.md) Never 3) and synth (04 §3).
- Exit codes: 0 results written (failed, rejected, `no_alert` and timeout runs are rows); 1 error; 2 usage, `--table` refused, or synth without an `--out` outside the repo; 3 input missing (answer keys: `veyltrace data fetch`); 4 invalid or unsupported experiment.

## RQ6 replay results (#440)

```bash
uv run veyltrace bench replay --role recording --dry-run   # run count and total bytes (the CI archive); writes nothing
uv run veyltrace bench replay --role recording --table     # Tier 1 on the recording laptop
uv run veyltrace bench replay --role recording --tier 2    # Tier 2: regenerate the fixed sample (needs the model)
uv run veyltrace bench replay --role second-laptop         # the same runs on another host (copy of <runs root>/bench-ai)
```

- The sources are the committed results under `--results` (default `bench/results`) with an AI arm, or the `--experiment` ids given. `recording` enumerates the kept record runs their `ok` AI-arm rows scored. `second-laptop` and `ci` replay exactly the runs of the committed `replay/recording/` result, whose sources must be the same.
- Tier 1 runs `veyltrace replay <receipt> --report` in a child per run (strict: no `--allow-env-drift`). Tier 2 records the run again from its `config.lock.json` into a scratch root and compares `proposals.json` bytes.
- Output: `bench/results/replay/<role>/replay.csv` and `replay_summary.json` ([03 §13.5–13.6](../docs/03-contracts.md)), the rates with Clopper–Pearson intervals; Table 9 reads them. Decisions: [ADR](../docs/adr/20261122-ak-rq6-replay-results.md). The run archive is private only (it holds telemetry).

## Tables and figures (R-17)

```bash
uv run veyltrace bench tables           # regenerate bench/results/tables/*.md and *.tex
uv run veyltrace bench tables --check   # write nothing; exit 2 and list the paths that differ (1 = error)
```

- Inputs: the experiment YAMLs (which experiments exist; grid coordinates such as `shift_s`) and each `bench/results/<experiment_id>/`. Numbers come from `summary.json` only ([04 §9](../docs/04-evaluation-protocol.md)). `manifest.json` gives the commit. The SHA-256 of all three result files is printed under each table ([04 §10.2](../docs/04-evaluation-protocol.md)). Synth experiments are never reported.
- Every row comes from one experiment and ends with `<experiment_id> @ <commit>`. A value with a 95% cluster-bootstrap interval prints as `0.500 [0.375, 0.625]`.
- A cell is never blank, and every cell without a number has a footnote with its reason. There are four kinds:
  - `not run`: only for an experiment cut on purpose or a 04 §6 cell nothing covers ([04 §10 rule 8](../docs/04-evaluation-protocol.md)), and for results that cannot be used (no results directory, an incomplete result, a dirty work tree, another version of the YAML). The reason of a cut comes from `bench/results/not_run.yaml` (`<experiment_id or 04 §6 cell>: <reason>`, the R-16 cut list, citing its ADR). An entry that names neither an experiment YAML nor a 04 §6 cell is an error.
  - `revised`: a pre-registered experiment that a [04 §12](../docs/04-evaluation-protocol.md) revision replaces (`<revision id>: {revises: <pre-registered id>}` in the register). Its note reads `revised as <id>`, and the revision's rows follow it. An arm the revision drops names its cut and ADR.
  - `n/a`: a metric that does not apply to the row (no slate, no verdict, a metric the experiment does not list) or that the summary leaves null (undefined, e.g. no denominator). The note says which.
  - `no value`: a defined value that no committed file holds, e.g. a pooled value or interval that `summary.json` and `rq3-intervals` do not have. The tables compute no new statistics ([04 §10.2](../docs/04-evaluation-protocol.md)).
- Results in `bench_summary` 0.1.0 (the R-05 baselines) ran: their cells read `not tabulated`, and Table A0 lists them as `run (bench_summary 0.1.0)` with their provenance. Any version other than 0.1.0 that the tables do not read (they read 1.1 and 1.2) is an error.
- Output is byte-identical across runs and machines: no timestamp, no path, LF, canonical numbers. `bench/results/tables/` is generated only, and a stale `.md`/`.tex` there is removed on write.
- Figures go to `bench/results/figures/`: Figs 4, 6, 7, 8 and 9 are drawn. Fig 6 shows the risk-coverage areas (AURC of the verified and the fused score, and their difference), not curves, because `summary.json` keeps the areas only. Fig 5 stays a placeholder with its reason: its data is only in run directories that are not committed. Each `<name>.csv` holds every plotted value with its interval, status and source experiment and commit, and is the figure's data of record. Each panel is a deterministic `.svg` from `veyltrace_bench.tables.svg` (no plotting dependency; R-18 converts it to PDF). A point without a value is a CSV row with its reason, is never drawn as 0, and reads in a heatmap cell as the tables print it (`n/a`, `not run`, `revised` or `no value`).
