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
import yaml

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
    extra = (
        '  - {id: "chance", kind: internal_baseline}\n  - {id: "prior-only", kind: internal_baseline}\n'
        '  - {id: "prism-plain", kind: internal_baseline}\n'
    )
    path = tmp_path / "exp.yaml"
    path.write_text(text.replace(OFF, OFF + extra), encoding="utf-8")
    todo = unsupported(load_experiment(path))
    assert any("chance" in t and "`chance` metric" in t for t in todo)
    assert not any(t.startswith("methods prior-only") for t in todo)  # built (#561); split checked at run
    assert any(t.startswith("methods prism-plain: internal baseline not built") for t in todo)


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


def test_every_rcaeval_experiment_has_a_dataset_entry_for_each_part() -> None:
    # re3/nezha rq1 were refused at R-16 because baselines.yaml mapped only RE2 (#615)
    datasets = rcaeval.settings().datasets
    not_run = cast(
        "dict[str, object]", yaml.safe_load(textio.read_text(ROOT / "bench" / "results" / "not_run.yaml"))
    )
    for path in sorted((ROOT / "bench" / "experiments").glob("*.yaml")):
        exp = load_experiment(path)
        if exp.experiment_id in not_run:  # cut from v1.0 (not_run.yaml): never run, so never refused
            continue
        if any(m.kind == "rcaeval" for m in exp.methods):
            missing = [d for d in exp.dataset.parts if d not in datasets]
            assert not missing, f"{path.name}: rcaeval.datasets has no entry for {missing}"


#: RCAEval's DATASET_MAP (RCAEval/benchmark/datasets.py at the pinned commit 90b63a46) for the ids
#: bench passes. main.py reads only DATASET_MAP[id] and downloads the public data there if missing.
RCAEVAL_DATASET_MAP = {
    "re2-ob": "data/RE2/RE2-OB",
    "re2-ss": "data/RE2/RE2-SS",
    "re2-tt": "data/RE2/RE2-TT",
    "re3-ob": "data/RE3/RE3-OB",
    "re3-ss": "data/RE3/RE3-SS",
    "re3-tt": "data/RE3/RE3-TT",
}


def test_every_rcaeval_dataset_entry_exports_where_main_py_reads() -> None:
    # nezha rq1 scored downloaded RE2 cases at R-16: its paths were data/Nezha/... (#627)
    for name, mapping in sorted(rcaeval.settings().datasets.items()):
        assert mapping.id in RCAEVAL_DATASET_MAP, f"{name}: {mapping.id} is not a mirrored RCAEval id"
        assert mapping.path == RCAEVAL_DATASET_MAP[mapping.id], (
            f"{name}: main.py reads {RCAEVAL_DATASET_MAP[mapping.id]}"
        )
