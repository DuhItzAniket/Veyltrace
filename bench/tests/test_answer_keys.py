"""Tests of bench answer keys (03 §13.1): synth through core's fetcher, RCAEval from fake trees built
in tmp_path from the documented layouts (01 §3.2, §3.3; rcaeval_facts): names and inject_time.txt only."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from veyltrace_bench import answer_keys as ak
from veyltrace_core import cli, io
from veyltrace_core.errors import ArtifactMissing, ConfigError, ContractValidationError, UsageError
from veyltrace_core.ids import case_id
from veyltrace_core.synth.truth import answer_key_rows

T_INJECT_S = 1_736_000_000  # any 10-digit Unix time in seconds (a priori)
OB_CASES = ("re2ob_checkoutservice_cpu_1", "re2ob_frontendservice_delay_2", "re2ob_redis-db_socket_3")
_TOKEN = st.from_regex(r"[a-z0-9][a-z0-9-]{0,12}", fullmatch=True)


def _case(root: Path, *parts: str, inject: str = f"{T_INJECT_S}\n") -> Path:
    case_dir = root.joinpath(*parts)
    case_dir.mkdir(parents=True)
    (case_dir / ak.INJECT_TIME_FILE).write_text(inject, encoding="utf-8", newline="\n")
    return case_dir


def _hf_tree(root: Path, names: tuple[str, ...] = OB_CASES) -> Path:
    for name in (*names, "re2ss_carts_cpu_1"):  # another suite side by side, as on Hugging Face
        _case(root, name)
    return root


def test_synth_keys_come_from_the_core_fetcher_via_the_cli() -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0  # VEYLTRACE_DATA: per-test root (conftest)
    keys = ak.load_answer_keys("synth")
    expected = answer_key_rows()
    assert list(keys) == [row["case_id"] for row in expected]
    assert [row.model_dump() for row in keys.values()] == expected
    assert keys[case_id("synth-01")].root_service == "checkout"
    assert keys[case_id("synth-05")].is_no_fault


def test_load_rejects_missing_misnamed_and_foreign_keys(tmp_path: Path) -> None:
    with pytest.raises(ArtifactMissing):
        ak.load_answer_keys("synth", tmp_path)
    with pytest.raises(UsageError):
        ak.answer_key_path("../synth", tmp_path)
    io.write_path("answer_key", answer_key_rows(), ak.answer_key_path("re2-ob", tmp_path))
    with pytest.raises(ContractValidationError, match="has dataset 'synth'"):
        ak.load_answer_keys("re2-ob", tmp_path)


def test_rcaeval_rows_from_a_hugging_face_tree(tmp_path: Path) -> None:
    rows = {row.case_id: row for row in ak.rcaeval_answer_key_rows("re2-ob", _hf_tree(tmp_path))}
    assert list(rows) == sorted(case_id(name) for name in OB_CASES)
    cpu, delay, sock = (rows[case_id(name)] for name in OB_CASES)
    truth = [
        (r.root_service, r.root_component, r.fault_class, r.mode, r.indicator) for r in (cpu, delay, sock)
    ]
    assert truth == [
        ("checkoutservice", None, "cpu", "resource", "cpu"),
        ("frontend", None, "delay", "network", "latency"),  # OB alias (01 §4 normalise.aliases)
        ("redis", "redis-db", "socket", "resource", "socket"),  # -db folds (01 §3.4 step 5)
    ]
    assert (cpu.dataset, cpu.system, cpu.fault_label, cpu.is_no_fault) == ("re2-ob", "ob", "cpu", False)
    assert (cpu.t_inject_ns, cpu.t_end_ns, cpu.injection_json) == (T_INJECT_S * ak.NS_PER_S, None, None)


def test_build_then_load_round_trips_with_identical_bytes(tmp_path: Path) -> None:
    _hf_tree(tmp_path / "a")
    _hf_tree(tmp_path / "b", OB_CASES[::-1])
    path, digest = ak.build_rcaeval_answer_keys("re2-ob", tmp_path / "a", tmp_path / "data-a")
    assert path == tmp_path / "data-a" / "answer_keys" / "re2-ob.parquet"
    assert ak.build_rcaeval_answer_keys("re2-ob", tmp_path / "b", tmp_path / "data-b")[1] == digest
    loaded = ak.load_answer_keys("re2-ob", tmp_path / "data-a")
    assert list(loaded.values()) == ak.rcaeval_answer_key_rows("re2-ob", tmp_path / "a")


def test_zenodo_paths_give_the_hugging_face_case_ids(tmp_path: Path) -> None:
    data = tmp_path / "data"
    _case(data, "RE2", "RE2-OB", "checkoutservice_cpu", "1")
    _case(data, "RE3", "RE3-TT", "ts-route-service_f6", "2")  # really F3 (rcaeval_facts "Data quirks")
    (ob,) = ak.rcaeval_answer_key_rows("re2-ob", data)
    assert ob.case_id == case_id("re2ob_checkoutservice_cpu_1")
    (tt,) = ak.rcaeval_answer_key_rows("re3-tt", data)
    assert tt.case_id == case_id("re3tt_ts-route-service_f3_2")
    assert (tt.fault_label, tt.fault_class, tt.mode, tt.indicator) == ("f3", None, "code", None)


@pytest.mark.parametrize(
    ("suite", "fault", "expected"),
    [
        ("re1-ss", "disk", ("disk", "resource", "latency")),  # RE1 has no disk metric (04 §7)
        ("re2-ss", "disk", ("disk", "resource", "diskio")),
        ("re2-tt", "mem", ("mem", "resource", "mem")),
        ("re2-tt", "loss", ("loss", "network", "latency")),  # RCAEval scores loss as latency
        ("re3-ob", "f5", (None, "code", None)),
    ],
)
def test_fault_labels_map_to_the_contract_vocabularies(
    tmp_path: Path, suite: str, fault: str, expected: tuple[str | None, str, str | None]
) -> None:
    _case(tmp_path, f"{suite.replace('-', '')}_svc_{fault}_1")
    (row,) = ak.rcaeval_answer_key_rows(suite, tmp_path)
    assert (row.fault_class, row.mode, row.indicator) == expected


@pytest.mark.parametrize(
    ("suite", "parts", "inject", "match"),
    [
        ("re1-ob", ("re1ob_svc_socket_1",), "1\n", "not an RE1 fault"),
        ("re2-ob", ("re2ob_svc_f1_1",), "1\n", "not an RE2 fault"),
        ("re2-ob", ("re2ob_svc_oom_1",), "1\n", "not an RE2 fault"),
        ("re2-ob", ("re2ob_svc_cpu_1",), "", "integer Unix time"),
        ("re2-ob", ("re2ob_svc_cpu_1",), "1.7e9\n", "integer Unix time"),
        ("re2-ob", ("RE2-OB", "nolabel", "1"), "1\n", "not an RCAEval case directory"),
        ("re2-ob", ("re2ob_bad!name_cpu_1",), "1\n", "root_service"),
    ],
)
def test_layout_errors_name_the_problem(
    tmp_path: Path, suite: str, parts: tuple[str, ...], inject: str, match: str
) -> None:
    _case(tmp_path, *parts, inject=inject)
    with pytest.raises(ak.LayoutError, match=match):
        ak.rcaeval_answer_key_rows(suite, tmp_path)


def test_duplicate_empty_and_unknown_suites_are_refused(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        ak.rcaeval_answer_key_rows("re4-ob", tmp_path)
    with pytest.raises(ak.LayoutError, match="no re2-ob case"):
        ak.rcaeval_answer_key_rows("re2-ob", tmp_path)
    _case(tmp_path, "hf", "re2ob_checkoutservice_cpu_1")
    _case(tmp_path, "zenodo", "RE2-OB", "checkoutservice_cpu", "1")
    with pytest.raises(ak.LayoutError, match="appears twice"):
        ak.rcaeval_answer_key_rows("re2-ob", tmp_path)


def test_write_refuses_foreign_rows_and_a_work_tree(tmp_path: Path) -> None:
    rows = ak.rcaeval_answer_key_rows("re2-ob", _hf_tree(tmp_path / "src"))
    with pytest.raises(ContractValidationError, match="re2-ob"):
        ak.write_answer_keys("re2-ss", rows, tmp_path / "data")
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(ConfigError, match="git work tree"):
        ak.write_answer_keys("re2-ob", rows, tmp_path / "repo" / "data")


@given(
    release=st.sampled_from(sorted(ak.RELEASE_FAULTS)),
    system=st.sampled_from(["ob", "ss", "tt"]),
    service=_TOKEN,
    fault=_TOKEN,
    rep=st.integers(min_value=1, max_value=99),
)
def test_hugging_face_and_zenodo_parts_parse_to_one_key(
    release: str, system: str, service: str, fault: str, rep: int
) -> None:
    key = ak.CaseKey(release, system, service, fault, str(rep))
    assume((key.suite, service, fault) not in ak.ZENODO_RELABEL)
    assert ak.parse_case_dir([key.key]) == key
    zenodo = [release.upper(), key.suite.upper(), f"{service}_{fault}".upper(), str(rep)]
    assert ak.parse_case_dir(zenodo) == key
    assert ak.parse_case_dir(["mirror", *zenodo]).key == key.key
