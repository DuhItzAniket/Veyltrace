"""veyltrace_core.synth.truth and the synth fetcher: answer keys (03 §13.1) and the NO_FAULT window.

The answer keys must match what the generator injected (same layout values), be valid `answer_key`
rows, and land only under the data root (never under packages/ or a run directory).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from veyltrace_core import io
from veyltrace_core.config import data_root
from veyltrace_core.fetch import FetchRequest
from veyltrace_core.hashing import sha256_file
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.synth import layout as lay
from veyltrace_core.synth.fetch import fetch
from veyltrace_core.synth.truth import answer_key_path, answer_key_rows, answer_key_table, normal_windows

T_INJECT = lay.T_INJECT_NS


def _by_case() -> dict[str, dict[str, object]]:
    return {str(r["case_id"]): r for r in answer_key_rows()}


def test_rows_are_valid_answer_keys() -> None:
    io.encode("answer_key", answer_key_table())  # schema, enums, patterns, unique case_id
    ids = [r["case_id"] for r in answer_key_rows()]
    assert ids == sorted(ids)
    assert len(answer_key_rows(include_variants=False)) == 5
    assert {r["dataset"] for r in answer_key_rows()} == {"synth"}
    assert {r["system"] for r in answer_key_rows()} == {"other"}


@pytest.mark.parametrize(
    ("case", "root", "fault_class", "indicator", "mode"),
    [
        ("synth-01", "checkout", "cpu", "cpu", "resource"),
        ("synth-02", "recommend", "delay", "latency", "network"),
        ("synth-03", "payment", "exception", "error", "code"),
        ("synth-04", "catalog", "mem", "mem", "change"),
    ],
)
def test_fault_cases(case: str, root: str, fault_class: str, indicator: str, mode: str) -> None:
    row = _by_case()[make_case_id(case)]
    assert row["is_no_fault"] is False
    assert (row["root_service"], row["root_component"]) == (root, None)
    assert (row["fault_class"], row["indicator"], row["mode"]) == (fault_class, indicator, mode)
    assert (row["t_inject_ns"], row["t_end_ns"]) == (T_INJECT, lay.DATA_END_NS)
    injection = json.loads(str(row["injection_json"]))
    assert injection["tool"] == "synth" and injection["tool_version"] == lay.ADAPTER_VERSION
    assert injection["params"] == dict(lay.CASES[case].fault.params)
    assert injection["fault_id"] == row["fault_label"] == lay.CASES[case].fault.fault_id
    assert injection["seed"] == make_case_id(case)


def test_decoys() -> None:
    rows = _by_case()
    synth03 = json.loads(str(rows[make_case_id("synth-03")]["decoy_changes_json"]))
    assert synth03 == [
        {"entity": "cart-1", "is_true": False, "kind": "deploy", "t_ns": T_INJECT - 240 * lay.NS}
    ]
    synth04 = json.loads(str(rows[make_case_id("synth-04")]["decoy_changes_json"]))
    assert synth04 == [
        {"entity": "catalog", "is_true": True, "kind": "deploy", "t_ns": T_INJECT - 60 * lay.NS}
    ]
    for case in ("synth-01", "synth-02", "synth-05"):
        assert rows[make_case_id(case)]["decoy_changes_json"] is None


def test_no_fault_and_silent_variant() -> None:
    rows = _by_case()
    nofault = rows[make_case_id("synth-05")]
    assert nofault["is_no_fault"] is True
    assert all(
        nofault[k] is None
        for k in (
            "root_service",
            "fault_class",
            "indicator",
            "mode",
            "t_inject_ns",
            "t_end_ns",
            "injection_json",
        )
    )
    silent = rows[make_case_id("synth-05@silent")]
    assert silent["is_no_fault"] is False
    assert (silent["root_service"], silent["root_component"], silent["fault_class"]) == (
        "cart",
        "cart-1",
        None,  # telemetry loss, not a pod failure: no fault class is scored
    )
    assert (silent["fault_label"], silent["indicator"], silent["mode"]) == ("replica-silence", None, None)
    assert silent["t_inject_ns"] == T_INJECT


def test_normal_windows() -> None:
    (window,) = normal_windows()
    assert (window.case, window.case_id, window.dataset) == ("synth-05", make_case_id("synth-05"), "synth")
    assert (window.protocol, window.shift_s, window.variant, window.reportable) == ("oracle", 0, "", False)
    assert dict(window.overrides) == {}


def test_fetch_writes_answer_keys_under_the_data_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert fetch(FetchRequest(name="synth", data_root=tmp_path)) == 0
    path = answer_key_path(tmp_path)
    assert path == tmp_path / "answer_keys" / "synth.parquet"
    table = io.read_path("answer_key", path, validate=True)
    assert table.to_pylist() == answer_key_rows()  # pyright: ignore[reportAttributeAccessIssue]
    first = sha256_file(path)
    assert fetch(FetchRequest(name="synth", data_root=tmp_path)) == 0
    assert sha256_file(path) == first  # deterministic bytes
    assert "answer-key rows" in capsys.readouterr().out
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == [
        "answer_keys/synth.parquet"
    ]


def test_fetch_rejects_other_suites_and_sources(tmp_path: Path) -> None:
    assert fetch(FetchRequest(name="synth", data_root=tmp_path, suite="re2-ss")) == 2
    assert fetch(FetchRequest(name="synth", data_root=tmp_path, source="hf")) == 2
    assert not answer_key_path(tmp_path).exists()


def test_cli_data_fetch_synth() -> None:
    from veyltrace_core import cli

    assert cli.main(["data", "fetch", "synth"]) == 0
    assert answer_key_path(data_root()).is_file()  # conftest points VEYLTRACE_DATA at a tmp dir
