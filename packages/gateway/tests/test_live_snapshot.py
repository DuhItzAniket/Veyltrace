"""The live snapshot and `/api/v1/live/*` (06 §3.4; X-10b): the window, content-addressed ids,
retries collapsed, the index entry, and the route errors."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from fastapi import FastAPI

from veyltrace_core.errors import ConfigError, ContractValidationError
from veyltrace_core.ids import case_id
from veyltrace_core.io import read_path
from veyltrace_core.testing import FIXTURE_CODE_COMMIT, repo_root
from veyltrace_gateway.buffer import LiveBuffer
from veyltrace_gateway.errors import add_error_handlers
from veyltrace_gateway.jobs import JobRunner
from veyltrace_gateway.live import live_router
from veyltrace_gateway.settings import load_settings, settings_from
from veyltrace_gateway.snapshot import write_snapshot
from veyltrace_gateway.testing import StubConverter, otlp_gauge, otlp_spans

CONFIG = repo_root() / "config"
T = 1_700_000_000_000_000_000
MIN = 60_000_000_000


def _spans(*starts: int) -> pa.Table:
    rows = [(f"{s:032x}", f"{s:016x}", s, s + 5, False) for s in starts]
    return StubConverter().spans(otlp_spans("frontend", rows), {})[0]


def _gauge(*points: tuple[int, float]) -> pa.Table:
    return StubConverter().metrics(otlp_gauge("cart", "cpu", points), {})[0]


def test_the_window_and_the_id_depend_only_on_rows_and_trigger(tmp_path: Path) -> None:
    a, b = LiveBuffer(30, 512), LiveBuffer(30, 512)
    a.add("spans", _spans(T - 25 * MIN, T - MIN), "s1")  # 25 min before: outside a 20-min window
    a.add("spans", _spans(T + 1), "s2")  # after the trigger: outside
    a.add("metrics", _gauge((T - MIN, 0.5)), "m1")
    a.add("metrics", _gauge((T - MIN, 0.5)), "m2")  # the same point in a second request
    b.add("metrics", _gauge((T - MIN, 0.5)), "x")  # another arrival order, same rows
    b.add("spans", _spans(T - MIN), "y")
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
    buffer = LiveBuffer(30, 512)
    assert write_snapshot(buffer, tmp_path, T, 20, "manual") is None
    buffer.add("metrics", _gauge((T - MIN, 0.5)), "m1")
    buffer.add("metrics", _gauge((T - MIN, 0.9)), "m2")  # same key, another value
    with pytest.raises(ContractValidationError, match="duplicate key"):
        write_snapshot(buffer, tmp_path, T, 20, "manual")


def _post(app: Any, path: str, body: object | None = None) -> tuple[int, Any]:
    raw = b"" if body is None else json.dumps(body).encode()
    method = "GET" if path.endswith("status") else "POST"
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": [(b"content-type", b"application/json")] if raw else [],
        "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000),
    }  # fmt: skip
    sent: list[dict[str, Any]] = []
    chunks = [{"type": "http.request", "body": raw, "more_body": False}]

    async def receive() -> dict[str, Any]:
        return chunks.pop() if chunks else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent[0]["status"], json.loads(b"".join(m.get("body", b"") for m in sent[1:]))


def _app(buffer: LiveBuffer | None, tmp_path: Path) -> FastAPI:
    app = FastAPI()
    add_error_handlers(app)
    runner = JobRunner(tmp_path / "runs", commit=FIXTURE_CODE_COMMIT, config_dir=CONFIG)
    app.include_router(live_router(load_settings(CONFIG), buffer, None, tmp_path / "runs", runner, lambda: T))
    return app


def test_route_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEYLTRACE_DATA", str(tmp_path / "data"))
    assert _post(_app(None, tmp_path), "/live/status")[1]["error"]["code"] == "live_disabled"
    app = _app(LiveBuffer(30, 512), tmp_path)
    assert _post(app, "/live/diagnose") == (
        409,
        {"error": {"code": "buffer_empty", "message": "no live data in the last 20 min"}},
    )
    assert _post(app, "/live/snapshot", {"before_min": 31})[0] == 422  # more than the buffer holds
    assert _post(app, "/live/snapshot", {"before_min": 0})[0] == 422
    status, body = _post(app, "/live/status")
    assert status == 200 and body["rows"]["spans"] == 0 and body["snapshots"] == []


@pytest.mark.parametrize("modes", [[], ["record"], ["off", "replay"], ["off", "off"], "off"])
def test_live_ai_modes_must_start_with_off(modes: object) -> None:
    from veyltrace_core.config import load_section_file

    body = json.loads(json.dumps(load_section_file("gateway", config_dir=CONFIG), default=dict))
    body["live"]["ai_modes"] = modes
    with pytest.raises(ConfigError, match=r"live\.ai_modes"):
        settings_from(body)
