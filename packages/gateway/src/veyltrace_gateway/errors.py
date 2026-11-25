"""The error envelope of 06 §3.1: every error is `{"error": {"code", "message"}}`.

Why handlers for the framework's own errors too: the console reads one error shape, so a 404 for
an unknown route and a 422 for a bad query parameter must look like the gateway's own errors.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from veyltrace_gateway.api_models import ErrorBody, ErrorDetail

__all__ = ["ApiError", "add_error_handlers"]

_CODES: Final = {404: "not_found", 405: "method_not_allowed"}


class ApiError(Exception):
    """A gateway error with its HTTP status (06 §3.1: 400/404/409/413/422/503)."""

    def __init__(
        self, status: int, code: str, message: str, headers: Mapping[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.headers = dict(headers or {})  # e.g. Retry-After on a 503 the client should retry


def _envelope(status: int, code: str, message: str, headers: Mapping[str, str] | None = None) -> JSONResponse:
    body = ErrorBody(error=ErrorDetail(code=code, message=message))
    return JSONResponse(body.model_dump(), status_code=status, headers=headers)


def add_error_handlers(app: FastAPI) -> None:
    """Map ApiError, framework HTTP errors and request validation errors to the envelope."""

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _envelope(exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(StarletteHTTPException)  # also the router's own 404 and 405
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _envelope(exc.status_code, _CODES.get(exc.status_code, "http_error"), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        where = "; ".join(".".join(map(str, e["loc"])) + ": " + e["msg"] for e in exc.errors())
        return _envelope(422, "invalid_request", where)
