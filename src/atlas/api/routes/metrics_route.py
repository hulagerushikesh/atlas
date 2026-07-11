"""GET /metrics — Prometheus exposition format."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter()


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> PlainTextResponse:
    """Expose Prometheus metrics in text exposition format."""
    return PlainTextResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )
