"""The error envelope of 06 §3.1: every error is `{"error": {"code", "message"}}`.

Why handlers for the framework's own errors too: the console reads one error shape, so a 404 for
an unknown route and a 422 for a bad query parameter must look like the gateway's own errors. The
same holds for a server error: an artifact `veyltrace_core.io` refuses (another contract version,
a truncated file) is 500 `artifact_invalid`, any other failure 500 `internal_error`.
"""

from __future__ import annotations

from typing import Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from veyltrace_core.errors import ContractValidationError, VeyltraceError
from veyltrace_core.log import get_logger
from veyltrace_gateway.api_models import ErrorBody, ErrorDetail

__all__ = ["ApiError", "add_error_handlers"]

_CODES: Final = {404: "not_found", 405: "method_not_allowed"}
_LOG: Final = get_logger(__name__)


class ApiError(Exception):
    """A gateway error with its HTTP status (06 §3.1; also 405, 415 and 500)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _envelope(status: int, code: str, message: str) -> JSONResponse:
    body = ErrorBody(error=ErrorDetail(code=code, message=message))
    return JSONResponse(body.model_dump(), status_code=status)


def add_error_handlers(app: FastAPI) -> None:
    """Map ApiError, framework HTTP errors and request validation errors to the envelope."""

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _envelope(exc.status, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)  # also the router's own 404 and 405
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _envelope(exc.status_code, _CODES.get(exc.status_code, "http_error"), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        where = "; ".join(".".join(map(str, e["loc"])) + ": " + e["msg"] for e in exc.errors())
        return _envelope(422, "invalid_request", where)

    @app.exception_handler(VeyltraceError)  # e.g. an artifact io refuses to read
    async def veyltrace_error(request: Request, exc: VeyltraceError) -> JSONResponse:
        code = "artifact_invalid" if isinstance(exc, ContractValidationError) else "internal_error"
        _LOG.error("request_failed", path=request.url.path, code=code, error=f"{type(exc).__name__}: {exc}")
        return _envelope(500, code, str(exc))

    @app.exception_handler(Exception)  # last resort; Starlette still re-raises it to the server log
    async def server_error(_: Request, exc: Exception) -> JSONResponse:
        return _envelope(500, "internal_error", f"{type(exc).__name__}: {exc}")
