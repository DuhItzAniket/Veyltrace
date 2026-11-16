"""Baseline methods in the runner (R-05, #15; 04 §4): `simplerca` and `rcaeval:<m>` read Infralume's
tables and alert.json from an alert-step run, and are scored on their ranks alone. The RCAEval venv
is replaced by this interpreter and a fake main.py that records what it was given."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

import pyarrow as pa
import pytest

from veyltrace_bench import rcaeval, runner
from veyltrace_bench.experiment import load_experiment, unsupported
from veyltrace_core import cli, io, textio
from veyltrace_core.errors import ConfigError

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / "bench" / "experiments" / "synth-baselines.yaml"
OFF = '  - {id: "veyltrace:off", kind: veyltrace, ai: {mode: "off"}, overrides: {}}\n'
FAKE_MAIN = (Path(__file__).parent / "fake_rcaeval_main.py").read_text(encoding="utf-8")


def _ranks(row: dict[str, object]) -> list[str]:
    ranks = row["ranks"]
    assert isinstance(ranks, list)
    return [str(r) for r in cast("list[object]", ranks)]


def _rows(out: Path) -> list[dict[str, object]]:
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    return table.to_pylist()


@pytest.fixture
def fake_rcaeval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """RCAEval's source = a fake main.py; its python = this interpreter; the commit check skipped."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "main.py").write_text(FAKE_MAIN, encoding="utf-8")
    real = rcaeval.settings()
    monkeypatch.setattr(
        rcaeval, "settings", lambda repo=None: real.model_copy(update={"source": str(source)})
    )
    monkeypatch.setattr(rcaeval, "python_path", lambda cfg, repo: Path(sys.executable))
    monkeypatch.setattr(rcaeval, "check_environment", lambda cfg, repo: None)
    return source


@pytest.mark.usefixtures("fake_rcaeval")
def test_baselines_run_on_synth_next_to_veyltrace(tmp_path: Path) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    exp = load_experiment(EXPERIMENT)
    assert unsupported(exp) == []
    out, summary = runner.run_experiment(
        EXPERIMENT, out_root=tmp_path / "results", runs_root=tmp_path / "runs"
    )
    rows = _rows(out)
    methods = {str(r["method"]) for r in rows}
    assert methods == {"veyltrace:off", "simplerca", "rcaeval:baro", "rcaeval:nsigma"}
    for row in rows:
        assert row["run_outcome"] == "ok", row
        if row["method"] != "veyltrace:off":  # ranks only: no verifier or slate channels
            assert row["status"] is None and row["retrieval_hit"] is None and row["in_set"] is None
            assert row["ranks"] and row["wall_ms"] is not None
    simple = [r for r in rows if r["method"] == "simplerca"]
    assert all("_" not in str(s) for r in simple for s in _ranks(r))  # services only
    baro = [r for r in rows if r["method"] == "rcaeval:baro"]
    assert all("_" in s for r in baro for s in _ranks(r))  # RCAEval's {component}_{metric}
    report = textio.read_text(out / "rcaeval" / "synth.rcaeval-baro.txt")  # stored next to ours (04 §4)
    argv = json.loads(report.splitlines()[0].removeprefix("argv "))
    assert argv[:2] == ["--method", "baro"] and "--report-chance" in argv and "--report-decomposition" in argv
    assert "Avg speed: 5" in report  # all five synth cases exported, synth-05 under its no-fault label
    manifest = json.loads(textio.read_text(out / "manifest.json"))
    hashes = {c["method"]: c["config_sha256"] for c in manifest["configs"]}
    assert len(set(hashes.values())) == 3  # nsigma and baro share the rcaeval section; simplerca, off differ
    groups = cast("list[dict[str, object]]", summary["groups"])
    assert {g["method"] for g in groups} == methods


def test_chance_and_unbuilt_baselines_are_named_not_run(tmp_path: Path) -> None:
    text = textio.read_text(EXPERIMENT)
    extra = '  - {id: "chance", kind: internal_baseline}\n  - {id: "prior-only", kind: internal_baseline}\n'
    path = tmp_path / "exp.yaml"
    path.write_text(text.replace(OFF, OFF + extra), encoding="utf-8")
    todo = unsupported(load_experiment(path))
    assert any("chance" in t and "`chance` metric" in t for t in todo)
    assert any(t.startswith("methods prior-only: internal baseline not built") for t in todo)


def test_an_unwrapped_rcaeval_method_is_refused_before_the_first_case(
    tmp_path: Path, fake_rcaeval: Path
) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    path = tmp_path / "exp.yaml"
    path.write_text(
        textio.read_text(EXPERIMENT).replace("method: nsigma", "method: mmbaro"), encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="'mmbaro' is not in"):
        runner.run_experiment(path, out_root=tmp_path / "r", runs_root=tmp_path / "runs")
    assert not (tmp_path / "runs").exists()
