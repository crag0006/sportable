"""One error envelope for every failure: ``{"error": {"code": ..., "message": ...}}``.

A genuine API error must stay JSON with the right status code. CloudFront's SPA
fallback deliberately does not apply to ``/api/*``, and the deploy smoke test
asserts that a 404 from here is ``application/json`` — so nothing below may
ever fall through to a framework default HTML page.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        """An API failure with its HTTP status, machine code and message."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _envelope(status: int, code: str, message: str) -> JSONResponse:
    """The one JSON error shape, with the given status code."""
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def install_error_handlers(app: FastAPI) -> None:
    """Route every failure through the single error envelope."""

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        """Business and validation failures raised as ``ApiError``."""
        return _envelope(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        """FastAPI's own 422, reshaped to the envelope with the first problem named."""
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "query")
        detail = str(first.get("msg", "invalid request"))
        message = f"{where}: {detail}" if where else detail
        return _envelope(422, "validation_error", message)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        """Anything else: logged with its traceback, answered as a JSON 500."""
        log.exception("unhandled error: %s", exc)
        return _envelope(500, "internal_error", "Something went wrong on our side.")
