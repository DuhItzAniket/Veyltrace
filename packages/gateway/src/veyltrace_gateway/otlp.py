"""The live OTLP/HTTP receiver (06 §3.3): `POST /v1/{traces,metrics,logs}` on its own listener.

Why a seam: the gateway does not parse telemetry semantics (06 §3.3). Each decoded request goes
to Infralume's converter `veyltrace_infralume.otlp` (O-07, Observe lane), which returns a
canonical-shape Arrow table, already normalised and scrubbed, plus its scrub counters. The
converter is passed in (`OtlpConverter`), so the real module drops in unchanged; without one the
receiver answers 503 and the Collector retries. The request shape is the OTLP protobuf-JSON
mapping, the same as one line of a lab capture's `otlp/*.jsonl` (proposed on #24). Protobuf
bodies are 415 until `opentelemetry-proto` is a dependency (OTLP/HTTP: an unsupported content
type MUST be 415). Gzip is accepted; the size limit applies before and after decompression.
"""

# No `from __future__ import annotations`: FastAPI reads the route annotations at creation.
import hashlib
import json
import zlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

import pyarrow as pa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from veyltrace_core.errors import ContractValidationError
from veyltrace_gateway.buffer import LiveBuffer
from veyltrace_gateway.errors import ApiError, add_error_handlers

__all__ = ["SIGNALS", "OtlpConverter", "ReceiverCounters", "create_otlp_app"]

#: OTLP/HTTP path → (converter function, buffer source).
SIGNALS: Final = {"traces": ("spans", "spans"), "metrics": ("metrics", "metrics"), "logs": ("logs", "logs")}
_JSON: Final = "application/json"
_GZIP_WBITS: Final = 16 + zlib.MAX_WBITS
_BYTES_PER_MB: Final = 1024 * 1024


class OtlpConverter(Protocol):
    """`veyltrace_infralume.otlp` (01 §3.9; interface proposed on #24): pure functions from one
    OTLP/JSON export request to a canonical table and the scrub counters. `settings` is the
    `infralume` section of `config/infralume.yaml`."""

    def spans(
        self, request: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> tuple[pa.Table, Mapping[str, int]]: ...

    def metrics(
        self, request: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> tuple[pa.Table, Mapping[str, int]]: ...

    def logs(
        self, request: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> tuple[pa.Table, Mapping[str, int]]: ...


@dataclass
class ReceiverCounters:
    """Request outcomes since start (06 §3.3 "a counter"); the scrub counters are summed."""

    accepted: int = 0
    duplicate: int = 0
    rejected: int = 0
    scrub: dict[str, int] = field(default_factory=lambda: {})


async def _body(request: Request, limit: int) -> bytes:
    """The raw body, refused past `limit` while it streams in (413)."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise ApiError(413, "body_too_large", f"OTLP body exceeds {limit} bytes")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if request.headers.get("content-encoding", "identity").lower() != "gzip":
        return raw
    inflater = zlib.decompressobj(_GZIP_WBITS)
    try:
        data = inflater.decompress(raw, limit + 1)
    except zlib.error as exc:
        raise ApiError(400, "malformed_body", f"bad gzip body: {exc}") from None
    if len(data) > limit or inflater.unconsumed_tail:
        raise ApiError(413, "body_too_large", f"decompressed OTLP body exceeds {limit} bytes")
    return data


def create_otlp_app(
    buffer: LiveBuffer,
    converter: OtlpConverter | None,
    convert_settings: Mapping[str, Any],
    *,
    max_body_mb: int,
    counters: ReceiverCounters | None = None,
) -> FastAPI:
    """The receiver app; it shares `buffer` (and `counters`) with the API app."""
    app = FastAPI(title="Veyltrace OTLP receiver", docs_url=None, redoc_url=None, openapi_url=None)
    add_error_handlers(app)
    tally = counters if counters is not None else ReceiverCounters()
    limit = max_body_mb * _BYTES_PER_MB

    async def receive(signal: str, request: Request) -> JSONResponse:
        try:
            return await convert(signal, request)
        except ApiError:
            tally.rejected += 1
            raise

    async def convert(signal: str, request: Request) -> JSONResponse:
        if converter is None:
            raise ApiError(503, "converter_unavailable", "Infralume's OTLP converter is not installed yet")
        media = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if media != _JSON:
            raise ApiError(415, "unsupported_media_type", f"{media or 'no content type'}: send {_JSON}")
        raw = await _body(request, limit)
        function, source = SIGNALS[signal]
        try:
            decoded: object = json.loads(raw)
            if not isinstance(decoded, dict):
                raise ValueError("expected a JSON object")
            table, scrub = await run_in_threadpool(getattr(converter, function), decoded, convert_settings)
            fresh = buffer.add(source, table, hashlib.sha256(signal.encode() + b"\0" + raw).hexdigest())
        except (ValueError, KeyError, TypeError, ContractValidationError) as exc:
            raise ApiError(400, "malformed_body", f"{type(exc).__name__}: {exc}") from None
        if fresh:
            tally.accepted += 1
            for key, count in scrub.items():
                tally.scrub[key] = tally.scrub.get(key, 0) + int(count)
        else:
            tally.duplicate += 1
        return JSONResponse({})  # Export*ServiceResponse: full success, no partial_success

    def route_for(signal: str) -> Callable[[Request], Awaitable[JSONResponse]]:
        async def route(request: Request) -> JSONResponse:
            return await receive(signal, request)

        return route

    for signal in SIGNALS:
        app.post(f"/v1/{signal}", name=f"otlp_{signal}")(route_for(signal))
    return app
