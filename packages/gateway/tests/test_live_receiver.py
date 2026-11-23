"""The live OTLP/HTTP receiver and buffer (06 §3.3, §3.4; X-10a): JSON through the converter seam
into the buffer, retries buffered once, 413/415/400/503, retention and the byte cap. In-process
ASGI calls: no socket, no HTTP client."""

from __future__ import annotations

import asyncio
import gzip
import json
from dataclasses import replace
from typing import Any

import pytest

from veyltrace_core.errors import ConfigError
from veyltrace_core.testing import repo_root
from veyltrace_gateway import __main__ as cli
from veyltrace_gateway.app import create_app
from veyltrace_gateway.buffer import LiveBuffer
from veyltrace_gateway.otlp import ReceiverCounters, create_otlp_app
from veyltrace_gateway.settings import load_settings
from veyltrace_gateway.testing import StubConverter, otlp_gauge, otlp_spans

CONFIG = repo_root() / "config"
T0 = 1_700_000_000_000_000_000
MIN = 60_000_000_000
JSON = (b"content-type", b"application/json")


def _call(
    app: Any, path: str, body: bytes = b"", headers: list[tuple[bytes, bytes]] | None = None
) -> tuple[int, Any]:
    """POST `body` (GET when it is empty and no headers are given) through the ASGI interface."""
    method = "GET" if not body and headers is None else "POST"
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": headers or [], "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 4319),
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


def _receiver(converter: StubConverter | None = None, **kw: Any) -> tuple[Any, LiveBuffer, ReceiverCounters]:
    buffer, counters = LiveBuffer(30, 512), ReceiverCounters()
    app = create_otlp_app(buffer, converter or StubConverter(), {}, max_body_mb=1, counters=counters, **kw)
    return app, buffer, counters


def _spans(n: int, t: int = T0) -> bytes:
    return json.dumps(
        otlp_spans("frontend", [(f"{i:032x}", f"{i:016x}", t + i, t + i + 5, False) for i in range(n)])
    ).encode()


def test_json_spans_land_in_the_buffer_and_a_retry_is_buffered_once() -> None:
    app, buffer, counters = _receiver()
    assert _call(app, "/v1/traces", _spans(3), [JSON]) == (200, {})
    assert _call(app, "/v1/traces", _spans(3), [JSON]) == (200, {})  # Collector retry: same body
    gauge = json.dumps(otlp_gauge("cart", "cpu", [(T0, 0.5), (T0 + MIN, 0.7)])).encode()
    zipped = gzip.compress(gauge)
    assert _call(app, "/v1/metrics", zipped, [JSON, (b"content-encoding", b"gzip")]) == (200, {})
    stats = buffer.stats()
    assert stats.rows == {"metrics": 2, "logs": 0, "spans": 3, "events": 0}
    assert (stats.oldest_ns, stats.newest_ns) == (T0, T0 + MIN)
    assert (counters.accepted, counters.duplicate, counters.rejected) == (2, 1, 0)
    assert counters.scrub == {"dropped_attributes": 0}


@pytest.mark.parametrize(
    ("body", "headers", "status", "code"),
    [
        (b"{}", [(b"content-type", b"application/x-protobuf")], 415, "unsupported_media_type"),
        (b"{not json", [JSON], 400, "malformed_body"),
        (b"[]", [JSON], 400, "malformed_body"),
        (b'{"resourceSpans": [{"oops": 1}]}', [JSON], 400, "malformed_body"),
        (b"x" * (1024 * 1024 + 1), [JSON], 413, "body_too_large"),
        (
            gzip.compress(b" " * (2 * 1024 * 1024)),
            [JSON, (b"content-encoding", b"gzip")],
            413,
            "body_too_large",
        ),
        (b"not gzip", [JSON, (b"content-encoding", b"gzip")], 400, "malformed_body"),
    ],
)
def test_bad_requests(body: bytes, headers: list[tuple[bytes, bytes]], status: int, code: str) -> None:
    app, buffer, counters = _receiver()
    got, error = _call(app, "/v1/traces", body, headers)
    assert (got, error["error"]["code"]) == (status, code)
    assert buffer.stats().rows["spans"] == 0
    assert (counters.accepted, counters.rejected) == (0, 1)  # 06 §3.3: every rejection is counted


def test_without_a_converter_the_receiver_is_503() -> None:
    buffer = LiveBuffer(30, 512)
    app = create_otlp_app(buffer, None, {}, max_body_mb=1)
    status, error = _call(app, "/v1/logs", b'{"resourceLogs": []}', [JSON])
    assert (status, error["error"]["code"]) == (503, "converter_unavailable")


def test_health_reports_receiving_from_the_buffer() -> None:
    now = [100.0]
    buffer = LiveBuffer(30, 512, clock=lambda: now[0])
    settings = replace(load_settings(CONFIG), live_enabled=True)
    app = create_app(settings, config_dir=CONFIG, live=buffer)
    otlp = create_otlp_app(buffer, StubConverter(), {}, max_body_mb=1)
    assert _call(app, "/api/v1/health")[1]["live"] == {"enabled": True, "receiving": False}
    assert _call(otlp, "/v1/traces", _spans(1), [JSON])[0] == 200
    assert _call(app, "/api/v1/health")[1]["live"]["receiving"]
    now[0] += settings.live.receiving_s + 1  # the Collector went quiet
    assert not _call(app, "/api/v1/health")[1]["live"]["receiving"]


def test_cli_refuses_a_lan_otlp_listener_without_the_flag(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = load_settings(CONFIG)
    lan = replace(settings, live_enabled=True, live=replace(settings.live, otlp_host="0.0.0.0"))
    monkeypatch.setattr(cli, "load_settings", lambda: lan)
    assert cli.main([]) == ConfigError.exit_code
    assert "--allow-lan" in capsys.readouterr().err
