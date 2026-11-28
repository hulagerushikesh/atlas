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

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

from atlas import __version__
from atlas.api import mcp_server
from atlas.api.audit import AuditMiddleware
from atlas.api.background import drain
from atlas.api.budget import SpendMeter
from atlas.api.cache import QueryCache
from atlas.api.dependencies import AppState
from atlas.api.middleware.auth_mw import APIKeyMiddleware
from atlas.api.middleware.metrics_mw import PrometheusMiddleware
from atlas.api.middleware.tracing import TracingMiddleware
from atlas.api.namespaces import NamespaceRegistry, SharedComponents
from atlas.api.reuse import EvidenceReuse
from atlas.api.routes import (
    auth,
    connectors,
    documents,
    health,
    ingest,
    keys,
    me,
    metrics_route,
    namespaces,
    org,
    query,
)
from atlas.api.sessions import SignIn
from atlas.api.spendstore import build_spend_backend
from atlas.config import Settings, get_settings
from atlas.logging import configure_logging

logger = structlog.get_logger(__name__)



async def connect_redis(settings: Settings) -> object | None:
    """
    Return a live Redis client, or None when Redis is absent.

    REDIS_URL="" means deliberately absent: Cloud Run runs without Redis and
    the in-process cache, rate limiter and spend counter are the design there,
    not a degraded mode. A client that fails its ping is discarded rather than
    handed on — keeping it makes every cache get/set raise and pins /health at
    "degraded" for the life of the process.
    """
    if not settings.redis.url:
        logger.info("redis_disabled", detail="REDIS_URL empty; using in-process fallbacks")
        return None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis.url, encoding="utf-8", decode_responses=True)
        await client.ping()
    except Exception as exc:
        logger.warning("redis_unavailable", error=str(exc), detail="running without Redis cache")
        return None
    logger.info("redis_connected", url=settings.redis.url)
    return client


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state._settings
    configure_logging(level=settings.log_level, json=True, log_questions=settings.log_questions)

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
    from atlas.api import auth as auth_db
    auth_db.configure_store(
        settings.auth_store, firestore_project=settings.auth_firestore_project or None
    )
    await auth_db.init_db()
    from atlas.api import tenancy
    await tenancy.configure_tenancy(
        settings.auth_store, firestore_project=settings.auth_firestore_project or None
    ).init()

    # Build shared (cross-namespace) components once
    shared = SharedComponents(settings)
    registry = NamespaceRegistry(shared)

    redis_client = await connect_redis(settings)
    spend = SpendMeter(
        budget_usd=settings.budget.daily_usd,
        backend=build_spend_backend(
            settings.budget.store,
            redis_client=redis_client,
            firestore_project=settings.auth_firestore_project or None,
        ),
    )
    demo_on = bool(settings.budget.demo_namespace) and settings.budget.demo_usd > 0

    app.state.atlas = AppState(
        registry=registry,
        cache=QueryCache(
            redis_client=redis_client,
            ttl_seconds=settings.redis.cache_ttl_seconds,
        ),
        embedding_model=shared.settings.openai.embedding_model,
        chat_model=shared.settings.openai.primary_model,
        ingest=settings.ingest,
        drive=settings.drive,
        reuse=EvidenceReuse(shared.embedder, shared.llm, settings.reuse)
        if settings.reuse.enabled else None,
        spend=spend,
        demo_namespace=settings.budget.demo_namespace if demo_on else "",
        demo_spend=SpendMeter(
            budget_usd=settings.budget.demo_usd, backend=spend.backend,
            scope="demo", parent=spend,
        ) if demo_on else None,
    )
    if settings.budget.daily_usd > 0:
        logger.info("daily_budget_enabled", usd=settings.budget.daily_usd)
    if demo_on:
        logger.info("keyless_demo_enabled", namespace=settings.budget.demo_namespace,
                    usd=settings.budget.demo_usd, rpm=settings.budget.demo_rpm)

    # Load the cross-encoder behind the server rather than in front of it.
    # The import alone is 12.41 s of a 36.9 s cold start, and only /query
    # needs it: the landing page, the console and /health do not. Held on
    # app.state so the task is not garbage collected mid-load, which is the
    # documented way a bare create_task disappears.
    #
    # This finishes under docker-compose and on any host with continuously
    # allocated CPU. On Cloud Run as configured it cannot finish on its own:
    # the service uses the default request-scoped CPU allocation, so this
    # thread only advances while the instance happens to be serving
    # something. Rev atlas-api-00018-zfc went three minutes and two /health
    # pings without logging `reranker_loaded_lazily`; rev
    # atlas-api-00020-pcg then logged it at 54.1s wall, of which 37.0s was
    # one `/warm` request holding the instance awake — the task had been
    # running for seventeen seconds before that and had got nowhere.
    # So it is not dead weight, it is a head start that needs traffic to
    # cash in. `/warm` is what guarantees the load; `atlas-keepwarm` calls
    # it every ten minutes.
    warm_task: asyncio.Task[None] | None = None
    if shared.reranker is not None:
        warm_task = asyncio.create_task(shared.reranker.warm())
    app.state.reranker_warm_task = warm_task

    logger.info("atlas_ready")
    # E4: the MCP endpoint's session manager lives as long as the app.
    async with app.state.mcp.session_manager.run():
        yield
    if warm_task is not None and not warm_task.done():
        # Shutdown should not wait on a model nobody is going to use.
        warm_task.cancel()

    # Shutdown
    #
    # Before closing anything the un-awaited writes still need: the per-key
    # usage records and the cache writes `/query` deliberately keeps off the
    # response path. Dropping those is how a scale-in during a burst
    # under-counts exactly the traffic worth counting, and BUDGET.md's
    # `cost / query` is read off those counters. Bounded, because Cloud Run
    # gives ten seconds between SIGTERM and SIGKILL and the redis close is
    # still to come.
    await drain()

    if redis_client is not None:
        await redis_client.aclose()  # type: ignore[attr-defined]
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
    # Inside the key middleware, so each entry knows who made the request.
    app.add_middleware(AuditMiddleware)
    app.add_middleware(APIKeyMiddleware, enabled=cfg.auth_enabled, demo_rpm=cfg.budget.demo_rpm,
                       session_secret=cfg.session_secret)
    # Sign-in needs the key middleware to read its cookie, so it is on only
    # with auth on as well.
    app.state.sign_in = SignIn.from_settings(
        cfg.google_client_id if cfg.auth_enabled else "", cfg.session_secret)

    # Landing page at /
    import pathlib as _pl
    # Built by the console's Vite multi-page build; see console/landing.html.
    _web_index = _pl.Path(__file__).parent / "static" / "landing.html"
    if _web_index.exists():
        _landing_html = _web_index.read_text()

        async def _landing() -> HTMLResponse:
            # The page references content-hashed assets; a cached copy of
            # this HTML after a rebuild would point at files that no longer
            # exist. Revalidate every time — the body is tiny.
            return HTMLResponse(content=_landing_html, headers={"Cache-Control": "no-cache"})

        app.add_api_route("/", _landing, include_in_schema=False, response_class=HTMLResponse)

    # The privacy page Google's sign-in screen links to. Same build, same
    # no-cache reason as the landing page.
    _privacy_index = _pl.Path(__file__).parent / "static" / "privacy.html"
    if _privacy_index.exists():
        _privacy_html = _privacy_index.read_text()

        async def _privacy() -> HTMLResponse:
            return HTMLResponse(content=_privacy_html, headers={"Cache-Control": "no-cache"})

        app.add_api_route("/privacy", _privacy, include_in_schema=False,
                          response_class=HTMLResponse)

    # Routes
    app.include_router(health.router, tags=["ops"])
    app.include_router(metrics_route.router, tags=["ops"])
    app.include_router(namespaces.router, tags=["namespaces"])
    app.include_router(keys.router, tags=["auth"])
    app.include_router(auth.router, tags=["auth"])
    app.include_router(org.router, tags=["organisation"])
    app.include_router(ingest.router, tags=["ingestion"])
    app.include_router(documents.router, tags=["ingestion"])
    app.include_router(connectors.router, tags=["connectors"])
    app.include_router(query.router, tags=["query"])
    app.include_router(me.router, tags=["auth"])

    # E4: Atlas as an MCP server, for the AI assistants people already use.
    app.state.mcp, mcp_app = mcp_server.build()
    app.router.routes.append(Route("/mcp", endpoint=mcp_app, methods=["GET", "POST", "DELETE"]))

    # Static console — served at /app (must come after API routes)
    import pathlib
    _static_dir = pathlib.Path(__file__).parent / "static"
    if _static_dir.is_dir():
        _console_index = _static_dir / "index.html"
        if _console_index.exists():
            _console_html = _console_index.read_text()

            async def _console() -> HTMLResponse:
                # Serve /app directly instead of letting the mount redirect to
                # /app/. Starlette builds that redirect from the request's own
                # host, which behind the domain proxy is the run.app origin —
                # the browser would leave atlas.hulage.in mid-click.
                return HTMLResponse(content=_console_html, headers={"Cache-Control": "no-cache"})

            app.add_api_route(
                "/app", _console, include_in_schema=False, response_class=HTMLResponse
            )
        app.mount("/app", StaticFiles(directory=str(_static_dir), html=True), name="console")

    # Eval reports — served at /out so the console dashboard can load eval_report.json
    _out_dir = pathlib.Path(__file__).parent.parent.parent.parent / "out"
    if _out_dir.is_dir():
        app.mount("/out", StaticFiles(directory=str(_out_dir)), name="out")

    return app


