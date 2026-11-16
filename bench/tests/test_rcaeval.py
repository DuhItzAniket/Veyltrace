"""The RCAEval wrapper (R-05, #15; 04 §4): the export in RCAEval's layout, main.py in its own
interpreter with output/ deleted first, and the refusals before any case. The RCAEval venv is
replaced by this interpreter and a fake main.py that records what it was given."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from veyltrace_bench import rcaeval
from veyltrace_contracts.models import AnswerKeyRow
from veyltrace_core import cli, textio
from veyltrace_core.errors import ConfigError, VeyltraceError
from veyltrace_core.pipeline import run_case

FAKE_MAIN = (Path(__file__).parent / "fake_rcaeval_main.py").read_text(encoding="utf-8")


def _key(case: str, **fields: object) -> AnswerKeyRow:
    base: dict[str, object] = {name: None for name in AnswerKeyRow.model_fields}
    base |= {"case_id": case, "dataset": "synth", "system": "other", "is_no_fault": False}
    return AnswerKeyRow.model_validate(base | fields)


def _fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, main: str = FAKE_MAIN) -> rcaeval.Settings:
    source = tmp_path / "src"
    source.mkdir(exist_ok=True)
    (source / "main.py").write_text(main, encoding="utf-8")
    monkeypatch.setattr(rcaeval, "python_path", lambda cfg, repo: Path(sys.executable))
    return rcaeval.settings().model_copy(update={"source": str(source)})


def test_export_is_rcaeval_wide_csv_with_t_alert(tmp_path: Path) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    s = run_case("synth", "synth-01", "off", runs_root=tmp_path / "runs", to_step="alert")
    rcaeval.export_case(s.run_dir, tmp_path / "case")
    lines = textio.read_text(tmp_path / "case" / rcaeval.METRICS_FILE).splitlines()
    header, first = lines[0].split(","), lines[1].split(",")
    assert header[0] == "time" and header[1:] == sorted(header[1:]) and len(first) == len(header)
    assert all("_" in c for c in header[1:])  # {component}_{name}, as RCAEval's columns
    alert = json.loads(textio.read_text(s.run_dir / "alert.json"))
    inject = int(textio.read_text(tmp_path / "case" / rcaeval.INJECT_FILE))
    assert inject == alert["t_alert_ns"] // rcaeval.NS


def test_case_dir_is_main_pys_label_layout(tmp_path: Path) -> None:
    mapping = rcaeval.DatasetMap(id="re2-ob", path="data/RE2/RE2-OB")
    fault = _key("0123456789ab", root_service="cart", fault_label="cpu")
    calm = _key("ba9876543210", is_no_fault=True)
    assert rcaeval.case_dir(tmp_path, mapping, fault) == tmp_path / "data/RE2/RE2-OB/cart_cpu/0123456789ab"
    assert rcaeval.case_dir(tmp_path, mapping, calm).parent.name == rcaeval.NO_FAULT_LABEL


def test_main_runs_with_report_flags_after_deleting_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _fake(tmp_path, monkeypatch)
    mapping = rcaeval.DatasetMap(id="re2-ob", path="data/RE2/RE2-OB")
    work = tmp_path / "work"
    for case, cols in (("0123456789ab", "time,b_cpu,a_mem"), ("ba9876543210", "time,c_cpu")):
        dest = rcaeval.case_dir(work, mapping, _key(case, root_service="a", fault_label="mem"))
        dest.mkdir(parents=True)
        (dest / rcaeval.METRICS_FILE).write_text(cols + "\n1,0,0\n", encoding="utf-8")
        (dest / rcaeval.INJECT_FILE).write_text("1\n", encoding="utf-8")
    (work / "output" / "results").mkdir(parents=True)
    (work / "output" / "results" / "x_y_ffffffffffff.json").write_text("{}", encoding="utf-8")  # stale
    args = rcaeval.MethodArgs(method="baro", length=20)
    got = rcaeval.run_main(
        cfg, tmp_path, work, mapping, args, ["0123456789ab", "ba9876543210", "000000000000"], 60
    )
    assert got.ranks == {"0123456789ab": ("a_mem", "b_cpu"), "ba9876543210": ("c_cpu",), "000000000000": None}
    argv = json.loads(got.report.splitlines()[0].removeprefix("argv "))
    flags = ["--report-chance", "--report-decomposition", str(cfg.report_decomposition)]
    assert argv == ["--method", "baro", "--dataset", "re2-ob", "--length", "20", *flags]
    assert not got.timed_out and got.wall_ms > 0


def test_a_failing_main_stops_the_experiment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _fake(tmp_path, monkeypatch, main="import sys; sys.exit('boom')")
    mapping, args = rcaeval.DatasetMap(id="re2-ob", path="d"), rcaeval.MethodArgs(method="baro")
    (tmp_path / "work").mkdir()
    with pytest.raises(VeyltraceError, match="boom"):
        rcaeval.run_main(cfg, tmp_path, tmp_path / "work", mapping, args, ["0123456789ab"], 60)


def test_only_wrapped_methods_and_a_ready_venv_are_accepted(tmp_path: Path) -> None:
    cfg = rcaeval.settings()
    assert rcaeval.method_args({"method": "baro"}, cfg, "rcaeval:baro").length == 20  # main.py default
    with pytest.raises(ConfigError, match="'mmbaro' is not in"):
        rcaeval.method_args({"method": "mmbaro"}, cfg, "rcaeval:mmbaro")  # needs logts, not exported
    with pytest.raises(ConfigError, match="rcaeval block"):
        rcaeval.method_args({"method": "baro", "window": 3}, cfg, "rcaeval:baro")
    missing = cfg.model_copy(update={"venv": "nowhere", "source": "nowhere/src"})
    with pytest.raises(ConfigError, match=r"scripts/rcaeval/setup\.py"):
        rcaeval.check_environment(missing, tmp_path)
