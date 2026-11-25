"""The live OTLP/HTTP receiver (06 §3.3; X-10a2): JSON through the converter seam into the buffer,
retries buffered once, 400/413/415/503, partial success, and the CLI listener checks."""

from __future__ import annotations

import asyncio
import gzip
import json
import socket
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
GZ = [JSON, (b"content-encoding", b"gzip")]
RETRY_S = 7


def _call(  # POST `body`; GET when there is no body and no headers
    app: Any, path: str, body: bytes = b"", headers: list[tuple[bytes, bytes]] | None = None
) -> tuple[int, Any]:
    status, _, decoded = _send(app, path, body, headers)
    return status, decoded


def _send(  # `_call` plus the response headers
    app: Any, path: str, body: bytes = b"", headers: list[tuple[bytes, bytes]] | None = None
) -> tuple[int, dict[bytes, bytes], Any]:
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
    return sent[0]["status"], dict(sent[0]["headers"]), json.loads(raw) if raw else None


def _receiver(converter: StubConverter | None = None, **kw: Any) -> tuple[Any, LiveBuffer, ReceiverCounters]:
    buffer, counters = LiveBuffer(30, 512, 300), ReceiverCounters()
    app = create_otlp_app(
        buffer, converter or StubConverter(), {}, max_body_mb=1, retry_after_s=RETRY_S, counters=counters, **kw
    )
    return app, buffer, counters


def _spans(n: int, t: int = T0) -> bytes:
    rows = [(f"{i:032x}", f"{i:016x}", t + i, t + i + 5, False) for i in range(n)]
    return json.dumps(otlp_spans("frontend", rows)).encode()


def test_json_spans_land_in_the_buffer_and_a_retry_is_buffered_once() -> None:
    app, buffer, counters = _receiver()
    assert _call(app, "/v1/traces", _spans(3), [JSON]) == (200, {})
    assert _call(app, "/v1/traces", _spans(3), [JSON]) == (200, {})  # Collector retry: same body
    gauge = json.dumps(otlp_gauge("cart", "cpu", [(T0, 0.5), (T0 + MIN, 0.7)])).encode()
    zipped = gzip.compress(gauge)
    assert _call(app, "/v1/metrics", zipped, GZ) == (200, {})
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
        (b"\xff{}", [JSON], 400, "malformed_body"),  # not UTF-8
        (b'{"resourceSpans": [{"oops": 1}]}', [JSON], 503, "conversion_failed"),  # retried, not dropped
        (b"[" * 100_000, [JSON], 503, "conversion_failed"),  # RecursionError in json.loads
        (
            gzip.compress(b"{}")[:-4],
            GZ,
            400,
            "malformed_body",
        ),  # truncated
        (
            gzip.compress(b"{}") * 2,
            GZ,
            400,
            "malformed_body",
        ),  # multi-member
        (b"{}", [JSON, (b"content-encoding", b"deflate")], 415, "unsupported_encoding"),
        (b"x" * (1024 * 1024 + 1), [JSON], 413, "body_too_large"),
        (gzip.compress(b" " * (2 * 1024 * 1024)), GZ, 413, "body_too_large"),
        (b"not gzip", GZ, 400, "malformed_body"),
    ],
)
def test_bad_requests(body: bytes, headers: list[tuple[bytes, bytes]], status: int, code: str) -> None:
    app, buffer, counters = _receiver()
    got, error = _call(app, "/v1/traces", body, headers)
    assert (got, error["error"]["code"]) == (status, code)
    assert buffer.stats().rows["spans"] == 0
    assert (counters.accepted, counters.rejected) == (0, 1)  # 06 §3.3: every rejection is counted


def test_a_converter_failure_is_a_503_the_collector_retries() -> None:
    """Regression (#52 bug bash): it was 500, which OTLP/HTTP clients never retry, so the batch was
    lost. 503 with Retry-After is retried (OTLP/HTTP: 429/502/503/504), so the batch comes back."""
    app, buffer, counters = _receiver()
    status, headers, error = _send(app, "/v1/traces", b'{"resourceSpans": [{"oops": 1}]}', [JSON])
    assert (status, error["error"]["code"]) == (503, "conversion_failed")
    assert headers[b"retry-after"] == str(RETRY_S).encode()
    assert (buffer.stats().rows["spans"], counters.rejected) == (0, 1)
    assert _call(app, "/v1/traces", _spans(2), [JSON]) == (200, {})  # the retry that converts lands
    assert (buffer.stats().rows["spans"], counters.accepted) == (2, 1)


def test_without_a_converter_the_receiver_is_503() -> None:
    app = create_otlp_app(LiveBuffer(30, 512, 300), None, {}, max_body_mb=1, retry_after_s=RETRY_S)
    status, error = _call(app, "/v1/logs", b'{"resourceLogs": []}', [JSON])
    assert (status, error["error"]["code"]) == (503, "converter_unavailable")


def test_a_batch_the_buffer_refuses_is_a_partial_success() -> None:
    app, buffer, counters = _receiver()
    status, body = _call(app, "/v1/traces", _spans(2, 4_102_444_800 * 1_000_000_000), [JSON])  # year 2100
    assert (status, body) == (
        200,
        {"partialSuccess": {"rejectedSpans": "2", "errorMessage": "buffer: future"}},
    )
    assert buffer.stats().dropped == {"future": 1} and counters.accepted == 1


def test_health_reports_receiving_from_the_buffer() -> None:
    now = [100.0]
    buffer = LiveBuffer(30, 512, 300, clock=lambda: now[0])
    settings = replace(load_settings(CONFIG), live_enabled=True)
    app = create_app(settings, config_dir=CONFIG, live=buffer)
    otlp = create_otlp_app(buffer, StubConverter(), {}, max_body_mb=1, retry_after_s=RETRY_S)
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


def test_cli_stops_when_the_otlp_port_is_taken_or_is_the_api_port(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = load_settings(CONFIG)
    with socket.create_server(("127.0.0.1", 0)) as taken:
        port = int(taken.getsockname()[1])
        busy = replace(settings, live_enabled=True, live=replace(settings.live, otlp_port=port))
        monkeypatch.setattr(cli, "load_settings", lambda: busy)
        assert cli.main([]) == ConfigError.exit_code
    assert f"cannot listen for OTLP on 127.0.0.1:{port}" in capsys.readouterr().err
    same = replace(settings, live_enabled=True, live=replace(settings.live, otlp_port=settings.port))
    monkeypatch.setattr(cli, "load_settings", lambda: same)
    assert cli.main([]) == ConfigError.exit_code
    assert "also the API port" in capsys.readouterr().err
