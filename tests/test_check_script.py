"""Unit tests for the pure parts of scripts/check.py (flags, fragments, determinism comparison).

Why: check.py gates every PR, so its own decisions (what counts as a valid fragment, which file is
the first determinism difference, which flag combinations are usage errors) need tests too. The
heavy paths (ruff, pyright, pytest, pipeline runs) are exercised by running the script itself.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check.py"
MODULE_NAME = "veyltrace_check_script"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE_NAME, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


check = _load()

STEPS = [
    ["infralume", ["case_manifest.json", "telemetry/metrics.parquet"], []],
    ["alert", ["alert.json"], []],
    ["signalyth", ["signal_cube/series.parquet"], []],
    ["relentra", ["proposals.json", "agent_trace.jsonl"], ["cassette/"]],
    ["manifest", ["config.lock.json"], []],
    ["causivra.receipt", ["receipt.json"], ["receipt.json.minisig"]],
]


@pytest.mark.parametrize(
    ("name", "text", "ok"),
    [
        ("5.feat.md", "Core now ships scripts/check.py.\n", True),
        ("12.fix.md", "Fixed Anomara onsets shifting by one step (e.g. with gaps).\n", True),
        ("5.feat.md", "Two sentences. Not allowed.\n", False),
        ("5.feat.md", "No terminator\n", False),
        ("5.feat.md", "\n", False),
        ("5.feat.md", "Para one.\n\nPara two.\n", False),
        ("5.feature.md", "Unknown type.\n", False),
        ("x.feat.md", "No issue number.\n", False),
    ],
)
def test_fragment_rules(name: str, text: str, ok: bool) -> None:
    assert (check.fragment_problems(name, text) == []) is ok


def test_step_table_maps_files_to_steps() -> None:
    files = ["alert.json", "cassette/abc.json", "run_manifest.json", "receipt.json", "stray.txt"]
    table = check._step_table(STEPS, files)
    assert table["alert.json"] == (1, "alert")
    assert table["cassette/abc.json"] == (3, "relentra")
    assert table["run_manifest.json"] == (4, "manifest")
    assert table["receipt.json"] == (5, "causivra.receipt")
    assert "stray.txt" not in table


def _arm(label: str, files: dict[str, str]) -> object:
    return check.Arm(label, "ok", None, "r", Path(label), files, check._step_table(STEPS, files))


def test_compare_arms_reports_in_pipeline_order() -> None:
    a = _arm("a", {"receipt.json": "1" * 64, "signal_cube/series.parquet": "2" * 64, "alert.json": "3" * 64})
    b = _arm("b", {"receipt.json": "9" * 64, "signal_cube/series.parquet": "8" * 64, "alert.json": "3" * 64})
    diffs = check.compare_arms(a, b)
    assert [d.split(" ")[0] for d in diffs] == ["signal_cube/series.parquet", "receipt.json"]
    assert "step signalyth" in diffs[0]


def test_compare_arms_only_and_missing_files() -> None:
    a = _arm("a", {"proposals.json": "1" * 64, "cassette/x.json": "2" * 64, "alert.json": "3" * 64})
    b = _arm("b", {"proposals.json": "1" * 64, "alert.json": "4" * 64})
    diffs = check.compare_arms(a, b, only=["proposals.json", "cassette/"])
    assert diffs == ["cassette/x.json (step relentra): only in a"]


def test_run_files_skips_signature_and_spill(tmp_path: Path) -> None:
    (tmp_path / "receipt.json").write_bytes(b"{}\n")
    (tmp_path / "receipt.json.minisig").write_bytes(b"sig")
    (tmp_path / ".duck-tmp").mkdir()
    (tmp_path / ".duck-tmp" / "spill.tmp").write_bytes(b"x")
    (tmp_path / "telemetry").mkdir()
    (tmp_path / "telemetry" / "logs.parquet").write_bytes(b"p")
    assert sorted(check.run_files(tmp_path)) == ["receipt.json", "telemetry/logs.parquet"]


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--cascade"],
        ["--base", "origin/main"],
        ["--require-synth"],
        ["--ai-fake", "--lint"],
        ["--update-golden"],
        ["--package", "lab", "--update-golden"],
        ["--package", "nope"],
    ],
)
def test_usage_errors_exit_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        check.parse_args(argv)
    assert exc.value.code == check.EXIT_USAGE


def test_valid_flag_combinations() -> None:
    args = check.parse_args(["--determinism", "--require-synth", "--require-real-case"])
    assert args.determinism and args.require_synth and args.require_real_case
    args = check.parse_args(["--update-golden", "--cascade"])
    assert args.cascade and args.package is None
    assert check.parse_args(["--changelog", "--base", "HEAD~1"]).base == "HEAD~1"


def test_child_env_pins_threads_without_overriding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMP_NUM_THREADS", "4")
    monkeypatch.delenv("MKL_NUM_THREADS", raising=False)
    env = check.child_env({"PYTHONHASHSEED": "1"})
    assert env["OMP_NUM_THREADS"] == "4"  # setdefault: an explicit choice wins
    assert env["MKL_NUM_THREADS"] == "1"
    assert env["PYTHONHASHSEED"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_cascade_follows_pipeline_order() -> None:
    from veyltrace_core.steps import STEP_NAMES, step

    steps = [s for _, names in check.CASCADE for s in names]
    assert steps == list(STEP_NAMES)  # every sub-step once, receipt after the manifest
    for package, names in check.CASCADE:
        assert all((step(n).engine or "core") == package for n in names), (package, names)
