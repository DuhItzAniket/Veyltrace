"""HTTP transport and the Ollama provider, with fake transports and connections: no network (#136)."""

from __future__ import annotations

import http.client
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from veyltrace_core.config import load_section_file
from veyltrace_core.testing import repo_root
from veyltrace_llm.client import LLMClient
from veyltrace_llm.errors import ProviderTimeout, ProviderUnavailable
from veyltrace_llm.guard import Endpoint
from veyltrace_llm.ollama import OllamaProvider
from veyltrace_llm.providers import provider_for
from veyltrace_llm.request import LLMRequest, Message, ModelId, Usage
from veyltrace_llm.settings import LLMSettings, settings_from
from veyltrace_llm.transport import HttpResponse, HttpTransport, TransportError

PARAMS = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 1.5, "seed": 5, "max_tokens": 99}
SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in cast(Mapping[str, Any], value).items()}
    return value


def _settings(**runtime: Any) -> LLMSettings:
    section = _thaw(load_section_file("llm", config_dir=repo_root() / "config"))
    section["runtime"].update(runtime)
    return settings_from(section, env={})


class FakeTransport:
    """Records requests; answers from a queue of responses or TransportErrors."""

    def __init__(self, *answers: HttpResponse | TransportError) -> None:
        self.answers = list(answers)
        self.sent: list[tuple[str, str, Any, Mapping[str, str]]] = []

    def request(
        self,
        method: Literal["GET", "POST"],
        endpoint: Endpoint,
        route: str,
        body: bytes | None,
        headers: Mapping[str, str],
        connect_timeout_s: float,
        timeout_s: float,
    ) -> HttpResponse:
        self.sent.append((method, route, None if body is None else json.loads(body), dict(headers)))
        if route == "/api/version":
            return HttpResponse(200, b'{"version": "0.12.3"}')
        answer = self.answers.pop(0)
        if isinstance(answer, TransportError):
            raise answer
        return answer


def _ok(content: str = '{"x": 1}', **extra: Any) -> HttpResponse:
    body = {
        "model": "qwen3.5:9b",
        "created_at": "2026-11-09T00:00:00Z",
        "message": {"role": "assistant", "content": content},
    }
    body.update({"done": True, "prompt_eval_count": 321, "eval_count": 12, **extra})
    return HttpResponse(200, json.dumps(body).encode())


def _request(**params: Any) -> LLMRequest:
    return LLMRequest(
        "relentra.brief", ModelId("qwen3.5:9b"), (Message("user", "hi"),), {**PARAMS, **params}, SCHEMA
    )


def test_payload_maps_the_canonical_request() -> None:
    transport = FakeTransport(_ok())
    OllamaProvider(_settings(num_thread=4), transport).complete(_request(thinking=False))
    method, route, body, _ = transport.sent[0]
    assert (method, route) == ("POST", "/api/chat")
    assert body == {
        "model": "qwen3.5:9b",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "format": SCHEMA,
        "think": False,
        "options": {
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 20,
            "presence_penalty": 1.5,
            "seed": 5,
            "num_predict": 99,
            "num_ctx": 16384,
            "num_thread": 4,
        },
    }


def test_response_maps_to_a_completion_without_server_timestamps() -> None:
    completion = OllamaProvider(_settings(), FakeTransport(_ok())).complete(_request())
    assert completion.ok and completion.content == '{"x": 1}'
    assert completion.usage == Usage(321, 12)
    assert completion.runtime.provider == "ollama" and completion.runtime.version == "0.12.3"
    assert completion.latency_ms >= 0
    assert "2026-11-09" not in json.dumps(completion.as_json())


def test_missing_counts_are_zero() -> None:
    body = {"message": {"content": "{}"}}
    completion = OllamaProvider(
        _settings(), FakeTransport(HttpResponse(200, json.dumps(body).encode()))
    ).complete(_request())
    assert completion.usage == Usage(0, 0)


@pytest.mark.parametrize(
    ("answer", "kind"),
    [
        (TransportError("connection", "refused"), "connection"),
        (TransportError("timeout", "slow"), "timeout"),
        (HttpResponse(404, b'{"error":"model not found"}'), "http"),
        (HttpResponse(200, b"<html>"), "bad_response"),
        (HttpResponse(200, b'{"message": {"content": 7}}'), "bad_response"),
    ],
)
def test_failures_are_outcomes_not_exceptions(answer: HttpResponse | TransportError, kind: str) -> None:
    completion = OllamaProvider(_settings(), FakeTransport(answer)).complete(_request())
    assert completion.error is not None and completion.error.kind == kind
    assert completion.content is None and completion.usage == Usage(0, 0)


def test_no_retry_after_a_failure() -> None:
    transport = FakeTransport(TransportError("timeout", "slow"), _ok())
    OllamaProvider(_settings(), transport).complete(_request())
    assert [route for _, route, _, _ in transport.sent].count("/api/chat") == 1


def test_recorded_timeout_replays_without_the_server(tmp_path: Path) -> None:
    settings = _settings()
    provider = OllamaProvider(settings, FakeTransport(TransportError("timeout", "slow"), _ok()))
    record = LLMClient(settings, "record", tmp_path, provider=provider)
    with pytest.raises(ProviderTimeout):
        record.call_json("relentra.brief", [Message("user", "hi")], SCHEMA, PARAMS)
    assert record.call_json("relentra.brief", [Message("user", "hi")], SCHEMA, PARAMS).value == {"x": 1}
    replay = LLMClient(settings, "replay", tmp_path)
    with pytest.raises(ProviderTimeout):
        replay.call_json("relentra.brief", [Message("user", "hi")], SCHEMA, PARAMS)
    assert replay.call_json("relentra.brief", [Message("user", "hi")], SCHEMA, PARAMS).value == {"x": 1}


def test_factory_builds_the_configured_provider() -> None:
    assert isinstance(provider_for(_settings()), OllamaProvider)


class _FakeConnection:
    """Stands in for http.client.HTTPConnection: no socket."""

    mode: str = "ok"

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = None

    def connect(self) -> None:
        if self.mode == "refused":
            raise ConnectionRefusedError("refused")
        if self.mode == "connect_timeout":
            raise TimeoutError

    def request(self, method: str, url: str, body: bytes | None, headers: Mapping[str, str]) -> None:
        if self.mode == "read_timeout":
            raise TimeoutError

    def getresponse(self) -> Any:
        class _R:
            status = 200

            def read(self) -> bytes:
                return b"{}"

        return _R()

    def close(self) -> None:
        pass


@pytest.mark.parametrize(
    ("mode", "kind"),
    [("refused", "connection"), ("connect_timeout", "connection"), ("read_timeout", "timeout"), ("ok", None)],
)
def test_http_transport_maps_socket_failures(
    mode: str, kind: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_FakeConnection, "mode", mode)
    monkeypatch.setattr(http.client, "HTTPConnection", _FakeConnection)
    endpoint = Endpoint("http", "127.0.0.1", 11434, "")
    if kind is None:
        assert HttpTransport().request("GET", endpoint, "/api/version", None, {}, 1.0, 2.0).status == 200
        return
    with pytest.raises(TransportError) as exc:
        HttpTransport().request("POST", endpoint, "/api/chat", b"{}", {}, 1.0, 2.0)
    assert exc.value.kind == kind


def test_unreachable_server_raises_provider_unavailable(tmp_path: Path) -> None:
    settings = _settings()
    client = LLMClient(
        settings,
        "record",
        tmp_path,
        provider=OllamaProvider(settings, FakeTransport(TransportError("connection", "down"))),
    )
    with pytest.raises(ProviderUnavailable):
        client.call_json("relentra.brief", [Message("user", "hi")], SCHEMA, PARAMS)
