"""The live snapshot writer (06 §3.4; X-10b1): the window, content-addressed ids and file bytes,
repeated rows collapsed, key conflicts refused, and the index entry."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pytest

from veyltrace_core.errors import ContractValidationError
from veyltrace_core.ids import case_id
from veyltrace_core.io import read_path
from veyltrace_gateway.buffer import LiveBuffer
from veyltrace_gateway.snapshot import write_snapshot
from veyltrace_gateway.testing import StubConverter, otlp_gauge, otlp_spans

T = 1_700_000_000_000_000_000
MIN = 60_000_000_000


def _spans(*starts: int) -> pa.Table:
    rows = [(f"{s:032x}", f"{s:016x}", s, s + 5, False) for s in starts]
    return StubConverter().spans(otlp_spans("frontend", rows), {})[0]


def _gauge(*points: tuple[int, float]) -> pa.Table:
    return StubConverter().metrics(otlp_gauge("cart", "cpu", points), {})[0]


def test_the_window_and_the_id_depend_only_on_rows_and_trigger(tmp_path: Path) -> None:
    a, b = LiveBuffer(30, 512, 300), LiveBuffer(30, 512, 300)
    a.add("spans", _spans(T - 25 * MIN, T - MIN), "s1")  # 25 min before: outside a 20-min window
    a.add("spans", _spans(T + 1), "s2")  # after the trigger: outside
    a.add("metrics", _gauge((T - MIN, 0.5)), "m1")
    a.add("metrics", _gauge((T - MIN, 0.5)), "m2")  # the same point in a second request
    b.add("metrics", _gauge((T - MIN, 0.5)), "x")  # another arrival order, same rows
    b.add("spans", _spans(T - MIN), "y")
    b.add("spans", _spans(T + 1), "z")  # so both triggers are T: newest data is after the click
    snap = write_snapshot(a, tmp_path / "a", T, 20, "manual")
    again = write_snapshot(b, tmp_path / "b", T, 20, "manual")
    assert snap is not None and again is not None and snap.snapshot_id == again.snapshot_id
    assert snap.rows == {"metrics": 1, "logs": 0, "spans": 1, "events": 0}
    assert snap.case_id == case_id(snap.snapshot_id)
    folder = tmp_path / "a" / "live" / snap.snapshot_id
    assert sorted(p.name for p in folder.iterdir()) == [
        "events.parquet", "logs.parquet", "metrics.parquet", "snapshot.json", "spans.parquet",
    ]  # fmt: skip
    assert json.loads((folder / "snapshot.json").read_bytes()) == {
        "snapshot_id": snap.snapshot_id, "t_trigger_ns": T, "trigger": "manual",
    }  # fmt: skip
    for source in ("a", "b"):
        assert (tmp_path / source / "live" / snap.snapshot_id / "spans.parquet").read_bytes() == (
            folder / "spans.parquet"
        ).read_bytes()
    assert read_path("telemetry.spans", folder / "spans.parquet").num_rows == 1  # pyright: ignore[reportAttributeAccessIssue]
    index = json.loads((tmp_path / "a" / "index" / "live.json").read_bytes())
    assert index == {snap.case_id: f"live/{snap.snapshot_id}"}
    other = write_snapshot(a, tmp_path / "a", T + 1, 20, "manual")  # a later click: a new id
    assert other is not None and other.snapshot_id != snap.snapshot_id
    assert len(json.loads((tmp_path / "a" / "index" / "live.json").read_bytes())) == 2


def test_an_empty_window_is_none_and_a_key_conflict_is_refused(tmp_path: Path) -> None:
    buffer = LiveBuffer(30, 512, 300)
    assert write_snapshot(buffer, tmp_path, T, 20, "manual") is None
    buffer.add("metrics", _gauge((T - MIN, 0.5)), "m1")
    buffer.add("metrics", _gauge((T - MIN, 0.9)), "m2")  # same key, another value
    with pytest.raises(ContractValidationError, match="duplicate key"):
        write_snapshot(buffer, tmp_path, T, 20, "manual")


def test_the_trigger_is_capped_at_the_newest_data_so_the_hint_is_inside_the_span(tmp_path: Path) -> None:
    buffer = LiveBuffer(30, 512, 300)
    buffer.add("spans", _spans(T - 5 * MIN, T - 3_000_000_000), "late")  # newest row 3 s before the click
    snap = write_snapshot(buffer, tmp_path, T, 20, "manual")
    assert snap is not None and snap.t_trigger_ns == T - 3_000_000_000 and snap.rows["spans"] == 2
    again = write_snapshot(buffer, tmp_path, T + 60_000_000_000, 20, "manual")  # a second click, no new data
    assert again is not None and again.snapshot_id == snap.snapshot_id
    meta = json.loads((tmp_path / "live" / snap.snapshot_id / "snapshot.json").read_bytes())
    assert meta["t_trigger_ns"] == T - 3_000_000_000  # data_start_ns <= hint <= data_end_ns (core alert)
