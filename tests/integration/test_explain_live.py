"""X-10 live path end to end (06 §9 "OTLP round trip"), up to the snapshot and the queued runs.

OTLP/JSON → receiver → converter seam (the stub until O-07, #24) → buffer → "Diagnose now" →
snapshot files under `${VEYLTRACE_DATA}/live/<snapshot_id>/` → the `live.ai_modes` runs queued
with `dataset = live`, AI off first. The runs finish only once Infralume's `otlp_live` adapter is
installed. Until then this test checks they fail at the adapter, so it tightens itself when the
adapter lands. Protobuf requests built with `opentelemetry-proto` follow once that dependency is in.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from veyltrace_core import io
from veyltrace_core.adapters import find_adapter
from veyltrace_core.ids import case_id
from veyltrace_core.testing import FIXTURE_CODE_COMMIT, repo_root
from veyltrace_gateway import live as live_routes
from veyltrace_gateway.app import create_app
from veyltrace_gateway.buffer import LiveBuffer
from veyltrace_gateway.jobs import JobRunner
from veyltrace_gateway.otlp import ReceiverCounters, create_otlp_app
from veyltrace_gateway.settings import load_settings
from veyltrace_gateway.testing import StubConverter, otlp_gauge, otlp_spans

CONFIG = repo_root() / "config"
SEC = 1_000_000_000
WAIT_S = 300  # a failing run ends in seconds; the bound only stops a hung test


def _call(app: Any, method: str, path: str, body: bytes = b"") -> tuple[int, Any]:
    headers = [(b"content-type", b"application/json")] if body else []
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "", "headers": headers,
        "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000),
    }  # fmt: skip
    sent: list[dict[str, Any]] = []
    chunks = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive() -> dict[str, Any]:
        return chunks.pop() if chunks else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent[0]["status"], json.loads(b"".join(m.get("body", b"") for m in sent[1:]))


def test_otlp_json_to_snapshot_and_queued_live_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "data"
    monkeypatch.setenv("VEYLTRACE_DATA", str(data))
    loaded = load_settings(CONFIG)
    settings = replace(loaded, live=replace(loaded.live, ai_modes=("off",)))  # no model in CI
    buffer = LiveBuffer(
        settings.live.buffer_minutes, settings.live.buffer_max_mb, settings.live.future_tolerance_s
    )
    counters = ReceiverCounters()
    otlp = create_otlp_app(
        buffer, StubConverter(), {}, max_body_mb=settings.live.max_body_mb, counters=counters
    )
    runner = JobRunner(tmp_path / "runs", commit=FIXTURE_CODE_COMMIT, config_dir=CONFIG)
    api = create_app(
        settings, config_dir=CONFIG, runs=tmp_path / "runs", jobs=runner, live=buffer, counters=counters
    )

    now = time.time_ns()  # live data is "now": Diagnose now cuts the last 20 min of wall time
    spans = [
        (f"{i:032x}", f"{i:016x}", now - (600 - i) * SEC, now - (600 - i) * SEC + 5_000_000, i > 540)
        for i in range(600)
    ]
    gauge = [(now - (600 - 10 * i) * SEC, 0.1 * i) for i in range(60)]
    for path, request in (
        ("/v1/traces", otlp_spans("frontend", spans)),
        ("/v1/metrics", otlp_gauge("cart", "cpu", gauge)),
    ):
        assert _call(otlp, "POST", path, json.dumps(request).encode()) == (200, {})

    if find_adapter("live") is None:  # O-07 (#24) not installed yet: say so, then stand in for it
        assert _call(api, "POST", "/api/v1/live/diagnose", b"{}")[1]["error"]["code"] == "adapter_missing"
        monkeypatch.setattr(live_routes, "find_adapter", lambda dataset: object())
    status, first = _call(api, "POST", "/api/v1/live/diagnose", b"{}")
    assert status == 202 and (first["dataset"], first["ai_mode"]) == ("live", "off")
    again = _call(api, "POST", "/api/v1/live/diagnose", b"{}")[1]  # a double click: same snapshot, same run
    assert again["run_id"] == first["run_id"]
    _, live = _call(api, "GET", "/api/v1/live/status")
    (sid,) = live["snapshots"]
    assert first["case_id"] == case_id(sid) and live["run_ids"][0] == first["run_id"]
    assert len(live["run_ids"]) == len(settings.live.ai_modes)
    assert live["requests"] == {"accepted": 2, "duplicate": 0, "rejected": 0}

    folder = data / "live" / sid
    meta = json.loads((folder / "snapshot.json").read_bytes())
    assert meta["snapshot_id"] == sid and meta["trigger"] == "manual"
    assert meta["t_trigger_ns"] == now - SEC  # the newest span start, 1 s before the click
    tables = {
        s: io.read_path(f"telemetry.{s}", folder / f"{s}.parquet")
        for s in ("metrics", "logs", "spans", "events")
    }
    assert {s: t.num_rows for s, t in tables.items()} == {"metrics": 60, "logs": 0, "spans": 600, "events": 0}  # pyright: ignore[reportAttributeAccessIssue]
    assert json.loads((data / "index" / "live.json").read_bytes()) == {case_id(sid): f"live/{sid}"}

    for rid in live["run_ids"]:
        job = runner.get(rid)
        assert job is not None and job.finished.wait(WAIT_S)
        assert job.overrides == {"core.alert.protocol": "live"}  # alert.json says protocol live
        if find_adapter("live") is None:  # O-07 (#24) not installed yet
            assert job.state == "failed" and "adapter" in (job.error or ""), job.error
        elif job.ai_mode == "off":
            assert job.state == "done", job.error
