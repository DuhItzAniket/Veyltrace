"""The scrub test (01 §3.6): planted leaks never survive the rcaeval adapter.

A Zenodo-layout case carries its folder tokens in a log body, an operation name, a metric name and
an attribute value; deny-listed attribute keys; and rows of a fault-tool service. Every output is
then read back: (a) no folder token anywhere, (b) no deny-listed key in attrs_json, (c) no row of a
dropped service, (d) the `scrub` counts equal the planted counts, (e) scrubbing again changes nothing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa

from veyltrace_core.config import EngineConfig, data_root
from veyltrace_infralume.adapters.rcaeval import RcaevalAdapter
from veyltrace_infralume.casekey import parse_case_dir
from veyltrace_infralume.index import write_index
from veyltrace_infralume.scrub import Scrubber, ScrubRules, folder_tokens

KEY = "re2ob_cartservice_cpu_1"
REL = "rcaeval/zenodo/RE2/RE2-OB/cartservice_cpu/1"
T0 = 1_705_353_846
PLANTED_ATTRIBUTES = 3  # fault_type, chaos.experiment and feature_flag.cart on the first log line
PLANTED_ROWS = 4  # flagd: one metric point, one log line, one span; chaos-daemon: one log line


def _case() -> Path:
    case = data_root().joinpath(*REL.split("/"))
    case.mkdir(parents=True)
    (case / "simple_metrics.csv").write_bytes(
        f"time,cartservice_cpu,flagd_cpu,cartservice_{KEY}\n{T0},0.5,1,2\n".encode()
    )
    us = T0 * 1_000_000
    (case / "logs.csv").write_bytes(
        "timestamp,container_name,message,fault_type,chaos.experiment,feature_flag.cart,note\n"
        f"{T0},cartservice,open {REL}/cfg: refused,cpu,x,on,see {KEY.upper()}\n"
        f"{T0},flagd,flag cartFailure on,,,,\n"
        f"{T0},chaos-daemon,inject stress,,,,\n"
        f"{T0},frontend,fault tolerance ok,,,,\n".encode()  # "fault" in a body stays: evidence
    )
    (case / "traces.csv").write_bytes(
        "traceID,spanID,parentSpanID,serviceName,methodName,operationName,startTime,duration,statusCode\n"
        f"a1,b1,,frontend,,GET /{KEY}/x,{us},10,200\n"
        f"a1,b2,b1,flagd,,resolve,{us + 1},2,200\n".encode()
    )
    (case / "inject_time.txt").write_bytes(f"{T0}".encode())
    key = parse_case_dir(case.parts)
    assert key is not None
    write_index(data_root(), key.suite, {key.case_id: REL})
    return case


def _strings(table: pa.Table) -> Iterator[str]:
    for name in table.column_names:
        if pa.types.is_string(table.schema.field(name).type):
            yield from (v for v in table.column(name).to_pylist() if isinstance(v, str))


def _keys(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _keys(v)


def test_planted_leaks_are_scrubbed(infralume_cfg: EngineConfig) -> None:
    _case()
    adapter = RcaevalAdapter()
    out = adapter.convert(adapter.resolve("re2-ob", KEY, data_root()), infralume_cfg)
    rules = ScrubRules.from_config(infralume_cfg)
    tokens = folder_tokens(KEY, REL)
    texts = [s for _, table in out.tables.items() for s in _strings(table)]
    assert texts, "the case produced no string output"
    # (a) no folder token, in any case
    assert not [s for s in texts for t in tokens if t in s.lower()]
    assert "fault tolerance ok" in texts  # bodies are otherwise verbatim
    # (b) no deny-listed key in any attrs_json
    attrs = [json.loads(v) for v in out.tables.logs.column("attrs_json").to_pylist() if v is not None]
    assert attrs == [{"note": "see <case>"}]
    assert not [k for a in attrs for k in _keys(a) if rules.denied(k)]
    # (c) no row of a fault-tool service
    for _, table in out.tables.items():
        for column in ("service", "component", "entity"):
            if column in table.column_names:
                assert not set(table.column(column).to_pylist()) & rules.drop_services
    # (d) counts
    assert out.scrub == ("scrub-1", PLANTED_ATTRIBUTES, PLANTED_ROWS)
    # (e) scrubbing the output again changes nothing and drops nothing
    again = Scrubber(rules, tokens)
    for _, table in out.tables.items():
        assert (
            again.drop_rows(table, [c for c in ("service", "component") if c in table.column_names]) == table
        )
        assert [again.text(s) for s in _strings(table)] == list(_strings(table))
    stored = [v for v in out.tables.logs.column("attrs_json").to_pylist() if v is not None]
    assert [again.attrs_json(v) for v in stored] == stored
    assert again.counts == ("scrub-1", 0, 0)
