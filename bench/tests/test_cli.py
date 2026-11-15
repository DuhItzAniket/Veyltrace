"""Tests of `veyltrace bench run`, bench's veyltrace.commands entry point: delegation, exit codes.

The runner behind it is tested as a library in test_runner.py. Outputs go to tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyltrace_bench import cli as bench_cli
from veyltrace_bench import runner
from veyltrace_core import cli, textio

SMOKE = Path(__file__).resolve().parents[1] / "experiments" / "synth-smoke.yaml"
OUTPUTS = ("summary.json", "manifest.json")


def test_synth_smoke_runs_through_the_core_cli_and_again_byte_identically(tmp_path: Path) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    argv = ["run", str(SMOKE), "--out", str(tmp_path / "results"), "--runs-root", str(tmp_path / "runs")]
    assert cli.main(["bench", *argv]) == 0  # core delegates to veyltrace.commands:bench
    out = tmp_path / "results" / "synth-smoke"
    first = [textio.read_text(out / name) for name in OUTPUTS]
    assert (out / "per_case.csv").is_file() and '"n_unranked":4' in first[0]  # R-00 stubs rank nothing
    assert bench_cli.main(argv) == 0  # again on the same runs root: bench empties its dir, all re-run
    assert [textio.read_text(out / name) for name in OUTPUTS] == first


def test_cli_exit_codes(tmp_path: Path) -> None:
    unsupported = tmp_path / "rcaeval.yaml"
    unsupported.write_text(textio.read_text(SMOKE).replace("kind: veyltrace", "kind: rcaeval"), "utf-8")
    out = ["--out", str(tmp_path)]
    assert bench_cli.main(["run"]) == 2  # usage
    assert bench_cli.main(["run", str(SMOKE)]) == 2  # synth without --out
    assert bench_cli.main(["run", str(SMOKE), *out]) == 3  # no answer keys fetched yet
    assert bench_cli.main(["run", str(tmp_path / "nope.yaml"), *out]) == 3
    assert bench_cli.main(["run", str(unsupported), *out]) == 4  # rcaeval baselines are R-05


def test_table_refusals_are_usage_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "results"
    for bench_dirty, reason in ((True, "dirty work tree"), (False, "synth is never reported")):
        monkeypatch.setattr(runner, "code_state", lambda _, d=bench_dirty: {"dirty": False, "bench_dirty": d})
        assert bench_cli.main(["run", str(SMOKE), "--table", "--out", str(out)]) == 2
        assert reason in capsys.readouterr().err
    assert not out.exists()  # refused before any run or write
