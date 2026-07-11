"""GET /health — liveness and dependency health check."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from atlas import __version__
from atlas.api.schemas import ComponentHealth, HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> JSONResponse:
    """
    Return the health of the API and its upstream dependencies.

    We probe Qdrant and Redis with a lightweight ping rather than a full query.
    This endpoint is used by the docker-compose healthcheck and load balancer
    probes — it must remain fast (<500ms) and must not trigger LLM calls.
    """
    components: dict[str, ComponentHealth] = {}

    # Qdrant probe
    try:
        state = request.app.state.atlas
        qdrant_client = state.pipeline._retriever._retrievers[0]._client  # type: ignore[attr-defined]
        t = time.perf_counter()
        await qdrant_client.get_collections()
        components["qdrant"] = ComponentHealth(
            status="ok",
            latency_ms=round((time.perf_counter() - t) * 1000, 1),
        )
    except Exception as exc:
        components["qdrant"] = ComponentHealth(status="down", detail=str(exc))

    # Redis probe
    try:
        cache = request.app.state.atlas.cache
        if cache._redis is not None:
            t = time.perf_counter()
            await cache._redis.ping()
            components["redis"] = ComponentHealth(
                status="ok",
                latency_ms=round((time.perf_counter() - t) * 1000, 1),
            )
        else:
            components["redis"] = ComponentHealth(status="ok", detail="disabled")
    except Exception as exc:
        components["redis"] = ComponentHealth(status="degraded", detail=str(exc))

    overall = (
        "ok"
        if all(c.status == "ok" for c in components.values())
        else "degraded"
        if any(c.status == "degraded" for c in components.values())
        else "down"
    )

    return JSONResponse(
        content=HealthResponse(
            status=overall,
            version=__version__,
            components=components,
        ).model_dump(),
        status_code=200 if overall != "down" else 503,
    )
