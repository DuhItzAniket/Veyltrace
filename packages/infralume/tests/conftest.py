"""Tiny synthetic RCAEval case trees (Hugging Face, Zenodo) for the adapter's own behaviour; row
rules are tested on in-memory tables. Never downloaded data. Constants are mirrored in the tests
(importlib mode: conftest is not importable)."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from veyltrace_core.config import EngineConfig, data_root, resolve_config
from veyltrace_infralume.casekey import parse_case_dir
from veyltrace_infralume.index import write_index

KEY = "re2ob_cartservice_cpu_1"
T0 = 1_705_353_846  # seconds, as the Hugging Face mirror stores metric and log times


@pytest.fixture
def infralume_cfg() -> EngineConfig:
    """Infralume's config section from the work tree's config/ (no overrides)."""
    return resolve_config({}, ai_mode="off").engine("infralume")


def _register(case_dir: Path) -> Path:
    key = parse_case_dir(case_dir.parts)
    assert key is not None
    write_index(data_root(), key.suite, {key.case_id: case_dir.relative_to(data_root()).as_posix()})
    (case_dir / "inject_time.txt").write_bytes(f"{T0 + 3}\n".encode())
    return case_dir


@pytest.fixture
def hf_case() -> Path:
    """An RE2-OB case in the Hugging Face layout, next to a label file the adapter must not open."""
    case = data_root() / "rcaeval" / "hf" / KEY
    case.mkdir(parents=True)
    pq.write_table(pa.table({"time": [T0, T0 + 1], "cartservice_mem": [1.0, 2.0]}), case / "metrics.parquet")
    logs = {"timestamp": [T0], "container_name": ["cartservice"], "message": [f"open /{KEY}/x"]}
    pq.write_table(pa.table(logs), case / "logs.parquet")
    spans = {
        "traceID": ["t1"], "spanID": ["0a"], "parentSpanID": [None], "serviceName": ["frontendservice"],
        "methodName": [None], "operationName": ["frontend"], "startTimeMillis": [T0 * 1000],
        "startTime": [T0 * 1_000_000], "duration": [1000], "statusCode": [0],
    }  # fmt: skip
    pq.write_table(pa.table(spans), case / "traces.parquet")
    (case / "root_cause.txt").write_bytes(b"cartservice")
    return _register(case)


@pytest.fixture
def zenodo_case() -> Path:
    """The same case in the Zenodo CSV layout: IDs with leading zeros, RE2 log columns."""
    case = data_root().joinpath("rcaeval", "zenodo", "RE2", "RE2-OB", "cartservice_cpu", "1")
    case.mkdir(parents=True)
    (case / "simple_metrics.csv").write_bytes(f"time,cartservice_cpu\n{T0},0.5\n".encode())
    (case / "logs.csv").write_bytes(
        f"timestamp,container_name,message,level,pod_name\n{T0 * 10**9},cartservice,hi,warning,\n".encode()
    )
    (case / "traces.csv").write_bytes(
        "traceID,spanID,parentSpanID,serviceName,methodName,operationName,startTime,duration,statusCode\n"
        f"0012,0034,,cartservice,GetCart,op,{T0 * 1_000_000},7,503.0\n".encode()
    )
    return _register(case)
