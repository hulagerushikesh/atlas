"""
API key authentication middleware.

Reads the Authorization: Bearer <key> header, validates against the SQLite
store, checks rate limits, and attaches the key record to request.state.

Auth is bypassed when AUTH_ENABLED=false (the default) so the dev experience
requires no keys. With a keyless demo sheet configured (BUDGET_DEMO_*), a
POST /query with no Authorization header is let through, rate-limited per
visitor; the route confines it to that sheet and its own daily cap.
When enabled, the following paths are always public:
  /health, /warm, /docs, /redoc, /openapi.json, /metrics, /, /app/*, /out/*
"""

from __future__ import annotations

import contextlib
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from atlas.api import auth as auth_db

# /keys is guarded by X-Admin-Secret, not a Bearer key — it has to be reachable
# before the first key exists.
#
# /warm is public for the same reason /health is: `atlas-keepwarm` calls it
# unauthenticated every ten minutes, and it was added to the allowlist only
# after production answered it 401 — the endpoint existed and could not be
# reached by the one caller it was written for. It makes no model calls and
# cannot spend: the worst an anonymous caller achieves is loading a
# cross-encoder that the next request would have loaded anyway, and every
# call after that returns immediately.
_PUBLIC_PATHS = {
    "/health", "/warm", "/docs", "/redoc", "/openapi.json", "/metrics", "/", "/keys",
}
# "/keys/" covers the per-key admin routes (listing is on "/keys" itself).
# Every route under it checks X-Admin-Secret, which is the guard — a new route
# added here without that check would be open to anyone.
_PUBLIC_PREFIXES = ("/app", "/out", "/namespaces", "/keys/")


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validate Bearer tokens and enforce per-key rate limits."""

    def __init__(self, app: ASGIApp, *, enabled: bool, demo_rpm: int = 3) -> None:
        super().__init__(app)
        self._enabled = enabled
        self._demo_rpm = demo_rpm

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._enabled:
            return await call_next(request)

        path = request.url.path
        if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        # Use Redis from app cache if available for distributed rate limiting
        redis_client = None
        with contextlib.suppress(AttributeError):
            redis_client = request.app.state.atlas.cache._redis

        auth_header = request.headers.get("Authorization", "")
        if not auth_header and _demo_open(request):
            return await self._admit_demo(request, call_next, redis_client)
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"error": "Missing API key", "detail": "Provide Authorization: Bearer <key>"},
                status_code=401,
            )

        raw_key = auth_header[7:].strip()
        api_key = await auth_db.lookup_key(raw_key)
        if api_key is None:
            return JSONResponse(
                {"error": "Invalid or inactive API key"},
                status_code=401,
            )

        allowed = await auth_db.check_rate_limit(api_key.id, api_key.rate_limit_rpm, redis_client)
        if not allowed:
            return JSONResponse(
                {"error": "Rate limit exceeded", "detail": f"Limit: {api_key.rate_limit_rpm} rpm"},
                status_code=429,
                headers={"Retry-After": "60"},
            )

        request.state.api_key_id = api_key.id
        request.state.api_key_name = api_key.name
        return await call_next(request)

    async def _admit_demo(
        self, request: Request, call_next: RequestResponseEndpoint, redis_client: Any
    ) -> Response:
        # A keyless question. The route keeps it to the demo sheet and charges
        # it to the demo cap; this only limits how fast one visitor can ask.
        visitor = f"demo:{_client_ip(request)}"
        if not await auth_db.check_rate_limit(visitor, self._demo_rpm, redis_client):
            return JSONResponse(
                {"error": "Rate limit exceeded", "detail": {
                    "code": "demo_rate",
                    "message": f"Without a key, each visitor can ask {self._demo_rpm} "
                               "questions a minute.",
                }},
                status_code=429,
                headers={"Retry-After": "60"},
            )
        request.state.demo = True
        return await call_next(request)


def _demo_open(request: Request) -> bool:
    if request.method != "POST" or request.url.path != "/query":
        return False
    state = getattr(request.app.state, "atlas", None)
    return bool(getattr(state, "demo_namespace", ""))


def _client_ip(request: Request) -> str:
    # Vercel overwrites X-Forwarded-For with the visitor's address and Cloud
    # Run appends its own hop, so the first entry is the visitor. A caller
    # hitting run.app directly can forge it; the daily demo cap still holds.
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")
