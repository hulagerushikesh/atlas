"""
API key authentication middleware.

Reads the Authorization: Bearer <key> header, validates against the SQLite
store, checks rate limits, and attaches the key record to request.state.

Auth is bypassed when AUTH_ENABLED=false (the default) so the dev experience
requires no keys. When enabled, the following paths are always public:
  /health, /docs, /redoc, /openapi.json, /metrics, /, /app/*, /out/*
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from atlas.api import auth as auth_db

_PUBLIC_PATHS = {"/health", "/docs", "/redoc", "/openapi.json", "/metrics", "/"}
_PUBLIC_PREFIXES = ("/app", "/out", "/namespaces")


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validate Bearer tokens and enforce per-key rate limits."""

    def __init__(self, app, *, enabled: bool) -> None:
        super().__init__(app)
        self._enabled = enabled

    async def dispatch(self, request: Request, call_next):
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
        try:
            redis_client = request.app.state.atlas.cache._redis  # type: ignore[attr-defined]
        except AttributeError:
            pass

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
