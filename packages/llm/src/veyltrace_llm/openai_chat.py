"""llama.cpp `llama-server` and OpenAI-compatible providers: `POST /v1/chat/completions` (08 §3.8).

Both speak the OpenAI chat-completions shape; `base_url` is the server root (the route adds `/v1`).

- **llamacpp** (`llama-server -np 1`): sampler params as top-level fields, `max_tokens`,
  `cache_prompt` from `runtime.cache_prompt` (false: llama.cpp warns the prompt cache can make
  results nondeterministic), the schema as `response_format: {type: json_schema, json_schema:
  {schema}}`, and `thinking` as `chat_template_kwargs.enable_thinking` (Qwen3.5 templates). The
  version comes from `GET /props` (`build_info`). `num_ctx`/`num_thread` are server start flags,
  recorded in the cassette entry, not sent.
- **openai_compat**: the standard fields only (no `top_k`, no thinking switch: the API has none),
  the schema as a strict `json_schema` response format named after the purpose, and an optional
  bearer key read from `VEYLTRACE_LLM_API_KEY` in the environment, never from config and never
  recorded (package Never list).

A null sampler param is not sent (the server default applies). Usage = `usage.prompt_tokens`,
`usage.completion_tokens`; content = `choices[0].message.content`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, ClassVar, Final

from veyltrace_llm.http_provider import HttpProvider, count
from veyltrace_llm.request import LLMRequest, Usage
from veyltrace_llm.settings import LLMSettings
from veyltrace_llm.transport import Transport

__all__ = ["API_KEY_ENV", "LlamaCppProvider", "OpenAICompatProvider"]

#: Environment variable holding an optional bearer key for an OpenAI-compatible server.
API_KEY_ENV: Final = "VEYLTRACE_LLM_API_KEY"
_OPENAI_PARAMS: Final = ("temperature", "top_p", "presence_penalty", "seed", "max_tokens")
_LLAMACPP_PARAMS: Final = ("temperature", "top_p", "top_k", "presence_penalty", "seed", "max_tokens")


class _ChatCompletions(HttpProvider):
    chat_route: ClassVar[str] = "/v1/chat/completions"
    sent_params: ClassVar[tuple[str, ...]] = _OPENAI_PARAMS

    def _base(self, request: LLMRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model.name,
            "messages": [m.as_json() for m in request.messages],
            "stream": False,
        }
        body.update({n: request.params[n] for n in self.sent_params if request.params[n] is not None})
        return body

    def parse(self, body: Mapping[str, Any]) -> tuple[str, Usage]:
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise TypeError(f"choices[0].message.content is {type(content).__name__}, not a string")
        usage = body.get("usage") or {}
        if not isinstance(usage, Mapping):
            raise TypeError("usage is not an object")
        return content, Usage(count(usage, "prompt_tokens"), count(usage, "completion_tokens"))


class LlamaCppProvider(_ChatCompletions):
    kind: ClassVar[str] = "llamacpp"
    version_route: ClassVar[str | None] = "/props"
    sent_params: ClassVar[tuple[str, ...]] = _LLAMACPP_PARAMS

    def payload(self, request: LLMRequest) -> dict[str, Any]:
        body = self._base(request)
        body["cache_prompt"] = self.settings.cache_prompt
        if request.schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {"schema": dict(request.schema)}}
        if request.params["thinking"] is not None:
            body["chat_template_kwargs"] = {"enable_thinking": request.params["thinking"]}
        return body

    def parse_version(self, body: Mapping[str, Any]) -> str | None:
        build = body.get("build_info")
        return build if isinstance(build, str) else None


class OpenAICompatProvider(_ChatCompletions):
    kind: ClassVar[str] = "openai_compat"

    def __init__(
        self, settings: LLMSettings, transport: Transport | None = None, env: Mapping[str, str] | None = None
    ) -> None:
        super().__init__(settings, transport)
        self._api_key = (os.environ if env is None else env).get(API_KEY_ENV) or None

    def payload(self, request: LLMRequest) -> dict[str, Any]:
        body = self._base(request)
        if request.schema is not None:
            name = request.purpose.replace(".", "_")
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": name, "schema": dict(request.schema), "strict": True},
            }
        return body

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
