"""The live OTLP/HTTP receiver (06 §3.3): `POST /v1/{traces,metrics,logs}` on its own listener.

Why a seam: the gateway does not parse telemetry semantics (06 §3.3). Each decoded request goes
to Infralume's converter `veyltrace_infralume.otlp` (O-07, Observe lane), which returns a
canonical-shape Arrow table, already normalised and scrubbed, plus its scrub counters. The
converter is passed in (`OtlpConverter`), so the real module drops in unchanged; without one the
receiver answers 503 and the Collector retries. The request shape is the OTLP protobuf-JSON
mapping, the same as one line of a lab capture's `otlp/*.jsonl` (proposed on #24). Protobuf
bodies are 415 until `opentelemetry-proto` is a dependency (OTLP/HTTP: an unsupported content
type MUST be 415). Gzip is accepted; the size limit applies before and after decompression. An
unreadable body is 400 (OTLP: not retried). A converter failure is 503 with `Retry-After`, which
OTLP/HTTP clients retry (they retry only 429/502/503/504, never 500), so a converter bug drops no
data while the client's retry budget lasts. A batch the buffer refuses is acknowledged as an OTLP
partial success.
"""

# No `from __future__ import annotations`: FastAPI reads the route annotations at creation.
import hashlib
import json
import zlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Protocol, cast

import pyarrow as pa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from veyltrace_core.log import get_logger
from veyltrace_gateway.buffer import BYTES_PER_MIB, AddResult, LiveBuffer
from veyltrace_gateway.errors import ApiError, add_error_handlers

__all__ = ["SIGNALS", "OtlpConverter", "ReceiverCounters", "create_otlp_app"]

#: OTLP/HTTP path → buffer source, and the partial-success field naming what was rejected.
SIGNALS: Final = {"traces": "spans", "metrics": "metrics", "logs": "logs"}
_REJECTED: Final = {"traces": "rejectedSpans", "metrics": "rejectedDataPoints", "logs": "rejectedLogRecords"}
_JSON: Final = "application/json"
_GZIP_WBITS: Final = 16 + zlib.MAX_WBITS
_LOG: Final = get_logger(__name__)
Converts = Callable[[Mapping[str, Any], Mapping[str, Any]], tuple[pa.Table, Mapping[str, int]]]


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
    """Request outcomes since start (06 §3.3 "a counter"), scrub counters summed; rejections are
    logged too, and `/live/status` (#469) reports the counts."""

    accepted: int = 0
    duplicate: int = 0
    rejected: int = 0
    scrub: dict[str, int] = field(default_factory=lambda: {})
    converter_installed: bool = False


async def _body(request: Request, limit: int) -> bytes:
    """The raw body, refused past `limit` while it streams in and again after gzip (413)."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise ApiError(413, "body_too_large", f"OTLP body exceeds {limit} bytes")
        chunks.append(chunk)
    raw = b"".join(chunks)
    encoding = request.headers.get("content-encoding", "identity").strip().lower()
    if encoding == "identity":
        return raw
    if encoding != "gzip":  # OTLP/HTTP defines only gzip
        raise ApiError(415, "unsupported_encoding", f"content-encoding {encoding!r}: send gzip or none")
    inflater = zlib.decompressobj(_GZIP_WBITS)
    try:
        data = inflater.decompress(raw, limit + 1)
    except zlib.error as exc:
        raise ApiError(400, "malformed_body", f"bad gzip body: {exc}") from None
    if len(data) > limit or inflater.unconsumed_tail:
        raise ApiError(413, "body_too_large", f"decompressed OTLP body exceeds {limit} bytes")
    if not inflater.eof or inflater.unused_data:
        raise ApiError(400, "malformed_body", "truncated or multi-member gzip body")
    return data


def create_otlp_app(
    buffer: LiveBuffer,
    converter: OtlpConverter | None,
    convert_settings: Mapping[str, Any],
    *,
    max_body_mb: int,
    retry_after_s: int,
    counters: ReceiverCounters | None = None,
) -> FastAPI:
    """The receiver app; it shares `buffer` (and `counters`) with the API app. `retry_after_s` is
    the `Retry-After` of a converter failure (`live.retry_after_s`)."""
    app = FastAPI(title="Veyltrace OTLP receiver", docs_url=None, redoc_url=None, openapi_url=None)
    add_error_handlers(app)
    tally = counters if counters is not None else ReceiverCounters()
    tally.converter_installed = converter is not None
    limit = max_body_mb * BYTES_PER_MIB
    retry_after = str(retry_after_s)

    def ingest(convert: Converts, signal: str, raw: bytes) -> tuple[AddResult, int, Mapping[str, int]]:
        """Decode, convert and buffer one body; runs in a worker thread, off the event loop."""
        try:
            decoded: object = json.loads(raw)
        except ValueError as exc:  # also bad UTF-8
            raise ApiError(400, "malformed_body", f"{type(exc).__name__}: {exc}") from None
        if not isinstance(decoded, dict):
            raise ApiError(400, "malformed_body", "expected a JSON object")
        table, scrub = convert(cast(dict[str, Any], decoded), convert_settings)
        digest = hashlib.sha256(signal.encode() + b"\0" + raw).hexdigest()
        return buffer.add(SIGNALS[signal], table, digest), table.num_rows, scrub

    async def receive(signal: str, request: Request) -> JSONResponse:
        try:
            if converter is None:
                raise ApiError(
                    503, "converter_unavailable", "Infralume's OTLP converter is not installed yet"
                )
            media = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if media != _JSON:
                raise ApiError(415, "unsupported_media_type", f"{media or 'no content type'}: send {_JSON}")
            functions: dict[str, Converts] = {
                "traces": converter.spans, "metrics": converter.metrics, "logs": converter.logs,
            }  # fmt: skip
            raw = await _body(request, limit)
            outcome, rows, scrub = await run_in_threadpool(ingest, functions[signal], signal, raw)
        except ApiError as exc:
            tally.rejected += 1
            _LOG.warning(
                "otlp_rejected", signal=signal, status=exc.status, code=exc.code, message=exc.message
            )
            raise
        except Exception as exc:  # a converter bug or a RecursionError: 503, so the Collector retries
            tally.rejected += 1
            _LOG.warning("otlp_failed", signal=signal, error=f"{type(exc).__name__}: {exc}")
            raise ApiError(
                503, "conversion_failed", f"{type(exc).__name__}: {exc}", {"Retry-After": retry_after}
            ) from None
        if outcome == "duplicate":
            tally.duplicate += 1
            return JSONResponse({})
        tally.accepted += 1
        for key, count in scrub.items():
            tally.scrub[key] = tally.scrub.get(key, 0) + int(count)
        if outcome == "accepted":
            return JSONResponse({})  # Export*ServiceResponse: full success
        # The buffer refused the batch (it logs and counts that): an OTLP partial success.
        return JSONResponse(
            {"partialSuccess": {_REJECTED[signal]: str(rows), "errorMessage": f"buffer: {outcome}"}}
        )

    def route_for(signal: str) -> Callable[[Request], Awaitable[JSONResponse]]:
        async def route(request: Request) -> JSONResponse:
            return await receive(signal, request)

        return route

    for signal in SIGNALS:
        app.post(f"/v1/{signal}", name=f"otlp_{signal}")(route_for(signal))
    return app
