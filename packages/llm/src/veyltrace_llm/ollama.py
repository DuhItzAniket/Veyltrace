"""Ollama provider: `POST /api/chat`, non-streaming, with the JSON schema as `format` (08 §3.8).

Mapping (canonical request → Ollama): messages as given; `format` = the schema (Ollama's structured
output); `think` = `thinking` (Ollama's "disable thinking" flag); options `temperature`, `top_p`,
`top_k`, `presence_penalty`, `seed`, `num_predict` = `max_tokens`, plus the runtime keys `num_ctx`
and `num_thread` (when set). A null param is not sent, so Ollama's default applies (03 §9.1
nullable params). Usage = `prompt_eval_count`, `eval_count`. `OLLAMA_NUM_PARALLEL=1` is a server
setting this package cannot set (08 §3.8, L-01 guide); the runtime version comes from
`GET /api/version`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Final

from veyltrace_llm.http_provider import HttpProvider, count
from veyltrace_llm.request import LLMRequest, Usage

__all__ = ["OllamaProvider"]

#: Canonical sampler params that map 1:1 onto Ollama options of the same name.
_SAME_NAME: Final = ("temperature", "top_p", "top_k", "presence_penalty", "seed")


class OllamaProvider(HttpProvider):
    kind: ClassVar[str] = "ollama"
    chat_route: ClassVar[str] = "/api/chat"
    version_route: ClassVar[str | None] = "/api/version"

    def payload(self, request: LLMRequest) -> dict[str, Any]:
        params = request.params
        options: dict[str, Any] = {name: params[name] for name in _SAME_NAME if params[name] is not None}
        options["num_predict"] = params["max_tokens"]
        options["num_ctx"] = self.settings.num_ctx
        if self.settings.num_thread is not None:
            options["num_thread"] = self.settings.num_thread
        body: dict[str, Any] = {
            "model": request.model.name,
            "messages": [m.as_json() for m in request.messages],
            "stream": False,
            "options": options,
        }
        if request.schema is not None:
            body["format"] = dict(request.schema)
        if params["thinking"] is not None:
            body["think"] = params["thinking"]
        return body

    def parse(self, body: Mapping[str, Any]) -> tuple[str, Usage]:
        content = body["message"]["content"]
        if not isinstance(content, str):
            raise TypeError(f"message.content is {type(content).__name__}, not a string")
        return content, Usage(count(body, "prompt_eval_count"), count(body, "eval_count"))

    def parse_version(self, body: Mapping[str, Any]) -> str | None:
        version = body.get("version")
        return version if isinstance(version, str) else None
