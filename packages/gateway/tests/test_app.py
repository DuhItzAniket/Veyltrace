"""The X-00 gateway: health envelope, settings validation and the loopback bind rule (06 §3.2, §3.6).

Requests go through the ASGI interface in-process (no socket, no HTTP client), so the tests need
no network.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from veyltrace_core.config import load_section_file
from veyltrace_core.errors import ConfigError
from veyltrace_core.testing import repo_root
from veyltrace_gateway import __main__ as cli
from veyltrace_gateway.app import create_app
from veyltrace_gateway.settings import check_bind, is_loopback, load_settings, settings_from

CONFIG = repo_root() / "config"


async def _asgi_get(
    app: Any, path: str, headers: list[tuple[bytes, bytes]] | None = None
) -> tuple[int, dict[bytes, bytes], bytes]:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), body


def _get(
    path: str, headers: list[tuple[bytes, bytes]] | None = None
) -> tuple[int, dict[bytes, bytes], bytes]:
    return asyncio.run(_asgi_get(create_app(config_dir=CONFIG), path, headers))


def test_health_envelope() -> None:
    status, _, body = _get("/api/v1/health")
    assert status == 200
    health = json.loads(body)
    assert set(health) == {"status", "version", "code_commit", "ai", "live"}
    assert health["status"] == "ok" and health["version"] == "0.1.0"
    llm = load_section_file("llm", config_dir=CONFIG)  # so a model change in config needs no test edit
    assert health["ai"] == {
        "default_mode": "off",
        "provider": llm["provider"],
        "model": llm["model"]["name"],
        "reachable": None,
    }
    assert health["live"] == {"enabled": False, "receiving": False}
    assert health["code_commit"]


def test_unknown_route_is_404() -> None:
    assert _get("/api/v1/nothing")[0] == 404


def test_cors_allows_only_the_configured_origin() -> None:
    allowed = _get("/api/v1/health", [(b"origin", b"http://127.0.0.1:5173")])[1]
    assert allowed.get(b"access-control-allow-origin") == b"http://127.0.0.1:5173"
    other = _get("/api/v1/health", [(b"origin", b"http://evil.example")])[1]
    assert b"access-control-allow-origin" not in other


def test_default_settings_bind_loopback() -> None:
    settings = load_settings(CONFIG)
    assert (settings.host, settings.port) == ("127.0.0.1", 8000)
    check_bind(settings.host, allow_lan=False)


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("127.0.0.1", True),
        ("127.1.2.3", True),
        ("::1", True),
        ("[::1]", True),
        ("localhost", True),
        ("0.0.0.0", False),
        ("192.168.1.5", False),
        ("gateway.lan", False),
    ],
)
def test_loopback_rule(host: str, loopback: bool) -> None:
    assert is_loopback(host) is loopback
    if not loopback:
        with pytest.raises(ConfigError):
            check_bind(host, allow_lan=False)
        check_bind(host, allow_lan=True)


def test_cli_refuses_lan_bind_without_flag(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo_root())
    assert cli.main(["--host", "0.0.0.0"]) == ConfigError.exit_code
    assert "--allow-lan" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("dotted", "value"),
    [
        ("api.port", 0),
        ("api.port", "8000"),
        ("api.host", ""),
        ("api.cors_origins", "x"),
        ("jobs.default_ai_mode", "on"),
        ("live.enabled", "no"),
    ],
)
def test_bad_settings_are_config_errors(dotted: str, value: object) -> None:
    body: dict[str, Any] = {
        "api": {"host": "127.0.0.1", "port": 8000, "cors_origins": []},
        "jobs": {"default_ai_mode": "off"},
        "live": {"enabled": False},
    }
    section, key = dotted.split(".")
    body[section][key] = value
    with pytest.raises(ConfigError):
        settings_from(body)


def test_missing_key_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match=r"live\.enabled"):
        settings_from(
            {"api": {"host": "127.0.0.1", "port": 1, "cors_origins": []}, "jobs": {"default_ai_mode": "off"}}
        )
