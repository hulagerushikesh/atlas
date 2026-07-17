"""
FastAPI application factory.

Design rationale:
    create_app() is a factory (not a module-level singleton) so tests can
    construct a fresh app with overridden settings without monkey-patching
    globals. The test client pattern is:

        app = create_app(settings=Settings(openai={"api_key": "sk-test"}))
        client = TestClient(app)

    Lifespan handler:
    All I/O-bound component construction (Qdrant client, Redis, model loading)
    happens in the lifespan async context manager — not at import time. This
    ensures:
      1. Import is cheap (no network calls).
      2. Components are shut down gracefully on SIGTERM.
      3. Tests that don't need the full stack can mock app.state.atlas.

    Middleware registration order matters in Starlette: middleware is applied
    in reverse registration order (last registered = outermost layer).
    We register PrometheusMiddleware last so it wraps everything, including
    the TracingMiddleware, and records the true end-to-end latency.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from atlas import __version__
from atlas.api.cache import QueryCache
from atlas.api.dependencies import AppState
from atlas.api.middleware.auth_mw import APIKeyMiddleware
from atlas.api.middleware.metrics_mw import PrometheusMiddleware
from atlas.api.middleware.tracing import TracingMiddleware
from atlas.api.namespaces import NamespaceRegistry, SharedComponents
from atlas.api.routes import health, ingest, keys, query, metrics_route, namespaces
from atlas.config import Settings, get_settings
from atlas.logging import configure_logging

logger = structlog.get_logger(__name__)



@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state._settings  # type: ignore[attr-defined]
    configure_logging(level=settings.log_level, json=True)

    logger.info("atlas_startup", version=__version__)

    # Sentry (optional — only initialised when SENTRY_DSN is set)
    if settings.sentry_dsn:
        try:
            import sentry_sdk
            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                traces_sample_rate=0.1,
                environment="production",
                release=f"atlas@{__version__}",
            )
            logger.info("sentry_enabled")
        except ImportError:
            logger.warning("sentry_sdk_not_installed", detail="pip install sentry-sdk to enable")

    # Initialise auth DB (creates tables if first run)
    from atlas.api.auth import init_db
    await init_db()

    # Build shared (cross-namespace) components once
    shared = SharedComponents(settings)
    registry = NamespaceRegistry(shared)

    # Redis (optional — gracefully skip if not configured)
    redis_client = None
    try:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(
            settings.redis.url, encoding="utf-8", decode_responses=True
        )
        await redis_client.ping()
        logger.info("redis_connected", url=settings.redis.url)
    except Exception as exc:
        logger.warning("redis_unavailable", error=str(exc), detail="running without Redis cache")

    app.state.atlas = AppState(
        registry=registry,
        cache=QueryCache(
            redis_client=redis_client,
            ttl_seconds=settings.redis.cache_ttl_seconds,
        ),
        embedding_model=shared.settings.openai.embedding_model,
    )

    logger.info("atlas_ready")
    yield

    # Shutdown
    if redis_client is not None:
        await redis_client.aclose()
    logger.info("atlas_shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct and configure the FastAPI application."""
    cfg = settings or get_settings()

    app = FastAPI(
        title="Atlas",
        description="Production-grade agentic RAG platform",
        version=__version__,
        lifespan=_lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state._settings = cfg

    # Middleware (last registered = outermost)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TracingMiddleware)
    app.add_middleware(PrometheusMiddleware)
    app.add_middleware(APIKeyMiddleware, enabled=cfg.auth_enabled)

    # Landing page at /
    import pathlib as _pl
    _web_index = _pl.Path(__file__).parent / "web" / "index.html"
    if _web_index.exists():
        _landing_html = _web_index.read_text()

        async def _landing() -> HTMLResponse:
            return HTMLResponse(content=_landing_html)

        app.add_api_route("/", _landing, include_in_schema=False, response_class=HTMLResponse)

    # Routes
    app.include_router(health.router, tags=["ops"])
    app.include_router(metrics_route.router, tags=["ops"])
    app.include_router(namespaces.router, tags=["namespaces"])
    app.include_router(keys.router, tags=["auth"])
    app.include_router(ingest.router, tags=["ingestion"])
    app.include_router(query.router, tags=["query"])

    # Static console — served at /app (must come after API routes)
    import pathlib
    _static_dir = pathlib.Path(__file__).parent / "static"
    if _static_dir.is_dir():
        app.mount("/app", StaticFiles(directory=str(_static_dir), html=True), name="console")

    # Eval reports — served at /out so the console dashboard can load eval_report.json
    _out_dir = pathlib.Path(__file__).parent.parent.parent.parent / "out"
    if _out_dir.is_dir():
        app.mount("/out", StaticFiles(directory=str(_out_dir)), name="out")

    return app


