"""Application error type and the shared FastAPI exception handlers that
turn it (and any unhandled exception) into the consistent error envelope.

Security checklist reference: section 14 -- user-facing error messages never
include stack traces, internal paths, or query details; only a safe code +
message + request id go to the client, the full exception is logged
server-side.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from app.schemas.common import ErrorDetail, ErrorEnvelope

logger = logging.getLogger("market_access_evidence_assistant")


class AppError(Exception):
    """Raised by services/routes for any expected, user-facing failure."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _envelope(request: Request, code: str, message: str, details: dict[str, Any] | None = None) -> dict:
    return ErrorEnvelope(
        error=ErrorDetail(code=code, message=message, request_id=_request_id(request), details=details)
    ).model_dump()


def _safe_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe_errors: list[dict[str, Any]] = []
    for error in errors:
        safe_errors.append(
            {
                key: value
                for key, value in error.items()
                if key not in {"input", "ctx", "url"}
            }
        )
    return safe_errors


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope(
                request,
                "VALIDATION_ERROR",
                "Request validation failed.",
                {"errors": _safe_validation_errors(exc.errors())},
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception request_id=%s", _request_id(request))
        return JSONResponse(
            status_code=500,
            content=_envelope(request, "INTERNAL_ERROR", "An unexpected error occurred."),
        )
