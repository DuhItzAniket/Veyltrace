"""Shared machinery of the HTTP providers (Ollama, llama.cpp server, OpenAI-compatible).

A subclass says how a canonical request becomes a JSON payload and how a response body becomes
content and usage. This base sends it once, measures latency with the monotonic clock (the only
clock read in the pipeline, package rule 7), and turns every failure into an error outcome:
`connection`, `timeout`, `http` (non-2xx) or `bad_response` (unreadable body). It never retries.
The runtime version is asked once per provider, for the audit field `runtime.version`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any, ClassVar, Final, Literal

from veyltrace_core.canonical import canonical_json
from veyltrace_llm.request import CallError, Completion, ErrorKind, LLMRequest, Runtime, Usage
from veyltrace_llm.settings import LLMSettings
from veyltrace_llm.transport import HttpResponse, HttpTransport, Transport, TransportError

__all__ = ["ERROR_BODY_CHARS", "HttpProvider", "count"]

_MS_PER_S: Final = 1000.0
#: Bytes of a non-2xx body kept in the recorded error message (enough for the server's reason).
ERROR_BODY_CHARS: Final = 200


class HttpProvider:
    """Base class; subclasses set `kind`, `chat_route`, `payload` and `parse`."""

    kind: ClassVar[str]
    chat_route: ClassVar[str]
    version_route: ClassVar[str | None] = None

    def __init__(self, settings: LLMSettings, transport: Transport | None = None) -> None:
        self.settings = settings
        self.transport: Transport = transport if transport is not None else HttpTransport()
        self._version: str | None = None
        self._version_asked = False

    # --- subclass hooks --------------------------------------------------------------------
    def payload(self, request: LLMRequest) -> dict[str, Any]:
        raise NotImplementedError

    def parse(self, body: Mapping[str, Any]) -> tuple[str, Usage]:
        raise NotImplementedError

    def headers(self) -> dict[str, str]:
        """Extra request headers; never recorded anywhere."""
        return {}

    def parse_version(self, body: Mapping[str, Any]) -> str | None:
        return None

    # --- calls -----------------------------------------------------------------------------
    def _send(self, method: Literal["GET", "POST"], route: str, body: bytes | None) -> HttpResponse:
        s = self.settings
        return self.transport.request(
            method, s.endpoint, route, body, self.headers(), s.connect_timeout_s, s.timeout_s
        )

    def version(self) -> str | None:
        """The runtime's version string, asked once; None when the runtime does not say."""
        if not self._version_asked and self.version_route is not None:
            self._version_asked = True
            try:
                response = self._send("GET", self.version_route, None)
                if 200 <= response.status < 300:
                    self._version = self.parse_version(json.loads(response.body))
            except (TransportError, ValueError, KeyError, TypeError, AttributeError):
                self._version = None
        return self._version

    def _failure(self, kind: ErrorKind, message: str, latency_ms: float) -> Completion:
        return Completion(
            content=None,
            usage=Usage(0, 0),
            latency_ms=latency_ms,
            runtime=Runtime(self.kind, self.version()),
            error=CallError(kind, message),
        )

    def complete(self, request: LLMRequest) -> Completion:
        """One POST; the outcome, success or failure, with its measured latency."""
        body = canonical_json(self.payload(request))
        start = time.perf_counter()
        try:
            response = self._send("POST", self.chat_route, body)
        except TransportError as exc:
            return self._failure(exc.kind, exc.message, (time.perf_counter() - start) * _MS_PER_S)
        latency_ms = (time.perf_counter() - start) * _MS_PER_S
        if not 200 <= response.status < 300:
            text = response.body[:ERROR_BODY_CHARS].decode("utf-8", errors="replace")
            return self._failure("http", f"HTTP {response.status}: {text}", latency_ms)
        try:
            content, usage = self.parse(json.loads(response.body))
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            return self._failure("bad_response", f"unreadable response: {exc!r}", latency_ms)
        return Completion(content, usage, latency_ms, Runtime(self.kind, self.version()))


def count(body: Mapping[str, Any], key: str) -> int:
    """A provider-reported token count; absent or null counts as 0 (e.g. a fully cached prompt)."""
    value = body.get(key)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative int, got {value!r}")
    return value
