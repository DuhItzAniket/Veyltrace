"""The `nezha` adapter on a tiny synthetic day in Nezha's published layout (01 §3.3).

The tree mirrors what the real repository has, quirks included: a fault list whose
`inject_timestamp` is wrong, a pod metric file whose `TimeStamp` is wrong, JSON-wrapped log lines,
`root` parents, and label-bearing files the adapter must never open. Never downloaded data.
"""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_core.adapters import CanonicalCase, adapter_for
from veyltrace_core.config import EngineConfig, data_root
from veyltrace_core.errors import ConfigError, UsageError
from veyltrace_core.ids import case_id
from veyltrace_infralume.adapters import nezha_layout as layout
from veyltrace_infralume.adapters.nezha import ForbiddenFile, NezhaAdapter, _open
from veyltrace_infralume.adapters.nezha_tables import MIB, _message, raw_metrics, raw_spans

NS = 1_000_000_000
DATE = "2022-08-22"
POD = "frontend-579b9bff58-t2dbm"
#: Two faults 300 s apart: 03:53:54 and 03:58:54 UTC.
T = (
    int(datetime(2022, 8, 22, 3, 53, 54, tzinfo=UTC).timestamp()),
    int(datetime(2022, 8, 22, 3, 58, 54, tzinfo=UTC).timestamp()),
)
ADAPTER = NezhaAdapter()
KEYS = (f"nezha-ob-{DATE}-0", f"nezha-ob-{DATE}-1")


def _clock(second: int) -> str:
    return datetime.fromtimestamp(second, UTC).strftime("%Y-%m-%d %H:%M:%S")


def _csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    def cell(value: object) -> str:
        text = str(value)
        return '"' + text.replace('"', '""') + '"' if any(c in text for c in ',"\n') else text

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(header), *(",".join(cell(v) for v in row) for row in rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture
def nezha_day() -> Path:
    """One Online Boutique day with two faults, registered in the private index."""
    day = data_root().joinpath(*layout.SRC, DATE)
    faults = {
        "03": [
            # inject_timestamp is deliberately wrong (as on the real Train Ticket days): unused.
            {"inject_time": _clock(T[0]), "inject_timestamp": "1", "inject_pod": POD, "inject_type": "cpu"},
            {"inject_time": _clock(T[1]), "inject_timestamp": "1", "inject_pod": POD, "inject_type": "cpu"},
        ]
    }
    day.mkdir(parents=True)
    (day / layout.fault_list_name(DATE)).write_text(json.dumps(faults), encoding="utf-8")
    # One row a minute from 4 minutes before the first fault; TimeStamp is 2e8 s off (real quirk).
    minutes = [T[0] - 240 + 60 * i for i in range(12)]
    _csv(
        day / "metric" / f"{POD}_metric.csv",
        [
            "Time",
            "TimeStamp",
            "PodName",
            "CpuUsage(m)",
            "MemoryUsage(Mi)",
            "PodServerLatencyP90(s)",
            "NodeCpuUsageRate(%)",
        ],
        [
            [f"{_clock(s)}.607158889 +0000 UTC m=+0.1", s + 200_000_000, POD, 1.5 + i, 2, 0.25, 9]
            for i, s in enumerate(minutes)
        ],
    )
    _csv(
        day / "metric" / "front_service.csv",
        ["Time", "TimeStamp", "ServiceName"],
        [[_clock(T[0]), T[0], "Frontend"]],
    )
    inner = json.dumps({"message": "TraceID: aa SpanID: bb charge failed", "severity": "error"})
    wrapped = json.dumps({"log": inner + "\n", "stream": "stdout"})
    plain = json.dumps({"log": "16:42:22.382 WARN  t.s.Impl#5 slow call\n", "stream": "stdout"})
    for k, stem in enumerate(layout.minute_stems(T[0] * NS)):
        at = (T[0] - 30 + 60 * k) * NS
        _csv(
            day / "log" / f"{stem}_log.csv",
            ["Timestamp", "TimeUnixNano", "Node", "PodName", "Container", "TraceID", "SpanID", "Log"],
            [
                ["x", at, "10.0.0.1", POD, "server", "0a", "0b", wrapped],
                ["x", at + 1, "10.0.0.1", POD, "server", "", "", plain],
            ],
        )
        _csv(
            day / "trace" / f"{stem}_trace.csv",
            [
                "TraceID",
                "SpanID",
                "ParentID",
                "PodName",
                "OperationName",
                "StartTimeUnixNano",
                "EndTimeUnixNano",
                "Duration",
            ],
            [
                ["0a", f"0{k}", "root", POD, "op", at, at + 5_000_000, 5000],
                ["0a", f"1{k}", f"0{k}", POD, "op2", at + 10, at + 2_000_010, 2000],
            ],
        )
    assert layout.build_index(data_root()) == {"nezha-ob": 2, "nezha-tt": 0}
    return day


def _vals(table: pa.Table, name: str) -> list[Any]:
    """A column as plain Python values (pyarrow types them as optional)."""
    return cast("list[Any]", table.column(name).to_pylist())


def _convert(key: str, cfg: EngineConfig) -> CanonicalCase:
    return ADAPTER.convert(ADAPTER.resolve("nezha-ob", key, data_root()), cfg)


def test_registered_and_resolves(nezha_day: Path) -> None:
    assert isinstance(adapter_for("nezha-ob"), NezhaAdapter)
    by_key = ADAPTER.resolve("nezha-ob", KEYS[1], data_root())
    assert by_key == ADAPTER.resolve("nezha-ob", case_id(KEYS[1]), data_root())
    assert (by_key.canonical_key, by_key.location) == (KEYS[1], nezha_day / "1")
    assert ADAPTER.list_cases("nezha-ob", data_root()) == sorted(case_id(k) for k in KEYS)
    assert ADAPTER.list_cases("nezha-tt", data_root()) == []
    for dataset, case in (("nezha-tt", KEYS[0]), ("nezha-ob", "nope"), ("nezha-x", KEYS[0])):
        with pytest.raises(UsageError):
            ADAPTER.resolve(dataset, case, data_root())


def test_fault_times_come_from_inject_time_only(nezha_day: Path) -> None:
    assert layout.fault_times_ns(nezha_day) == (T[0] * NS, T[1] * NS)  # not the bogus inject_timestamp
    assert layout.day_system(nezha_day) == "ob"
    assert ADAPTER.alert_hint(ADAPTER.resolve("nezha-ob", KEYS[1], data_root())) == (T[1] * NS, "oracle")
    listing = nezha_day / layout.fault_list_name(DATE)
    listing.write_text(json.dumps({"03": [{"inject_time": _clock(T[0])}] * 2}), encoding="utf-8")
    with pytest.raises(ConfigError, match="increase strictly"):
        layout.fault_times_ns(nezha_day)


def test_allow_list_refuses_label_and_unread_files(nezha_day: Path) -> None:
    for kind, name in (
        ("metric", "front_service.csv"),
        ("metric", "dependency.csv"),
        ("traceid", "03_53_traceid.csv"),
        ("log", "../2022-08-22-fault_list.json"),
        ("trace", "root_cause_hipster.json"),
    ):
        with pytest.raises(ForbiddenFile):
            _open(nezha_day, kind, name)
    assert _open(nezha_day, "log", "00_00_log.csv") is None  # allowed name, absent file


def test_first_case_is_sliced_converted_and_scrub_free(nezha_day: Path, infralume_cfg: EngineConfig) -> None:
    out = _convert(KEYS[0], infralume_cfg)
    assert (out.system, out.adapter_name, out.adapter_version) == ("ob", "nezha", "1")
    assert out.sources_present == {"metrics": True, "logs": True, "traces": True, "events": False}
    assert (out.t_alert_hint_ns, out.hint_source) == (T[0] * NS, "oracle")
    names = [name for name, _, _ in out.inputs]
    assert names == sorted(names) and f"metrics/{POD}_metric.csv" in names
    assert not any("fault_list" in n or "front_service" in n for n in names)
    m = out.tables.metrics
    # The slice ends at the midpoint to the next fault (+150 s): minutes -240 … +120 are inside.
    assert sorted(set(_vals(m, "t_ns"))) == [(T[0] - 240 + 60 * i) * NS for i in range(7)]
    assert set(_vals(m, "service")) == {"frontend"}
    assert sorted(set(_vals(m, "name"))) == ["cpu", "latency-90", "mem"]  # no Node* column
    by_name = dict(
        zip(
            _vals(m, "name"),
            zip(_vals(m, "value"), _vals(m, "unit"), strict=True),
            strict=True,
        )
    )
    assert by_name["mem"] == (2 * MIB, "bytes") and by_name["latency-90"] == (0.25, "s")
    logs = out.tables.logs
    assert logs.num_rows == 6 and set(_vals(logs, "service")) == {"frontend"}
    assert set(_vals(logs, "component")) == {POD}
    assert sorted(set(_vals(logs, "body"))) == [
        "16:42:22.382 WARN  t.s.Impl#5 slow call",
        "TraceID: aa SpanID: bb charge failed",
    ]
    assert sorted(set(_vals(logs, "severity"))) == ["ERROR", "WARN"]
    attrs = {a and json.dumps(json.loads(a), sort_keys=True) for a in _vals(logs, "attrs_json")}
    assert attrs == {None, '{"span_id": "0b", "trace_id": "0a"}'}  # a line without ids has no attrs
    spans = out.tables.spans
    assert spans.num_rows == 6 and set(_vals(spans, "status")) == {"unset"}
    assert spans.column("parent_span_id").null_count == 3  # the three `root` spans
    assert set((e - s) for s, e in zip(_vals(spans, "start_ns"), _vals(spans, "end_ns"), strict=True)) == {
        5_000_000,
        2_000_000,
    }
    assert out.scrub == ("scrub-1", 0, 0)


def test_second_case_gets_only_its_own_rows(nezha_day: Path, infralume_cfg: EngineConfig) -> None:
    out = _convert(KEYS[1], infralume_cfg)
    lo = (T[0] + T[1]) // 2 * NS
    assert min(_vals(out.tables.metrics, "t_ns")) >= lo
    # The second fault has no minute files in this tree: absent sources are zero-row tables.
    assert out.sources_present == {"metrics": True, "logs": False, "traces": False, "events": False}
    assert out.tables.logs.num_rows == 0 and out.tables.spans.num_rows == 0


@given(st.lists(st.integers(60, 3000), min_size=1, max_size=12), st.data())
def test_slices_never_overlap_and_contain_their_fault(gaps: list[int], data: st.DataObject) -> None:
    times = tuple(sum(gaps[: i + 1]) * NS for i in range(len(gaps)))
    windows = [layout.window_ns(times, i) for i in range(len(times))]
    for (lo, hi), t in zip(windows, times, strict=True):
        assert lo < t < hi and hi - lo <= 2 * layout.HALF_SPAN_NS
    assert all(a[1] <= b[0] for a, b in itertools.pairwise(windows))
    i = data.draw(st.integers(0, len(times) - 1))
    assert layout.parse_key(layout.nezha_key("tt", DATE, i)) == ("tt", DATE, i)


def test_table_helpers() -> None:
    assert _message('{"log":"plain line\\n"}') == ("plain line", None)
    assert _message("not json at all") == ("not json at all", None)
    assert _message(None) == ("", None)
    pod = pa.table({"Time": ["garbage", f"{_clock(T[0])}.5 +0000 UTC"], "CpuUsage(m)": [1.0, 2.0]})
    wide = raw_metrics(pod, "frontend", (0, 2**62))
    assert wide.column_names == ["time", "frontend_cpu"] and _vals(wide, "frontend_cpu") == [2.0]
    assert raw_metrics(pod, "frontend", (0, 1)).num_rows == 0  # outside the window
    assert raw_spans(pa.table({"x": [1]})).num_rows == 0
    assert layout.minute_stems(T[0] * NS) == ("03_53", "03_54", "03_55")


def test_a_malformed_csv_row_is_skipped_not_fatal(nezha_day: Path, infralume_cfg: EngineConfig) -> None:
    path = nezha_day / "log" / f"{layout.minute_stems(T[0] * NS)[0]}_log.csv"
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(f"x,{T[0] * NS},10.0.0.1,{POD},server,0a,0b,spliced,extra,cells\n")  # 10 cells, not 8
    assert _convert(KEYS[0], infralume_cfg).tables.logs.num_rows == 6  # the six good lines
