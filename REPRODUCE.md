# Reproducing the Veyltrace v1.0 results

This guide covers three levels of reproduction, from minutes to hours:

1. **Rebuild every table from the committed results.** This is one command, and the result should be byte-identical.
2. **Rerun the AI-off experiments** at the commit that produced them. The result should be identical.
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

```bash
git clone https://github.com/DuhItzAniket/Veyltrace.git && cd Veyltrace
uv sync --all-packages
export VEYLTRACE_DATA=$HOME/veyltrace-data     # outside the repo; PowerShell: $env:VEYLTRACE_DATA = "$HOME\veyltrace-data"
```

## 1. Tables from the committed results (one command)

```bash
uv run veyltrace bench tables --check
```

- The command reads only `bench/experiments/*.yaml` and `bench/results/`, and it writes nothing.
- Run it at `v1.0.0` or later. The tables are committed at the R-17 result freeze, so on earlier commits `--check` prints `differs: <path>` for every table and figure, because none is committed yet.
- Options: `--check`, `--results <dir>` (default `bench/results`) and `--experiments <dir>` (default `bench/experiments`). `veyltrace bench tables --help` shows only `--help`, because the core CLI hands the arguments to bench unparsed.
- Exit 0 means that every table and figure under `bench/results/tables/` and `bench/results/figures/` regenerates byte-identically, including the headline Table 5 (RQ1, RE2, oracle alert).
- Exit 2 lists the files that differ.
- Every table names the experiment and commit of each row, and prints the SHA-256 of its `per_case.csv`, `summary.json` and `manifest.json`.

## 2. Rerun the AI-off experiments

Check out the commit that the result's `manifest.json` names (`code.commit`). The commit is in the run id, so a different commit gives different run ids, though the same scores are expected.

| Tag | Commit | Results produced there |
|---|---|---|
| `results-code-v1` | `9e553e1c` | the engine freeze (R-16): RQ1, RQ2 (scored by replaying the recordings), RQ4 and the other AI-off experiments run from it |
| `results-code-v1-cpu` | `281787f1` | `results-code-v1` plus the two 04 §12 revision YAMLs: `re2-oracle-rq3-off-v1`, `re2-oracle-loso-off-v1` |
| `results-replay-v1` | `a2cdc166` | `results-code-v1` plus the RQ6 replay fixes: `replay/recording` |

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
  - The recordings hold the benchmark's telemetry, so the archive is shared privately and is not in this repository or the release.
- **New recording (not exact).**
  - Recording again with the same model and seeds does not give byte-identical proposals: Tier 2 matched 0 of 50 regenerated runs.
  - The AI-arm numbers are therefore reproducible only statistically.
  - The deterministic pipeline (every AI-off number) is reproducible exactly.

## What is not reproduced

See [`bench/results/not_run.yaml`](bench/results/not_run.yaml) for the experiments cut from v1.0 and why (ADR [20261121-ak-r16-cut-list](docs/adr/20261121-ak-r16-cut-list.md)). Deviations from the pre-registration are listed in [04 §12](docs/04-evaluation-protocol.md).
