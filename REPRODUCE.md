# Reproducing the Veyltrace v1.0 results

This guide covers three levels of reproduction, from minutes to hours:

1. **Rebuild every table from the committed results.** This is one command, and the result should be byte-identical.
2. **Rerun the AI-off experiments** at the commit that produced them. The result should be identical with the OpenBLAS kernel pinned (§0).
3. **The AI arms.** They replay only from the private recordings, and a fresh recording is not byte-identical (RQ6).

Every number in the paper comes from `bench/results/<experiment_id>/` ([04 §9–§10](docs/04-evaluation-protocol.md)). Each `manifest.json` names the code commit that produced it.

## 0. Requirements

| | |
|---|---|
| OS | Windows 11 or Linux. Every R-16 number was produced on Windows 11 ([docs/team/ak.md](docs/team/ak.md)). Level 1 was also checked on macOS 15.5 arm64 (L-06, #54). |
| Tools | `git`, [`uv`](https://docs.astral.sh/uv/) (it installs Python 3.12) |
| Disk | about 3.1 GB for the RCAEval RE2 download and about 5.7 GB for the convert cache built on first use, plus the run directories: about 30 GB per RE2 experiment with every method (`re2-oracle-rq1-v1`: 31 GB). All measured on the recording host. Delete an experiment's runs directory once its results are written, unless a derived result reads it (below). |
| RAM | 16 GB was enough for one experiment at a time (`resources.workers: 1`) |
| Network | only for `veyltrace data fetch` and the RCAEval baseline environment |

**Pin the OpenBLAS kernel.** NumPy's bundled OpenBLAS chooses its kernel from the CPU at run time, and a different kernel changes the last digits of the regression behind FaultLoom's `intervention` evidence (#576).
- The recording host used `Haswell`.
- On an AVX2 CPU, set `OPENBLAS_CORETYPE=Haswell` (PowerShell: `$env:OPENBLAS_CORETYPE = "Haswell"`) for steps 2 and 3, to get the same bytes.
- Without the pin, verdicts are expected to match, but intermediate files may not.

```bash
git clone https://github.com/DuhItzAniket/Veyltrace.git && cd Veyltrace
uv sync --all-packages
export VEYLTRACE_DATA=$HOME/veyltrace-data     # outside the repo
```

The same in Windows PowerShell 5.1, the Windows 11 default, which has no `&&`:

```powershell
git clone https://github.com/DuhItzAniket/Veyltrace.git; cd Veyltrace
uv sync --all-packages
$env:VEYLTRACE_DATA = "$HOME\veyltrace-data"
```

## 1. Tables from the committed results (one command)

```bash
uv run veyltrace bench tables --check
```

- The command reads only `bench/experiments/*.yaml` and `bench/results/`, and it writes nothing.
- Run it at `v1.0.0` or later (until that tag exists: any `main` commit after #665, 27 Nov). On success it prints `tables --check: <n> files, 0 differ`. On commits before `results-v1` (`3ed9d7cd`, the R-17 result freeze) `--check` prints `differs: <path>` for every table and figure, because none is committed yet. At `results-v1` itself it passes on Windows only: on macOS and Linux three tables (A0, A2, 8c) list the perf-o11 files in another order, with every hash equal (#664, fixed before `v1.0.0`).
- Options: `--check`, `--results <dir>` (default `bench/results`) and `--experiments <dir>` (default `bench/experiments`). `veyltrace bench tables --help` shows only `--help`, because the core CLI hands the arguments to bench unparsed.
- Exit 0 means that every table and figure under `bench/results/tables/` and `bench/results/figures/` regenerates byte-identically, including the headline Table 5 (RQ1, RE2, oracle alert).
- Exit 2 lists the files that differ.
- Every table names the experiment and commit of each row, and prints the SHA-256 of its `per_case.csv`, `summary.json` and `manifest.json`.

## 2. Rerun the AI-off experiments

Check out the commit that the result's `manifest.json` names (`code.commit`). The commit is in the run id, so a different commit gives different run ids, though the same scores are expected.

| Tag | Commit | Results produced there |
|---|---|---|
| `results-code-v1` | `9e553e1c` | the engine freeze (R-16): RQ1, RQ2 (scored by replaying the recordings), RQ4 and the other AI-off experiments run from it |
| `results-code-v1-cpu` | `281787f1` | `results-code-v1` plus the two 04 §12 revision YAMLs. It produced `re2-oracle-rq3-off-v1` and `re2-oracle-loso-off-v1`, and every crossfit2 experiment with `calibration.fit: false`: the onset shifts, the source drops, metrics-only and the RCAEval-C cells. They reuse the rcaeval-re2 files that `re2-oracle-rq3-off-v1` fits, and `calibrated.check` reads that YAML. Run that experiment first, in the same checkout, so `config/calibration/` holds its files |
| `results-code-v1-prior` | `9cb317d7` | `results-code-v1` plus the bench-only `prior-only` floor (#562; 04 §12 row of 26 Nov): `re2-oracle-prior-only-v1`, `re3-oracle-prior-only-v1` |
| `results-replay-v1` | `a2cdc166` | `results-code-v1` plus the RQ6 replay fixes: `replay/recording` |
| `results-code-v1-baselines` | `1b2f3be5` | `results-code-v1` plus the RCAEval dataset entries for RE3 and Nezha in `bench/baselines.yaml` (#615), no engine or config change: `re3-oracle-rq1-v1` |
| `results-code-v1-baselines-2` | `0654af62` | `results-code-v1-baselines` with the Nezha entries pointing where RCAEval's `main.py` reads (#627), again only `bench/baselines.yaml`: `nezha-oracle-rq1-v1` |

Two tags mark states of `main` rather than run commits: `results-v1` (`3ed9d7cd`, R-17) is the results freeze, where step 1 regenerates every committed table and figure and from which the paper reads every number, and `v0.9.0` is the M4 milestone (results frozen, paper draft v1).

The headline experiment, as an example:

```bash
git checkout results-code-v1 && uv sync --all-packages
uv run veyltrace data fetch rcaeval --suite re2-ob     # also re2-ss, re2-tt; answer keys come with the fetch
uv run veyltrace data fetch rcaeval --suite re2-ss
uv run veyltrace data fetch rcaeval --suite re2-tt
uv run python scripts/rcaeval/setup.py                 # RCAEval baselines in bench/.venv-rcaeval (pinned commit)
uv run veyltrace bench run bench/experiments/re2-oracle-rq1-v1.yaml --out /tmp/vt-results --runs-root /tmp/vt-runs
```

- Then compare `/tmp/vt-results/re2-oracle-rq1-v1/per_case.csv` and `summary.json` with the committed files under `bench/results/re2-oracle-rq1-v1/`.
- `per_case.csv` holds `wall_ms` and `peak_rss_mb`, which differ between machines, so compare the score columns.
- `summary.json`'s accuracy entries and intervals are deterministic (seeded bootstrap). Its `cost` entry is not.
- On the recording host this run took 2 h 20 min (23 Nov, 16:35–18:55 IST).
- `--table` reproduces the committed layout exactly. It refuses a dirty work tree.

Derived results are rebuilt from the kept runs, so they need the runs root of step 2:

| Folder | Command |
|---|---|
| `rq3-intervals/` | rerun `re2-oracle-rq3-off-v1` at `results-code-v1-cpu` with `--runs-root /tmp/vt-runs`, then on `main`: `uv run python scripts/rq3_intervals.py --runs-root /tmp/vt-runs` |
| `rq5-ai-cost/` | `uv run --no-project python scripts/rq5_ai_cost.py --runs-root <runs root with bench-ai/>` (needs the AI recordings, see 3) |

## 3. The AI arms

The AI arms (`brief`, `agent-only:brief`) ran with `qwen3.5:9b`, the Q4_K_M blob with SHA-256 `02d45dc1…0278d`, under Ollama 0.40.16 on the recording host ([config/llm.yaml](config/llm.yaml), [docs/team/ak.md](docs/team/ak.md)).

- **Replay (exact).**
  - `uv run veyltrace bench replay --role second-laptop` replays the 801 kept recordings from a copy of `<runs root>/bench-ai`.
  - On the recording host, Tier 1 matched 801 of 801 (`bench/results/replay/recording/`).
  - On the second laptop (i5-1135G7, default kernel, no pin), 799 of 801 exited 0 and 800 reproduced the verdict (`bench/results/replay/second-laptop/`). One run timed out while another job loaded the laptop, and one card differed. `evidence.parquet` differed on 501 runs, and the cause is the OpenBLAS kernel (#576).
  - The recordings hold the benchmark's telemetry, so the archive is shared privately and is not in this repository or the release.
- **New recording (not exact).**
  - Recording again with the same model and seeds does not give byte-identical proposals: Tier 2 matched 0 of 50 regenerated runs.
  - The AI-arm numbers are therefore reproducible only statistically.
  - The deterministic pipeline (every AI-off number) is reproducible exactly, with the OpenBLAS kernel pinned (§0).

## What is not reproduced

See [`bench/results/not_run.yaml`](bench/results/not_run.yaml) for the experiments cut from v1.0 and why (ADR [20261121-ak-r16-cut-list](docs/adr/20261121-ak-r16-cut-list.md)). Deviations from the pre-registration are listed in [04 §12](docs/04-evaluation-protocol.md).
