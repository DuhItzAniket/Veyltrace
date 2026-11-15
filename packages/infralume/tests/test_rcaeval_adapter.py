"""The `rcaeval` adapter on tiny Hugging Face and Zenodo trees (01 §3.3)."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from veyltrace_core.adapters import CanonicalCase, adapter_for
from veyltrace_core.config import EngineConfig, data_root
from veyltrace_core.errors import CaseRejected, UsageError
from veyltrace_core.ids import case_id
from veyltrace_infralume.adapters.rcaeval import HF, ZENODO, ForbiddenFile, Layout, RcaevalAdapter, _Case
from veyltrace_infralume.casekey import parse_case_dir
from veyltrace_infralume.index import write_index

NS = 1_000_000_000
KEY = "re2ob_cartservice_cpu_1"  # the trees of conftest.py
T0 = 1_705_353_846
ADAPTER = RcaevalAdapter()


def _convert(cfg: EngineConfig) -> CanonicalCase:
    return ADAPTER.convert(ADAPTER.resolve("re2-ob", KEY, data_root()), cfg)


def test_registered_and_resolves(hf_case: Path) -> None:
    assert isinstance(adapter_for("re2-ob"), RcaevalAdapter)
    by_name = ADAPTER.resolve("re2-ob", KEY, data_root())
    assert by_name == ADAPTER.resolve("re2-ob", case_id(KEY), data_root())
    assert (by_name.location, by_name.canonical_key) == (hf_case, KEY)
    assert ADAPTER.list_cases("re2-ob", data_root()) == [case_id(KEY)]
    with pytest.raises(UsageError, match="belongs to re2-ob"):
        ADAPTER.resolve("re2-ss", KEY, data_root())
    with pytest.raises(UsageError):
        ADAPTER.resolve("re2-ob", "nope", data_root())


@pytest.mark.parametrize("layout", [HF, ZENODO])
def test_allow_list_refuses_label_files(hf_case: Path, layout: Layout) -> None:
    case = _Case(hf_case, layout)
    for name in ("cases.parquet", "root_cause.txt", "metrics.csv", "../logs.parquet"):
        with pytest.raises(ForbiddenFile):
            case.path(name)


def test_hf_case(hf_case: Path, infralume_cfg: EngineConfig) -> None:
    out = _convert(infralume_cfg)
    assert out.system == "ob" and (out.adapter_name, out.adapter_version) == ("rcaeval", "1")
    assert out.sources_present == {"metrics": True, "logs": True, "traces": True, "events": False}
    names = [name for name, _, _ in out.inputs]
    assert names == ["logs/logs.parquet", "metrics/metrics.parquet", "traces/traces.parquet"]
    assert (out.t_alert_hint_ns, out.hint_source) == ((T0 + 3) * NS, "oracle")
    assert out.tables.spans.column("service").to_pylist() == ["frontend"]  # OB alias
    assert out.tables.logs.column("body").to_pylist() == ["open /<case>/x"]
    assert out.scrub == ("scrub-1", 0, 0)


def test_zenodo_case_has_the_same_case_id(zenodo_case: Path, infralume_cfg: EngineConfig) -> None:
    ref = ADAPTER.resolve("re2-ob", KEY, data_root())
    assert (ref.location, ref.case_id) == (zenodo_case, case_id(KEY))
    out = ADAPTER.convert(ref, infralume_cfg)
    spans = out.tables.spans.select(["trace_id", "span_id", "status"]).to_pylist()
    assert spans == [{"trace_id": "0012", "span_id": "0034", "status": "error"}]  # IDs keep leading zeros
    assert out.tables.logs.column("severity").to_pylist() == ["WARN"]
    names = [name for name, _, _ in out.inputs]
    assert names == ["logs/logs.csv", "metrics/simple_metrics.csv", "traces/traces.csv"]


def test_absent_and_header_only_sources(hf_case: Path, infralume_cfg: EngineConfig) -> None:
    (hf_case / "traces.parquet").unlink()
    empty = {"timestamp": pa.array([], pa.int64()), "container_name": pa.array([], pa.string())}
    pq.write_table(pa.table(empty), hf_case / "logs.parquet")
    out = _convert(infralume_cfg)
    assert out.sources_present == {"metrics": True, "logs": False, "traces": False, "events": False}
    assert [name for name, _, _ in out.inputs] == ["metrics/metrics.parquet"]


def test_rejections(hf_case: Path, infralume_cfg: EngineConfig) -> None:
    (hf_case / "inject_time.txt").write_bytes(b"soon")
    with pytest.raises(CaseRejected, match="no_hint"):
        _convert(infralume_cfg)
    for name in ("metrics.parquet", "logs.parquet", "traces.parquet"):
        (hf_case / name).unlink()
    with pytest.raises(CaseRejected, match="unsupported_format"):
        _convert(infralume_cfg)


def test_zenodo_re1_repeated_time_header(infralume_cfg: EngineConfig) -> None:
    """pyarrow keeps a repeated `time` header (pandas reads it as `time.1`); 01 §3.3 drops it."""
    case = data_root().joinpath("rcaeval", "zenodo", "RE1", "RE1-OB", "cartservice_cpu", "1")
    case.mkdir(parents=True)
    (case / "data.csv").write_bytes(b"time,cartservice_cpu,time\n1705353846,0.5,1705353846\n")
    key = parse_case_dir(case.parts)
    assert key is not None
    write_index(data_root(), key.suite, {key.case_id: "rcaeval/zenodo/RE1/RE1-OB/cartservice_cpu/1"})
    out = ADAPTER.convert(ADAPTER.resolve("re1-ob", key.key, data_root()), infralume_cfg)
    assert out.tables.metrics.select(["service", "name", "value"]).to_pylist() == [
        {"service": "cartservice", "name": "cpu", "value": 0.5}
    ]
