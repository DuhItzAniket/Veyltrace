"""The CLI wires Infralume's OTLP converter into the receiver at start-up (06 §3.3; G2, #504).

`veyltrace_infralume.otlp` (O-07, #24) may be absent, so these tests replace it in `sys.modules`:
a fake module with the #24 signatures (the stub converter's functions), `None` (not installed),
or a module missing a function. `uvicorn.Server` and `uvicorn.run` are replaced too, so the CLI
starts up but serves nothing; the apps it built are driven through ASGI.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import socket
import sys
import types
from dataclasses import replace
from typing import Any, ClassVar

import pytest
import uvicorn

from veyltrace_core.errors import ConfigError
from veyltrace_core.log import NAMESPACE
from veyltrace_core.testing import repo_root
from veyltrace_gateway import __main__ as cli
from veyltrace_gateway.settings import load_settings
from veyltrace_gateway.testing import StubConverter, otlp_spans

CONFIG = repo_root() / "config"
T0 = 1_700_000_000_000_000_000
JSON = [(b"content-type", b"application/json")]
SPANS = json.dumps(otlp_spans("frontend", [("a" * 32, "b" * 16, T0, T0 + 5, False)])).encode()


def _call(app: Any, path: str, body: bytes = b"") -> tuple[int, Any]:
    """POST `body` (JSON) to the ASGI `app`, or GET without one; return status and JSON body."""
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "scheme": "http",
        "method": "POST" if body else "GET", "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "headers": JSON if body else [], "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }  # fmt: skip
    sent: list[dict[str, Any]] = []
    chunks = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive() -> dict[str, Any]:
        return chunks.pop() if chunks else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    raw = b"".join(m.get("body", b"") for m in sent[1:])
    return sent[0]["status"], json.loads(raw) if raw else None


class _Server:
    """Stands in for uvicorn.Server: keeps the receiver app, closes its socket, serves nothing."""

    apps: ClassVar[list[Any]] = []

    def __init__(self, config: uvicorn.Config) -> None:
        _Server.apps.append(config.app)

    def run(self, sockets: list[socket.socket]) -> None:
        for sock in sockets:
            sock.close()


def _fake_module(*, without: str | None = None) -> types.ModuleType:
    """A `veyltrace_infralume.otlp` with the #24 functions `spans`, `metrics` and `logs`."""
    module = types.ModuleType(cli.CONVERTER_MODULE)
    stub = StubConverter()
    for name in ("spans", "metrics", "logs"):
        if name != without:
            setattr(module, name, getattr(stub, name))
    return module


def _start(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    """Run `python -m veyltrace_gateway` with live on; return the receiver app and the API app."""
    settings = load_settings(CONFIG)
    with socket.create_server(("127.0.0.1", 0)) as probe:  # a free port for the OTLP listener
        port = int(probe.getsockname()[1])
    live = replace(settings, live_enabled=True, live=replace(settings.live, otlp_port=port))
    monkeypatch.setattr(cli, "load_settings", lambda: live)
    api: list[Any] = []

    def run(app: Any, **_: Any) -> None:
        api.append(app)

    _Server.apps.clear()
    monkeypatch.setattr(uvicorn, "Server", _Server)
    monkeypatch.setattr(uvicorn, "run", run)
    assert cli.main([]) == 0
    return _Server.apps[0], api[0]


def test_start_up_passes_the_infralume_converter_to_the_receiver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, cli.CONVERTER_MODULE, _fake_module())
    receiver, api = _start(monkeypatch)
    assert _call(receiver, "/v1/traces", SPANS) == (200, {})
    status, body = _call(api, "/api/v1/live/status")  # the runbook's G2 check (06a B.1 step 8)
    assert status == 200
    assert body["requests"] == {"accepted": 1, "duplicate": 0, "rejected": 0}
    assert body["rows"]["spans"] == 1


def test_without_the_converter_start_up_logs_it_and_the_receiver_is_503(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(sys.modules, cli.CONVERTER_MODULE, None)  # the import fails: not installed
    with caplog.at_level(logging.WARNING, logger=NAMESPACE):
        receiver, api = _start(monkeypatch)
    assert [r.getMessage() for r in caplog.records] == ["otlp_converter_missing"]
    status, error = _call(receiver, "/v1/traces", SPANS)
    assert (status, error["error"]["code"]) == (503, "converter_unavailable")
    status, error = _call(api, "/api/v1/live/snapshot", b"{}")  # nothing is written
    assert (status, error["error"]["code"]) == (503, "converter_missing")


def test_a_converter_module_without_the_seam_stops_start_up(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, cli.CONVERTER_MODULE, _fake_module(without="logs"))
    settings = load_settings(CONFIG)
    monkeypatch.setattr(cli, "load_settings", lambda: replace(settings, live_enabled=True))
    assert cli.main([]) == ConfigError.exit_code  # before any socket is bound
    assert "has no logs(request, settings)" in capsys.readouterr().err


def test_a_missing_dependency_inside_the_converter_is_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(name: str, package: str | None = None) -> types.ModuleType:
        raise ModuleNotFoundError("No module named 'ijson'", name="ijson")

    monkeypatch.setattr(importlib, "import_module", broken)  # restored before pytest imports again
    with pytest.raises(ModuleNotFoundError, match="ijson"):
        cli.load_converter()
