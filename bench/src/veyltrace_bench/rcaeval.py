"""RCAEval baselines (`rcaeval:<method>`, 04 §4): RCAEval's own main.py, run in its isolated venv.

RCAEval is never imported here (bench/AGENTS.md): bench writes each case in the layout main.py reads
(`<DATASET_MAP path>/<service>_<fault>/<case_id>/simple_metrics.csv` + `inject_time.txt`), runs
`main.py --method M --dataset D --length L --report-chance --report-decomposition K` once per
(dataset, method) in a work directory whose `output/` is deleted first (main.py scores every stale
result file it finds), and reads back `output/results/<service>_<fault>_<case_id>.json`. The
metrics come from Infralume's `telemetry.metrics` pivoted back to RCAEval's wide columns
(`{component}_{name}`, one row per second), so every method sees the same inputs; `inject_time` is
the run's `alert.json` t_alert, so baselines get Veyltrace's alert time (04 §4). main.py itself
drops `_latency-50` and renames `_latency-90` to `_latency` before the method runs (#15 note).
Its printed report (Avg@5 per fault, chance, decomposition) is stored next to bench's results.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from veyltrace_bench import baselines
from veyltrace_contracts.models import Alert, AnswerKeyRow
from veyltrace_core import io, textio
from veyltrace_core.errors import ConfigError, VeyltraceError

NS = 1_000_000_000
METRICS_FILE = "simple_metrics.csv"  # the file main.py globs for on RE2/RE3 (main.py)
INJECT_FILE = "inject_time.txt"  # one integer of Unix seconds, read with int() (main.py)
NO_FAULT_LABEL = "nofault_none"  # folder of a case without truth: two `_` tokens, as main.py splits
MS_PER_S = 1000.0
#: Workspace variables that must not leak into RCAEval's interpreter.
ENV_DROP = ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DatasetMap(_Strict):
    id: str  # main.py --dataset choice
    path: str  # DATASET_MAP directory, relative to main.py's working directory


class Settings(_Strict):
    """The `rcaeval` section of bench/baselines.yaml (values and sources there)."""

    repo: str
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    venv: str
    source: str
    methods: tuple[str, ...] = Field(min_length=1)
    datasets: dict[str, DatasetMap]
    report_decomposition: int = Field(ge=1)


class MethodArgs(_Strict):
    """A method's `rcaeval:` block in the experiment YAML (04 §9)."""

    method: str
    length: int = Field(default=20, ge=1)  # main.py --length default (minutes, both sides together)


@dataclass(frozen=True)
class MainResult:
    """One main.py run: ranks per case id (None: no result file), its stdout report, wall time."""

    ranks: dict[str, tuple[str, ...] | None]
    report: str
    wall_ms: float
    timed_out: bool


def settings(repo: Path | None = None) -> Settings:
    return baselines.load("rcaeval", Settings, repo)


def method_args(raw: dict[str, object] | None, cfg: Settings, method_id: str) -> MethodArgs:
    """The method's rcaeval block, checked against the methods the wrapper can feed."""
    try:
        args = MethodArgs.model_validate(raw or {})
    except ValidationError as exc:
        raise ConfigError(f"method {method_id}: rcaeval block: {exc}") from None
    if args.method not in cfg.methods:
        raise ConfigError(f"method {method_id}: rcaeval.method {args.method!r} is not in {list(cfg.methods)}")
    return args


def python_path(cfg: Settings, repo: Path) -> Path:
    venv = repo / cfg.venv
    return venv / "Scripts" / "python.exe" if sys.platform == "win32" else venv / "bin" / "python"


def check_environment(cfg: Settings, repo: Path) -> None:
    """The venv and the clone at the pinned commit exist; else point at the setup script."""
    fix = "run `uv run python scripts/rcaeval/setup.py` (04 §4 RCAEval environment)"
    main = repo / cfg.source / "main.py"
    if not python_path(cfg, repo).is_file() or not main.is_file():
        raise ConfigError(f"RCAEval venv or source missing under {cfg.venv}: {fix}")
    head = subprocess.run(
        ["git", "-C", str(repo / cfg.source), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if head != cfg.commit:
        raise ConfigError(f"RCAEval source is at {head or 'no commit'}, not the pinned {cfg.commit}: {fix}")


def case_dir(workdir: Path, mapping: DatasetMap, key: AnswerKeyRow) -> Path:
    """Where main.py finds the case: `<path>/<service>_<fault>/<case_id>/`; main.py scores against
    this folder label, so a no-fault case gets a placeholder label outside its six fault groups."""
    if key.is_no_fault or key.root_service is None:
        label = NO_FAULT_LABEL
    else:
        label = f"{key.root_service}_{(key.fault_label or key.fault_class or 'unknown').replace('_', '-')}"
    return workdir / mapping.path / label / key.case_id


def _cell(value: float) -> str:
    return "" if math.isnan(value) else repr(value)


def export_case(run_dir: Path, dest: Path) -> None:
    """Write the run's metrics as RCAEval's wide CSV (`time` + `{component}_{name}`, sorted; a
    missing point is empty, read as NaN) and t_alert in whole seconds as inject_time.txt."""
    table = io.read_table("telemetry.metrics", run_dir, columns=["t_ns", "component", "name", "value"])
    seconds = np.asarray(table.column("t_ns").to_numpy(), dtype=np.int64) // NS
    names = [
        f"{c}_{n}"
        for c, n in zip(table.column("component").to_pylist(), table.column("name").to_pylist(), strict=True)
    ]
    values = np.asarray(table.column("value").to_numpy(), dtype=np.float64)
    columns, times = sorted(set(names)), np.unique(seconds)
    col_of, row_of = {c: i for i, c in enumerate(columns)}, {int(t): i for i, t in enumerate(times)}
    grid = np.full((len(times), len(columns)), np.nan)
    for t, name, value in zip(seconds.tolist(), names, values.tolist(), strict=True):
        grid[row_of[t], col_of[name]] = value  # sorted rows: the last value within a second wins
    lines = [",".join(["time", *columns])]
    lines += [
        ",".join([str(int(t)), *(_cell(v) for v in row)]) for t, row in zip(times, grid.tolist(), strict=True)
    ]
    alert = io.read_model("alert", run_dir, Alert)
    dest.mkdir(parents=True, exist_ok=True)
    textio.write_bytes(dest / METRICS_FILE, ("\n".join(lines) + "\n").encode())
    textio.write_bytes(dest / INJECT_FILE, f"{alert.t_alert_ns // NS}\n".encode())


def run_main(
    cfg: Settings,
    repo: Path,
    workdir: Path,
    mapping: DatasetMap,
    args: MethodArgs,
    case_ids: list[str],
    timeout_s: float,
) -> MainResult:
    """Run main.py on every case exported under `workdir`; its output/ is deleted first."""
    output = workdir / "output"
    if output.exists():
        shutil.rmtree(output)
    cmd = [str(python_path(cfg, repo)), str(repo / cfg.source / "main.py"), "--method", args.method]
    cmd += ["--dataset", mapping.id, "--length", str(args.length), "--report-chance"]
    cmd += ["--report-decomposition", str(cfg.report_decomposition)]
    env = {k: v for k, v in os.environ.items() if k not in ENV_DROP} | {"PYTHONIOENCODING": "utf-8"}
    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=workdir, env=env, capture_output=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        return MainResult(dict.fromkeys(case_ids), "", (time.perf_counter() - start) * MS_PER_S, True)
    wall_ms = (time.perf_counter() - start) * MS_PER_S
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace")[-2000:]
        raise VeyltraceError(
            f"RCAEval main.py --method {args.method} --dataset {mapping.id} exited {proc.returncode}:\n{tail}"
        )
    found = {p.stem.rpartition("_")[2]: p for p in sorted((output / "results").glob("*.json"))}
    ranks: dict[str, tuple[str, ...] | None] = {}
    for case in case_ids:
        path = found.get(case)
        data = json.loads(textio.read_text(path)) if path is not None else None  # RCAEval's JSON
        got = data.get("0") if isinstance(data, dict) else None
        ranks[case] = tuple(str(r) for r in got) if isinstance(got, list) else None
    return MainResult(ranks, proc.stdout.decode("utf-8", "replace"), wall_ms, False)
