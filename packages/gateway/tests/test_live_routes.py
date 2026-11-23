"""`/api/v1/live/*` (06 §3.4; X-10b2): route errors and the `live.ai_modes` rule. The happy path,
OTLP to queued runs, is tests/integration/test_explain_live.py."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from veyltrace_core.config import load_section_file
from veyltrace_core.errors import ConfigError
from veyltrace_core.testing import FIXTURE_CODE_COMMIT, repo_root
from veyltrace_gateway.buffer import LiveBuffer
from veyltrace_gateway.errors import add_error_handlers
from veyltrace_gateway.jobs import JobRunner
from veyltrace_gateway.live import live_router
from veyltrace_gateway.settings import load_settings, settings_from

CONFIG = repo_root() / "config"
T = 1_700_000_000_000_000_000


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
    body = json.loads(json.dumps(load_section_file("gateway", config_dir=CONFIG), default=dict))
    body["live"]["ai_modes"] = modes
    with pytest.raises(ConfigError, match=r"live\.ai_modes"):
        settings_from(body)
