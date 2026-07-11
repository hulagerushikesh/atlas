"""
Per-request tracing middleware.

Design rationale:
    Every log line emitted during a request carries a request_id so that all
    stages of the pipeline (routing, retrieval, grading, generation) can be
    correlated in a log aggregator without any plumbing in the business logic.

    We use structlog's contextvars integration: bind_contextvars() sets values
    in a thread-local (or asyncio-task-local) dict that structlog's
    merge_contextvars processor appends to every log record. This is the
    recommended pattern for async FastAPI applications — it doesn't require
    passing a logger or request object through every function call.

    Timing: we record X-Request-ID and X-Response-Time as response headers so
    clients and load balancers can correlate requests without log access. The
    header values are also emitted in the final structured log line so they
    appear in the aggregator alongside all stage-level logs for the request.

    We use a simple uuid4 for request IDs rather than a distributed trace ID
    (OpenTelemetry W3C trace-context format) because Atlas doesn't yet have
    a tracing backend configured. The format is easy to upgrade later: replace
    the uuid4 with an otel.generate_trace_id() call.
"""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)


class TracingMiddleware(BaseHTTPMiddleware):
    """Attach request_id and timing to every request; emit a completion log."""

    async def dispatch(self, request: Request, call_next: object) -> Response:
        request_id = str(uuid.uuid4())
        start = time.perf_counter()

        # Bind to structlog context — visible in ALL log lines for this request
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        try:
            response: Response = await call_next(request)  # type: ignore[operator]
        except Exception:
            structlog.contextvars.unbind_contextvars("request_id", "method", "path")
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"

        logger.info(
            "request_complete",
            status_code=response.status_code,
            duration_ms=round(duration_ms, 1),
        )
        structlog.contextvars.unbind_contextvars("request_id", "method", "path")
        return response
