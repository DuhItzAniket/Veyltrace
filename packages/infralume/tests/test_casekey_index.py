"""Canonical case keys and the private case index (01 §2, §3.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from veyltrace_core.errors import ConfigError, UsageError
from veyltrace_core.ids import case_id
from veyltrace_infralume.casekey import SUITES, parse_case_dir, parse_suite
from veyltrace_infralume.index import index_path, read_index, resolve_entry, write_index


def test_hf_and_zenodo_paths_give_one_case_id() -> None:
    hf = parse_case_dir(["rcaeval", "hf", "re2ob_checkoutservice_cpu_1"])
    zen = parse_case_dir(["data", "RE2", "RE2-OB", "checkoutservice_cpu", "1"])
    assert hf is not None and zen is not None
    assert hf == zen
    assert hf.key == "re2ob_checkoutservice_cpu_1"
    assert hf.suite == "re2-ob"
    assert hf.case_id == case_id("re2ob_checkoutservice_cpu_1")


def test_hyphenated_services_and_the_zenodo_relabel() -> None:
    tt = parse_case_dir(["re2tt_ts-order-service_delay_3"])
    assert tt is not None and (tt.service, tt.fault, tt.rep) == ("ts-order-service", "delay", "3")
    relabelled = parse_case_dir(["RE3", "RE3-TT", "ts-route-service_f6", "2"])
    assert relabelled is not None and relabelled.key == "re3tt_ts-route-service_f3_2"


@pytest.mark.parametrize(
    "parts", [[], ["cases.parquet"], ["re4ob_x_cpu_1"], ["re2ob_cpu_1"], ["RE2-OB", "x"]]
)
def test_non_case_paths_are_not_keys(parts: list[str]) -> None:
    assert parse_case_dir(parts) is None


def test_suites() -> None:
    assert len(SUITES) == 9
    assert parse_suite("re3-tt") == ("re3", "tt")
    with pytest.raises(UsageError):
        parse_suite("re2-xx")


def test_index_round_trip_merges_and_is_canonical(tmp_path: Path) -> None:
    a, b = case_id("re2ob_a_cpu_1"), case_id("re2ob_b_cpu_1")
    write_index(tmp_path, "re2-ob", {b: "rcaeval/hf/re2ob_b_cpu_1"})
    write_index(tmp_path, "re2-ob", {a: "rcaeval/hf/re2ob_a_cpu_1"})
    assert read_index(tmp_path, "re2-ob") == {a: "rcaeval/hf/re2ob_a_cpu_1", b: "rcaeval/hf/re2ob_b_cpu_1"}
    assert index_path(tmp_path, "re2-ob").read_bytes().startswith(b'{"')
    assert resolve_entry(tmp_path, "re2-ob", a) == tmp_path / "rcaeval" / "hf" / "re2ob_a_cpu_1"
    with pytest.raises(UsageError, match="not in the re2-ob index"):
        resolve_entry(tmp_path, "re2-ob", "0" * 12)
    assert read_index(tmp_path, "re2-ss") == {}


@pytest.mark.parametrize("bad", ["../outside", "/abs/path", "a\\b", ""])
def test_index_rejects_paths_outside_the_data_root(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ConfigError):
        write_index(tmp_path, "re2-ob", {case_id("x"): bad})
