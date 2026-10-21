"""
API key authentication middleware.

Reads the Authorization: Bearer <key> header, validates against the SQLite
store, checks rate limits, and attaches the key record to request.state.

Auth is bypassed when AUTH_ENABLED=false (the default) so the dev experience
requires no keys. When enabled, the following paths are always public:
  /health, /warm, /docs, /redoc, /openapi.json, /metrics, /, /app/*, /out/*
"""

from __future__ import annotations

import contextlib

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
_PUBLIC_PREFIXES = ("/app", "/out", "/namespaces")


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validate Bearer tokens and enforce per-key rate limits."""

    def __init__(self, app: ASGIApp, *, enabled: bool) -> None:
        super().__init__(app)
        self._enabled = enabled

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._enabled:
            return await call_next(request)

        path = request.url.path
        if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
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

        # Use Redis from app cache if available for distributed rate limiting
        redis_client = None
        with contextlib.suppress(AttributeError):
            redis_client = request.app.state.atlas.cache._redis

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
