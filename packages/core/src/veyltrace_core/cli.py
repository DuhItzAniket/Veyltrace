"""The `veyltrace` command line: diagnose, replay, bench run, data fetch and data list.

Why it is shaped this way:
- Thread pins come first, before anything can import numpy: BLAS/OpenMP thread counts change
  float summation order, so results would differ between laptops and CI (M0 lead decision
  2026-11-06 §2.12). They use setdefault, so a caller's explicit value wins.
- stdout and stderr are reconfigured to UTF-8, because the team's Windows consoles default to
  cp1252 and paths or card titles may hold non-ASCII text (lead §2.12).
- Exit codes are the shared vocabulary of `veyltrace_core.errors`: diagnose 0 ok, 1 error,
  2 usage, 3 case rejected or inputs missing, 4 config, 7 no_alert (lead §2.8); replay 0–6 as in
  02 §6.10, where a usage error is a plain error (1) because 2 means a hash mismatch there.
- `replay` and `bench` delegate to `veyltrace.commands` entry points (Causivra, bench) and
  `data fetch` to `veyltrace.fetchers`, so core never imports another lane's package
  (core_api_spec §9, §12). A missing delegate is a clear error naming the entry point.
- `diagnose --summary-json PATH` writes a canonical RunSummary outside the run directory, so
  bench learns the outcome of a subprocess run, including no_alert, rejected and failed runs,
  which write no manifest (critic gap "bench can't learn run outcomes").

The console script is `veyltrace = "veyltrace_core.cli:app"`; a bare `app()` call runs `main()`,
which owns the exit-code mapping. Tests call `main(argv)` directly.
"""

from __future__ import annotations

import os

# Thread pins (see module docstring). They must run before numpy is imported by anything below.
_THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
for _var in _THREAD_ENV:
    os.environ.setdefault(_var, "1")

import io  # noqa: E402  (after the thread pins on purpose)
import sys  # noqa: E402
import traceback  # noqa: E402
from collections.abc import Callable, Mapping, Sequence  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import TYPE_CHECKING, Any, Final, cast  # noqa: E402

import typer  # noqa: E402
from typer.exceptions import TyperException  # noqa: E402

from veyltrace_contracts.models import AlertProtocol  # noqa: E402
from veyltrace_core.canonical import canonical_json  # noqa: E402
from veyltrace_core.errors import (  # noqa: E402
    CaseRejected,
    DiagnoseExit,
    NoAlert,
    ReplayExit,
    UsageError,
    VeyltraceError,
    exit_code_for,
)
from veyltrace_core.fetch import FetchSource  # noqa: E402
from veyltrace_core.ids import AIMode, is_run_id  # noqa: E402
from veyltrace_core.log import LogFormat, LogLevel, get_logger  # noqa: E402
from veyltrace_core.log import configure as configure_logging  # noqa: E402

if TYPE_CHECKING:
    from veyltrace_core.pipeline import StepEvent

__all__ = ["PROG", "SUMMARY_SCHEMA", "THREAD_ENV", "app", "error_summary", "main"]

PROG: Final = "veyltrace"
THREAD_ENV: Final[tuple[str, ...]] = _THREAD_ENV
PROTOCOL_KEY: Final = "core.alert.protocol"
#: Entry-point group and names of the delegated commands (core_api_spec §9).
COMMANDS_GROUP: Final = "veyltrace.commands"
REPLAY_COMMAND: Final = "replay"
BENCH_COMMAND: Final = "bench"
#: Run-dir subdirectory holding the LLM cassette (02 §4.1); the same value as pipeline.CASSETTE_DIR.
CASSETTE_DIR: Final = "cassette"
#: Version tag of the error summary: the value pipeline.summary_dict writes as "schema" (a test
#: checks the two agree).
SUMMARY_SCHEMA: Final = "veyltrace.run_summary/1"
#: Prefix of every stub note: core's stubs.STUB_NOTE ("stub: R-02 bootstrap ...") and each
#: package's own stub ("stub: R-00 ...", likewise O-00 / X-00). diagnose warns when a step result
#: note starts with it, since EngineResult.notes are not stored in any artefact (the stubs module
#: is not imported here, so the CLI stays importable without it).
STUB_MARK: Final = "stub: "
#: Exit code click (vendored by typer) gives a usage error; mapped per command in main().
_CLICK_USAGE_EXIT: Final = 2

_log = get_logger("veyltrace_core.cli")
_PASS_THROUGH: Final = {"allow_extra_args": True, "ignore_unknown_options": True}
#: Root-callback options that take a separate value token (see _command_name).
_GLOBAL_VALUE_OPTIONS: Final = frozenset({"--log-level", "--log-format"})


def _reconfigure_streams() -> None:
    """Make stdout/stderr UTF-8 whatever the console code page is (lead §2.12)."""
    for stream, errors in ((sys.stdout, "strict"), (sys.stderr, "backslashreplace")):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors=errors)


def _fail(message: str) -> None:
    typer.echo(f"{PROG}: error: {message}", err=True)


# ---------------------------------------------------------------------------------------------
# App
class _VeyltraceApp(typer.Typer):
    """A Typer app whose bare call (the console script) runs `main()` and exits with its code."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if args or kwargs:
            return super().__call__(*args, **kwargs)
        sys.exit(main())


app = _VeyltraceApp(
    name=PROG,
    help="Veyltrace v2: root-cause analysis for microservice outages.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
bench_app = typer.Typer(name="bench", help="Benchmark experiments (veyltrace_bench).", no_args_is_help=True)
data_app = typer.Typer(name="data", help="Fetch and list datasets.", no_args_is_help=True)
app.add_typer(bench_app)
app.add_typer(data_app)


@app.callback()
def _root(
    log_level: LogLevel = typer.Option("info", "--log-level", help="Log level on stderr."),
    log_format: LogFormat = typer.Option("text", "--log-format", help="Log line format on stderr."),
) -> None:
    """Veyltrace v2: root-cause analysis for microservice outages."""
    configure_logging(level=log_level, fmt=log_format)


# ---------------------------------------------------------------------------------------------
# diagnose
def _overrides(sets: Sequence[str], protocol: str | None) -> dict[str, Any]:
    """`--set` assignments (YAML 1.2 values, config.parse_assignments) plus `--protocol`."""
    from veyltrace_core.config import parse_assignments

    overrides: dict[str, Any] = dict(parse_assignments(list(sets)))
    if protocol is not None:
        if PROTOCOL_KEY in overrides and overrides[PROTOCOL_KEY] != protocol:
            msg = f"--protocol {protocol} contradicts --set {PROTOCOL_KEY}={overrides[PROTOCOL_KEY]}"
            raise UsageError(msg)
        overrides[PROTOCOL_KEY] = protocol
    return overrides


def _runs_root(overrides: Mapping[str, Any], dataset: str, ai_mode: AIMode) -> Path:
    """The runs root a run with these settings writes under (pipeline.runs_root)."""
    from veyltrace_core.config import resolve_config
    from veyltrace_core.pipeline import runs_root

    return runs_root(resolve_config(overrides, dataset=dataset, ai_mode=ai_mode))


def _cassette_dir(cassette_from: str | None, ai_mode: AIMode, runs_root: Callable[[], Path]) -> Path | None:
    """Resolve --cassette-from (a run id or a run directory) to the cassette directory to replay."""
    if cassette_from is None:
        return None
    if ai_mode != "replay":
        msg = "--cassette-from only applies with --ai replay"
        raise UsageError(msg)
    candidate = Path(cassette_from)
    if candidate.is_dir():
        nested = candidate / CASSETTE_DIR
        return nested if nested.is_dir() else candidate
    if not is_run_id(cassette_from):
        msg = f"--cassette-from expects a run id or a run directory, got {cassette_from!r}"
        raise UsageError(msg)
    from veyltrace_core.pipeline import find_run

    root = runs_root()
    run_dir = find_run(cassette_from, root)
    if run_dir is None:
        msg = f"--cassette-from {cassette_from}: no run with that id under {root}"
        raise UsageError(msg)
    return run_dir / CASSETTE_DIR


def error_summary(dataset: str, case: str, exc: BaseException) -> dict[str, Any]:
    """The --summary-json object when the run raised before producing a RunSummary (usage,
    config, missing plugins, a held lock). It shares the "schema", outcome, reason and exit_code
    keys of pipeline.summary_dict, so bench reads both the same way."""
    if isinstance(exc, CaseRejected):
        outcome, reason = "rejected", str(exc.reason)
    elif isinstance(exc, NoAlert):
        outcome, reason = "no_alert", type(exc).__name__
    else:
        outcome, reason = "failed", type(exc).__name__
    return {
        "schema": SUMMARY_SCHEMA,
        "dataset": dataset,
        "case": case,
        "outcome": outcome,
        "exit_code": exit_code_for(exc, "diagnose"),
        "reason": reason,
        "detail": str(exc),
    }


def _check_outside(path: Path, run_dir: Path) -> None:
    if path.resolve().is_relative_to(run_dir.resolve()):
        msg = f"--summary-json {path} must be outside the run directory {run_dir}"
        raise UsageError(msg)


def _progress(event: StepEvent) -> None:
    status = event.result.status if event.result is not None else None
    _log.info(f"step.{event.event}", index=event.index, step=event.name, status=status)


@app.command(help="Diagnose one case: run the pipeline and write a run directory.")
def diagnose(
    dataset: str = typer.Option(..., "--dataset", help="Dataset name, e.g. synth or re2-ob."),
    case: str = typer.Option(..., "--case", help="12-hex case id, or a resolvable name (synth-0N)."),
    ai: AIMode = typer.Option("off", "--ai", help="AI mode."),
    protocol: AlertProtocol | None = typer.Option(
        None, "--protocol", "--alert", help=f"Alert protocol; same as --set {PROTOCOL_KEY}=X."
    ),
    sets: list[str] = typer.Option([], "--set", help="Override key=value (YAML 1.2 value); repeatable."),
    from_step: str | None = typer.Option(None, "--from-step", help="First sub-step (steps.STEPS name)."),
    to_step: str | None = typer.Option(None, "--to-step", help="Last sub-step (partial run directory)."),
    force_record: bool = typer.Option(False, "--force-record", help="With --ai record, overwrite a run."),
    summary_path: Path | None = typer.Option(None, "--summary-json", help="Write a RunSummary JSON here."),
    cassette_from: str | None = typer.Option(
        None, "--cassette-from", help="With --ai replay: run id or run dir whose cassette to replay."
    ),
) -> None:
    from veyltrace_core import textio
    from veyltrace_core.pipeline import run_case, write_summary

    try:
        overrides = _overrides(sets, protocol)
        plan: dict[str, Any] = {"force_record": force_record}
        if from_step is not None:
            plan["from_step"] = from_step
        if to_step is not None:
            plan["to_step"] = to_step
        cassette_dir = _cassette_dir(cassette_from, ai, lambda: _runs_root(overrides, dataset, ai))
        if cassette_dir is not None:
            plan["cassette_dir"] = cassette_dir
        summary = run_case(dataset, case, ai, overrides, progress=_progress, **plan)
    except Exception as exc:  # any error, not only VeyltraceError: bench must learn the outcome
        if summary_path is not None:
            textio.write_bytes(summary_path, canonical_json(error_summary(dataset, case, exc)) + b"\n")
        raise
    if summary_path is not None:
        _check_outside(summary_path, summary.run_dir)
        write_summary(summary, summary_path)
    if any(note.startswith(STUB_MARK) for result in summary.results for note in result.notes):
        typer.echo(
            "warning: stub engines wrote placeholder outputs (R-02 bootstrap or package stubs); "
            "results are not analysis",
            err=True,
        )
    typer.echo(f"outcome: {summary.outcome}")
    typer.echo(f"run_id: {summary.run_id}")
    typer.echo(f"run_dir: {summary.run_dir}")
    if summary.reason:
        typer.echo(f"reason: {summary.reason}")
    if summary.failed_step:
        typer.echo(f"failed_step: {summary.failed_step}")
    if summary.outcome == "failed" and summary.error is not None:
        _fail(f"{type(summary.error).__name__}: {summary.error}")
    raise typer.Exit(int(summary.exit_code))


# ---------------------------------------------------------------------------------------------
# Delegated commands
def _command_main(name: str) -> Callable[[list[str]], int] | None:
    """The `veyltrace.commands:<name>` entry point, or None when no package provides it."""
    from veyltrace_core import plugins

    if name not in plugins.names(COMMANDS_GROUP):
        return None
    fn = plugins.load_one(COMMANDS_GROUP, name)
    if not callable(fn):
        msg = f"{COMMANDS_GROUP}:{name} must be callable as main(argv) -> int"
        raise UsageError(msg)
    return cast("Callable[[list[str]], int]", fn)


@app.command(
    context_settings=_PASS_THROUGH,
    help="Replay a verdict from its receipt (delegates to Causivra; exit codes 0-6, 02 §6.10).",
)
def replay(
    ctx: typer.Context,
    receipt: str = typer.Argument(..., help="Path to receipt.json (forwarded verbatim)."),
    full: bool = typer.Option(False, "--full", help="Re-hash the raw inputs and re-run steps 0-10."),
) -> None:
    fn = _command_main(REPLAY_COMMAND)
    if fn is None:
        _fail(
            f"`{PROG} replay` needs the Causivra replay command ({COMMANDS_GROUP}:{REPLAY_COMMAND}), "
            "which is not installed yet (Explain lane, Causivra replay)"
        )
        raise typer.Exit(int(ReplayExit.ERROR))
    argv = [receipt, *(["--full"] if full else []), *ctx.args]
    raise typer.Exit(int(fn(argv)))


@bench_app.command("run", context_settings=_PASS_THROUGH, help="Run an experiment YAML (veyltrace_bench).")
def bench_run(
    ctx: typer.Context, experiment: str = typer.Argument(..., help="bench/experiments/<name>.yaml")
) -> None:
    fn = _command_main(BENCH_COMMAND)
    if fn is None:
        _fail(
            f"`{PROG} bench run` needs the bench command ({COMMANDS_GROUP}:{BENCH_COMMAND}), "
            "which is not installed yet (bench harness)"
        )
        raise typer.Exit(int(DiagnoseExit.ERROR))
    raise typer.Exit(int(fn(["run", experiment, *ctx.args])))


@data_app.command("fetch", help="Download (or, for synth, generate) a dataset under VEYLTRACE_DATA.")
def data_fetch(
    name: str = typer.Argument(..., help="Fetcher name, e.g. synth or rcaeval."),
    suite: str | None = typer.Option(None, "--suite", help="Sub-suite, e.g. re2-ss."),
    source: FetchSource | None = typer.Option(None, "--source", help="Download mirror."),
    cases: int | None = typer.Option(None, "--cases", min=1, help="Fetch at most N cases."),
) -> None:
    from veyltrace_core import plugins
    from veyltrace_core.config import data_root
    from veyltrace_core.fetch import FetchRequest

    available = plugins.names(plugins.FETCHERS)
    if name not in available:
        msg = f"unknown fetcher {name!r}; installed: {', '.join(available) or 'none'}"
        raise UsageError(msg)
    fn = plugins.load_one(plugins.FETCHERS, name)
    if not callable(fn):
        msg = f"{plugins.FETCHERS}:{name} must be callable as fetch(FetchRequest) -> int"
        raise UsageError(msg)
    request = FetchRequest(name=name, data_root=data_root(), suite=suite, source=source, cases=cases)
    raise typer.Exit(int(cast("Callable[[FetchRequest], int]", fn)(request)))


@data_app.command("list", help="List the case ids of a dataset (adapter.list_cases).")
def data_list(dataset: str = typer.Argument(..., help="Dataset name, e.g. synth.")) -> None:
    from veyltrace_core.adapters import adapter_for
    from veyltrace_core.config import data_root

    for case_id in adapter_for(dataset).list_cases(dataset, data_root()):
        typer.echo(case_id)


# ---------------------------------------------------------------------------------------------
# Entry point
def _command_name(args: Sequence[str]) -> str | None:
    """The top-level command in `args`: the first token that is neither an option nor the
    value of a global option (`--log-level debug replay …` is a replay)."""
    tokens = iter(args)
    for arg in tokens:
        if arg in _GLOBAL_VALUE_OPTIONS:
            next(tokens, None)
        elif not arg.startswith("-"):
            return arg
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI on `argv` (default sys.argv[1:]) and return the process exit code."""
    _reconfigure_streams()
    args = list(sys.argv[1:] if argv is None else argv)
    exit_as = "replay" if _command_name(args) == REPLAY_COMMAND else "diagnose"
    try:
        rv: object = typer.main.get_command(app).main(args=args, prog_name=PROG, standalone_mode=False)
    except typer.Exit as exc:
        return int(exc.exit_code)
    except typer.Abort:
        _fail("aborted")
        return int(DiagnoseExit.ERROR)
    except TyperException as exc:
        # typer's vendored click exceptions (usage errors, bad parameters) all derive from
        # TyperException and carry exit_code and show(); click gives a usage error exit 2.
        show: object = getattr(exc, "show", None)
        if callable(show):
            show()
        else:
            _fail(str(exc))
        code = int(getattr(exc, "exit_code", DiagnoseExit.ERROR))
        return exit_code_for(UsageError(str(exc)), exit_as) if code == _CLICK_USAGE_EXIT else code
    except VeyltraceError as exc:
        _fail(str(exc))
        for note in getattr(exc, "__notes__", ()):
            typer.echo(f"  {note}", err=True)
        return exit_code_for(exc, exit_as)
    except Exception:
        traceback.print_exc()
        return int(DiagnoseExit.ERROR)
    return int(rv) if isinstance(rv, int) else int(DiagnoseExit.OK)


if __name__ == "__main__":
    sys.exit(main())
