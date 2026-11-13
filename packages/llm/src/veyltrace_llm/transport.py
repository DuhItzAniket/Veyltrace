"""Stdlib HTTP for the providers: one request, JSON in and out, two timeouts, no retries.

Why stdlib `http.client`: it adds no dependency, and it is imported only when a request is made,
so importing an engine that uses `veyltrace_llm` never loads a network module (isolation test,
fresh-interpreter rule). The connect timeout bounds reaching the server (`connect_timeout_s`), the
read timeout bounds generation (`timeout_s`); either failure is a `TransportError` that the provider
turns into a recorded outcome. Nothing here retries (package Never list).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from veyltrace_llm.guard import Endpoint

__all__ = ["HttpResponse", "HttpTransport", "Transport", "TransportError"]

_JSON: Final = "application/json"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


class TransportError(Exception):
    """The server could not be reached (`connection`) or did not answer in time (`timeout`)."""

    def __init__(self, kind: Literal["connection", "timeout"], message: str) -> None:
        super().__init__(message)
        self.kind: Literal["connection", "timeout"] = kind
        self.message = message


class Transport(Protocol):
    def request(
        self,
        method: Literal["GET", "POST"],
        endpoint: Endpoint,
        route: str,
        body: bytes | None,
        headers: Mapping[str, str],
        connect_timeout_s: float,
        timeout_s: float,
    ) -> HttpResponse: ...


class HttpTransport:
    """`http.client` over the guard-checked endpoint (the host is never re-resolved here)."""

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
        import http.client

        cls = http.client.HTTPSConnection if endpoint.scheme == "https" else http.client.HTTPConnection
        conn = cls(endpoint.host, endpoint.port, timeout=connect_timeout_s)
        try:
            try:
                conn.connect()
            except TimeoutError as exc:
                raise TransportError("connection", f"connect to {endpoint.url('')} timed out") from exc
            except OSError as exc:
                raise TransportError("connection", f"cannot connect to {endpoint.url('')}: {exc}") from exc
            if conn.sock is not None:
                conn.sock.settimeout(timeout_s)
            sent = {"Accept": _JSON, **({"Content-Type": _JSON} if body is not None else {}), **headers}
            try:
                conn.request(method, endpoint.path + route, body=body, headers=sent)
                response = conn.getresponse()
                return HttpResponse(response.status, response.read())
            except TimeoutError as exc:
                msg = f"no answer from {endpoint.url(route)} in {timeout_s} s"
                raise TransportError("timeout", msg) from exc
            except (OSError, http.client.HTTPException) as exc:
                raise TransportError("connection", f"{endpoint.url(route)}: {exc}") from exc
        finally:
            conn.close()
