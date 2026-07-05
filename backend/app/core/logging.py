"""Structured logging setup and request-ID propagation.

Per the security checklist (error handling/logging section): logs carry
enough context to reconstruct a request (request id, path, status, latency)
but never full document text, questions, or secrets.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

logger = logging.getLogger("market_access_evidence_assistant")


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        format="%(asctime)s level=%(levelname)s logger=%(name)s %(message)s",
    )


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get(REQUEST_ID_HEADER, uuid.uuid4().hex)
    request.state.request_id = request_id
    started_at = time.monotonic()

    response = await call_next(request)

    latency_ms = round((time.monotonic() - started_at) * 1000, 2)
    response.headers[REQUEST_ID_HEADER] = request_id
    logger.info(
        "request_completed request_id=%s method=%s path=%s status=%s latency_ms=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        latency_ms,
    )
    return response
