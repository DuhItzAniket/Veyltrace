"""llama.cpp server and OpenAI-compatible providers, with a fake transport: no network (#18)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from veyltrace_core.config import load_section_file
from veyltrace_core.testing import repo_root
from veyltrace_llm.client import LLMClient
from veyltrace_llm.guard import Endpoint
from veyltrace_llm.openai_chat import API_KEY_ENV, LlamaCppProvider, OpenAICompatProvider
from veyltrace_llm.providers import provider_for
from veyltrace_llm.request import LLMRequest, Message, ModelId, Usage
from veyltrace_llm.settings import LLMSettings, settings_from
from veyltrace_llm.transport import HttpResponse

PARAMS = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 1.5, "seed": 5, "max_tokens": 99}
SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
OK = {
    "choices": [{"message": {"role": "assistant", "content": '{"x": 2}'}}],
    "usage": {"prompt_tokens": 40, "completion_tokens": 3},
}


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in cast(Mapping[str, Any], value).items()}
    return value


def _settings(provider: str) -> LLMSettings:
    section = _thaw(load_section_file("llm", config_dir=repo_root() / "config"))
    section.update(provider=provider, base_url="http://127.0.0.1:8080")
    return settings_from(section, env={})


class Recorder:
    def __init__(self, status: int = 200, body: Any = OK) -> None:
        self.status, self.body = status, body
        self.sent: list[tuple[str, str, Any, dict[str, str]]] = []

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
        if route == "/props":
            return HttpResponse(200, b'{"build_info": "b6100-abc123"}')
        return HttpResponse(self.status, json.dumps(self.body).encode())


def _request(**params: Any) -> LLMRequest:
    return LLMRequest(
        "causivra.narrate", ModelId("qwen3.5:9b"), (Message("user", "hi"),), {**PARAMS, **params}, SCHEMA
    )


def test_llamacpp_payload_and_version() -> None:
    transport = Recorder()
    completion = LlamaCppProvider(_settings("llamacpp"), transport).complete(_request(thinking=False))
    post = next(s for s in transport.sent if s[0] == "POST")
    assert post[1] == "/v1/chat/completions"
    assert post[2] == {
        "model": "qwen3.5:9b",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "presence_penalty": 1.5,
        "seed": 5,
        "max_tokens": 99,
        "cache_prompt": False,
        "response_format": {"type": "json_schema", "json_schema": {"schema": SCHEMA}},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    assert completion.content == '{"x": 2}' and completion.usage == Usage(40, 3)
    assert completion.runtime.provider == "llamacpp" and completion.runtime.version == "b6100-abc123"


def test_openai_compat_payload_sends_only_standard_fields() -> None:
    transport = Recorder()
    provider = OpenAICompatProvider(_settings("openai_compat"), transport, env={})
    provider.complete(_request(thinking=False))
    _, route, body, headers = transport.sent[0]
    assert route == "/v1/chat/completions"
    assert "top_k" not in body and "chat_template_kwargs" not in body and "cache_prompt" not in body
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "causivra_narrate", "schema": SCHEMA, "strict": True},
    }
    assert "Authorization" not in headers


def test_api_key_comes_from_the_environment_and_is_never_recorded(tmp_path: Path) -> None:
    settings = _settings("openai_compat")
    transport = Recorder()
    provider = OpenAICompatProvider(settings, transport, env={API_KEY_ENV: "sk-test-not-a-real-key"})
    LLMClient(settings, "record", tmp_path, provider=provider).call_json(
        "causivra.narrate", [Message("user", "hi")], SCHEMA, PARAMS
    )
    assert transport.sent[0][3]["Authorization"] == "Bearer sk-test-not-a-real-key"
    recorded = b"".join(p.read_bytes() for p in tmp_path.iterdir())
    assert b"sk-test" not in recorded and b"Authorization" not in recorded


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (500, {"error": "boom"}, "http"),
        (200, {"choices": []}, "bad_response"),
        (200, {"choices": [{"message": {}}]}, "bad_response"),
    ],
)
def test_chat_failures_are_outcomes(status: int, body: Any, kind: str) -> None:
    completion = LlamaCppProvider(_settings("llamacpp"), Recorder(status, body)).complete(_request())
    assert completion.error is not None and completion.error.kind == kind


def test_missing_usage_counts_as_zero() -> None:
    body = {"choices": [{"message": {"content": "{}"}}]}
    assert OpenAICompatProvider(_settings("openai_compat"), Recorder(200, body), env={}).complete(
        _request()
    ).usage == Usage(0, 0)


@pytest.mark.parametrize(
    ("name", "cls"), [("llamacpp", LlamaCppProvider), ("openai_compat", OpenAICompatProvider)]
)
def test_factory_builds_chat_providers(name: str, cls: type) -> None:
    assert isinstance(provider_for(_settings(name)), cls)
