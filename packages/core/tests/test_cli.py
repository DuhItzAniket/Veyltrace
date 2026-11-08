"""The `veyltrace` CLI: exit codes per command (lead §2.8, 02 §6.10), delegation to entry points,
--summary-json, thread pins and UTF-8 output."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from veyltrace_core import cli, plugins
from veyltrace_core.errors import DiagnoseExit, ReplayExit
from veyltrace_core.fetch import FetchRequest
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.pipeline import run_case, summary_dict

CASE = make_case_id("synth-01")


def _diagnose(tmp_path: Path, *extra: str) -> list[str]:
    """diagnose argv writing under tmp_path (core.paths.runs is an environment key)."""
    runs = (tmp_path / "runs").as_posix()
    return ["diagnose", "--dataset", "synth", "--case", CASE, "--set", f"core.paths.runs={runs}", *extra]


def _summary(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# --- diagnose ----------------------------------------------------------------------------------
def test_diagnose_ok_writes_summary_and_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    summary_path = tmp_path / "out" / "summary.json"
    code = cli.main(_diagnose(tmp_path, "--summary-json", str(summary_path)))
    out = capsys.readouterr().out
    assert code == DiagnoseExit.OK, out
    assert "outcome: ok" in out
    summary = _summary(summary_path)
    assert summary["outcome"] == "ok" and summary["exit_code"] == 0
    assert summary["schema"] == cli.SUMMARY_SCHEMA
    assert summary_path.read_bytes().endswith(b"\n") and b"\r\n" not in summary_path.read_bytes()
    run_dir = Path(summary["run_dir"])
    assert (run_dir / "receipt.json").is_file()
    assert run_dir.is_relative_to(tmp_path.resolve())


def test_diagnose_rejected_case_exits_3(tmp_path: Path) -> None:
    # Shifting t_alert far past the data span empties both windows: CaseRejected("empty_window").
    summary_path = tmp_path / "summary.json"
    code = cli.main(
        _diagnose(tmp_path, "--set", "core.alert.shift_s=100000", "--summary-json", str(summary_path))
    )
    assert code == DiagnoseExit.REJECTED
    summary = _summary(summary_path)
    assert summary["outcome"] == "rejected" and summary["exit_code"] == DiagnoseExit.REJECTED


def test_diagnose_config_error_exits_4_and_still_writes_summary(tmp_path: Path) -> None:
    # No alert detector is registered before O-04, so the detected protocol is a config error.
    summary_path = tmp_path / "summary.json"
    code = cli.main(_diagnose(tmp_path, "--protocol", "detected", "--summary-json", str(summary_path)))
    assert code == DiagnoseExit.CONFIG
    summary = _summary(summary_path)
    assert summary["outcome"] == "failed" and summary["exit_code"] == DiagnoseExit.CONFIG
    assert summary["reason"] == "ConfigError" and summary["schema"] == cli.SUMMARY_SCHEMA


def test_diagnose_os_error_still_writes_summary(tmp_path: Path) -> None:
    """A file where the runs root should be (an OSError, not a VeyltraceError) still gives bench
    a summary: outcome failed, exit 1 (isolation review)."""
    blocker = tmp_path / "runsfile"
    blocker.write_bytes(b"x")
    summary_path = tmp_path / "summary.json"
    argv = [
        "diagnose", "--dataset", "synth", "--case", CASE,
        "--set", f"core.paths.runs={blocker.as_posix()}", "--summary-json", str(summary_path),
    ]  # fmt: skip
    code = cli.main(argv)
    assert code == DiagnoseExit.ERROR
    summary = _summary(summary_path)
    assert summary["outcome"] == "failed" and summary["exit_code"] == DiagnoseExit.ERROR
    assert summary["reason"] == "RunDirUnavailable"


def test_error_summary_shares_the_pipeline_summary_schema(tmp_path: Path) -> None:
    summary = run_case("synth", CASE, "off", {}, runs_root=tmp_path / "runs", code_commit="fixture")
    assert summary_dict(summary)["schema"] == cli.SUMMARY_SCHEMA


@pytest.mark.parametrize(
    "extra",
    [
        ("--ai", "bogus"),
        ("--set", "no-equals-sign"),
        ("--protocol", "oracle", "--set", "core.alert.protocol=detected"),
        ("--cassette-from", "0123456789abcdef"),  # only with --ai replay
        ("--to-step", "no-such-step"),
        ("--from-step", "causatrix", "--to-step", "alert"),
        ("--force-record",),  # only with --ai record
    ],
)
def test_diagnose_usage_errors_exit_2(tmp_path: Path, extra: tuple[str, ...]) -> None:
    assert cli.main(_diagnose(tmp_path, *extra)) == DiagnoseExit.USAGE


def test_diagnose_missing_required_option_exits_2() -> None:
    assert cli.main(["diagnose", "--dataset", "synth"]) == DiagnoseExit.USAGE


def test_diagnose_unknown_config_key_exits_4(tmp_path: Path) -> None:
    assert cli.main(_diagnose(tmp_path, "--set", "core.no_such_key=1")) == DiagnoseExit.CONFIG


def test_diagnose_partial_run_to_alert(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(_diagnose(tmp_path, "--to-step", "alert")) == DiagnoseExit.OK
    run_dir = Path(capsys.readouterr().out.split("run_dir: ")[1].splitlines()[0])
    assert run_dir.name.endswith("~alert")
    assert (run_dir / "alert.json").is_file() and not (run_dir / "signal_cube").exists()


def test_cassette_from_resolves_a_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "rec"
    (run_dir / "cassette").mkdir(parents=True)
    got = cli._cassette_dir(str(run_dir), "replay", lambda: tmp_path)
    assert got == run_dir / "cassette"


def test_cassette_from_unknown_run_id_is_a_usage_error(tmp_path: Path) -> None:
    from veyltrace_core.errors import UsageError

    with pytest.raises(UsageError, match="no run with that id"):
        cli._cassette_dir("0123456789abcdef", "replay", lambda: tmp_path)


# --- delegated commands -------------------------------------------------------------------------
def _fake_command(monkeypatch: pytest.MonkeyPatch, name: str, code: int) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_main(argv: list[str]) -> int:
        calls.append(argv)
        return code

    real_names, real_load = plugins.names, plugins.load_one

    def names(group: str) -> tuple[str, ...]:
        return (name,) if group == cli.COMMANDS_GROUP else real_names(group)

    def load_one(group: str, entry: str) -> object:
        return fake_main if (group, entry) == (cli.COMMANDS_GROUP, name) else real_load(group, entry)

    monkeypatch.setattr(plugins, "names", names)
    monkeypatch.setattr(plugins, "load_one", load_one)
    return calls


def test_replay_without_causivra_is_a_clear_error(capsys: pytest.CaptureFixture[str]) -> None:
    if cli.REPLAY_COMMAND in plugins.names(cli.COMMANDS_GROUP):
        pytest.skip("a replay command is installed")
    assert cli.main(["replay", "receipt.json"]) == ReplayExit.ERROR
    assert "veyltrace.commands:replay" in capsys.readouterr().err


def test_replay_delegates_argv_and_returns_its_code(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_command(monkeypatch, "replay", ReplayExit.HASH_MISMATCH)
    assert cli.main(["replay", "r.json", "--full", "--keep", "--report", "x.md"]) == ReplayExit.HASH_MISMATCH
    assert calls == [["r.json", "--full", "--keep", "--report", "x.md"]]


def test_replay_usage_error_exits_1_not_2() -> None:
    # 2 means "verdict hash mismatch" under replay (02 §6.10), so usage errors are plain errors.
    assert cli.main(["replay"]) == ReplayExit.ERROR
    assert cli.main(["--log-level", "debug", "replay"]) == ReplayExit.ERROR


def test_bench_run_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_command(monkeypatch, "bench", 0)
    assert cli.main(["bench", "run", "bench/experiments/x.yaml", "--workers", "2"]) == 0
    assert calls == [["run", "bench/experiments/x.yaml", "--workers", "2"]]


def test_bench_run_without_bench_is_a_clear_error(capsys: pytest.CaptureFixture[str]) -> None:
    if cli.BENCH_COMMAND in plugins.names(cli.COMMANDS_GROUP):
        pytest.skip("a bench command is installed")
    assert cli.main(["bench", "run", "x.yaml"]) == DiagnoseExit.ERROR
    assert "veyltrace.commands:bench" in capsys.readouterr().err


def test_data_fetch_builds_a_fetch_request(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[FetchRequest] = []

    def fetch(request: FetchRequest) -> int:
        seen.append(request)
        return 0

    real_names, real_load = plugins.names, plugins.load_one
    fake: dict[str, Callable[[FetchRequest], int]] = {"rcaeval": fetch}

    def names(group: str) -> tuple[str, ...]:
        return tuple(sorted(fake)) if group == plugins.FETCHERS else real_names(group)

    def load_one(group: str, name: str) -> object:
        return fake[name] if group == plugins.FETCHERS else real_load(group, name)

    monkeypatch.setattr(plugins, "names", names)
    monkeypatch.setattr(plugins, "load_one", load_one)
    code = cli.main(["data", "fetch", "rcaeval", "--suite", "re2-ss", "--source", "hf", "--cases", "1"])
    assert code == 0
    assert seen == [
        FetchRequest(
            name="rcaeval",
            data_root=Path(os.environ["VEYLTRACE_DATA"]).resolve(),
            suite="re2-ss",
            source="hf",
            cases=1,
        )
    ]


def test_data_fetch_unknown_fetcher_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugins, "names", lambda group: ())
    assert cli.main(["data", "fetch", "nope"]) == DiagnoseExit.USAGE


def test_data_fetch_rejects_bad_options() -> None:
    assert cli.main(["data", "fetch", "synth", "--source", "ftp"]) == DiagnoseExit.USAGE
    assert cli.main(["data", "fetch", "synth", "--cases", "0"]) == DiagnoseExit.USAGE


def test_fetch_request_validates() -> None:
    with pytest.raises(ValueError):
        FetchRequest(name="", data_root=Path())
    with pytest.raises(ValueError):
        FetchRequest(name="x", data_root=Path(), cases=0)
    with pytest.raises(ValueError):
        FetchRequest(name="x", data_root=Path(), source=cast("Any", "ftp"))


# --- entry point, encoding, thread pins ----------------------------------------------------------
def test_help_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--help"]) == 0
    out = capsys.readouterr().out
    for command in ("diagnose", "replay", "bench", "data"):
        assert command in out


def test_bare_app_call_exits_with_main_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["veyltrace", "--help"])
    with pytest.raises(SystemExit) as info:
        cli.app()
    assert info.value.code == 0


def _python(code: str, env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    full_env = {k: v for k, v in os.environ.items() if k not in cli.THREAD_ENV}
    full_env.update(env)
    return subprocess.run([sys.executable, "-c", code], env=full_env, capture_output=True, check=True)


def test_thread_pins_are_set_on_import_and_respect_the_caller() -> None:
    probe = "import os, veyltrace_core.cli as c; print(','.join(os.environ[v] for v in c.THREAD_ENV))"
    assert _python(probe, {}).stdout.strip() == b"1,1,1"
    assert _python(probe, {"OMP_NUM_THREADS": "4"}).stdout.strip() == b"4,1,1"


def test_thread_pins_run_before_any_other_import() -> None:
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    kinds = [type(n).__name__ for n in body[:4]]
    assert kinds == ["ImportFrom", "Import", "Assign", "For"]  # __future__, os, _THREAD_ENV, the pins


def test_stdout_is_reconfigured_to_utf8() -> None:
    probe = "import sys; from veyltrace_core.cli import main; main(['--help']); print(sys.stdout.encoding)"
    result = _python(probe, {"PYTHONIOENCODING": "cp1252"})
    assert result.stdout.strip().splitlines()[-1].lower().replace(b"-", b"") == b"utf8"


def test_diagnose_warns_about_stub_outputs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from veyltrace_core import stubs

    assert stubs.STUB_NOTE.startswith(cli.STUB_MARK)
    assert cli.main(_diagnose(tmp_path)) == DiagnoseExit.OK
    assert "placeholder outputs" in capsys.readouterr().err


def test_stub_infralume_refuses_real_datasets_without_an_adapter(tmp_path: Path) -> None:
    runs = (tmp_path / "runs").as_posix()
    argv = ["diagnose", "--dataset", "re2-ob", "--case", "abcdefabcdef", "--set", f"core.paths.runs={runs}"]
    assert cli.main(argv) == DiagnoseExit.CONFIG  # no adapter: exit 4, not "ok" on fake data
