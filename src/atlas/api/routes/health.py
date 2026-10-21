"""GET /health — liveness and dependency health check."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from atlas import __version__
from atlas.api.schemas import BudgetStatus, ComponentHealth, HealthResponse

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

    # Qdrant probe — use the shared client on the registry
    try:
        qdrant_client = request.app.state.atlas.registry._shared.qdrant_client
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

    spend = request.app.state.atlas.spend
    budget = (
        BudgetStatus(
            daily_usd=spend.budget_usd,
            spent_today_usd=round(await spend.today_usd(), 6),
        )
        if spend.enabled
        else None
    )

    return JSONResponse(
        content=HealthResponse(
            status=overall,
            version=__version__,
            components=components,
            budget=budget,
        ).model_dump(),
        status_code=200 if overall != "down" else 503,
    )


@router.post("/warm", include_in_schema=False)
@router.get("/warm", include_in_schema=False)
async def warm(request: Request) -> JSONResponse:
    """Load the cross-encoder now, inside a request, and report what happened.

    This endpoint exists because of how Cloud Run allocates CPU. The service
    runs with the default request-scoped allocation — no
    `run.googleapis.com/cpu-throttling: false` — so a container gets CPU
    while it is handling a request and almost none between requests. The
    first attempt at deferring the reranker started the load as a background
    task from the lifespan, which is correct on a normal host and does not
    work here: rev `atlas-api-00018-zfc` served two `/health` pings in its
    first three minutes and never logged `reranker_loaded_lazily`, because
    the loading thread is frozen the moment each response is sent.

    Doing it inside a request is what makes the load finish: CPU is
    allocated for as long as the handler runs. `atlas-keepwarm` already
    pings every ten minutes, so pointing it here means a cold-started
    instance has its model within ten minutes without anyone waiting.

    What it costs is worth stating, because it is larger than it looks. On
    rev `atlas-api-00020-pcg` this handler blocked for 37.0s on the first
    call. The container has one vCPU and `startup-cpu-boost` only applies
    while the instance is starting, so a load moved off the startup path is
    a load that no longer gets the boost: the model costs ~37s here against
    the ~25s it cost inside the old 36.9s eager start. The landing page is
    up in 11s either way, which is the trade this endpoint exists to make,
    but an instance that takes a `/query` before anything has warmed it
    waits longer than it used to.

    It is not `/health`. A health check that blocks for twenty seconds once
    per cold start is a health check that trips alarms, and the two want
    opposite things from a slow dependency.
    """
    reranker = request.app.state.atlas.registry._shared.reranker
    if reranker is None:
        return JSONResponse({"reranker": "disabled"})

    already = reranker.is_loaded
    t = time.perf_counter()
    await reranker.warm()
    return JSONResponse({
        "reranker": "loaded" if reranker.is_loaded else "failed",
        "was_already_loaded": already,
        "seconds": round(time.perf_counter() - t, 2),
    })
