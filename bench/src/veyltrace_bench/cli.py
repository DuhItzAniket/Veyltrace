"""`veyltrace bench run`: bench's `veyltrace.commands:bench` entry point.

Core's CLI delegates `veyltrace bench run <experiment.yaml> [options]` here as
`main(["run", <experiment.yaml>, *options])`, so core never imports bench (core_api_spec §9).

Exit codes reuse core's diagnose vocabulary (`veyltrace_core.errors`), so scripts read both alike:
- 0: results written. Failed, rejected, no_alert and timeout runs are per_case.csv rows, not errors.
- 1: error (a contract violation, an RCAEval layout error, anything else).
- 2: usage (bad arguments; `--table` on a dirty work tree or synth; synth without an out-of-repo `--out`).
- 3: input missing (experiment file, case list, answer keys: `veyltrace data fetch <dataset>`).
- 4: config (invalid experiment YAML or unknown key, a feature v0 cannot run yet, a bad override).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from veyltrace_bench.answer_keys import ANSWER_KEY
from veyltrace_bench.runner import run_experiment
from veyltrace_core.errors import ArtifactMissing, DiagnoseExit, VeyltraceError, exit_code_for


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="veyltrace bench", description="Veyltrace evaluation harness (04 §9)."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser(
        "run", help="run an experiment YAML; write per_case.csv, summary.json, manifest.json"
    )
    run.add_argument("experiment", type=Path, help="bench/experiments/<name>.yaml")
    run.add_argument("--out", type=Path, help="results root (default bench/results; synth needs one)")
    run.add_argument("--runs-root", type=Path, help="root of the run directories, default core.paths.runs")
    run.add_argument(
        "--table", action="store_true", help="results for a table: refuse a dirty work tree and synth"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the bench CLI on `argv` (default sys.argv[1:]) and return the process exit code."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse exits 2 on a usage error and 0 after --help
        return exc.code if isinstance(exc.code, int) else int(DiagnoseExit.USAGE)
    try:
        out_dir, _ = run_experiment(
            args.experiment, out_root=args.out, runs_root=args.runs_root, table=args.table
        )
    except VeyltraceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if isinstance(exc, ArtifactMissing) and exc.name == ANSWER_KEY:
            print("hint: answer keys come from `veyltrace data fetch <dataset>`", file=sys.stderr)
        return exit_code_for(exc, "diagnose")
    print(f"results: {out_dir.as_posix()}")  # metrics per group: <results>/summary.json
    return int(DiagnoseExit.OK)
