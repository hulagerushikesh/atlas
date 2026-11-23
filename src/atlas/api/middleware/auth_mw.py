"""
API key authentication middleware.

Reads the Authorization: Bearer <key> header, validates against the SQLite
store, checks rate limits, and attaches the key record and the principal
(atlas.api.tenancy) to request.state.

Auth is bypassed when AUTH_ENABLED=false (the default) so the dev experience
requires no keys. With a keyless demo sheet configured (BUDGET_DEMO_*), a
POST /query with no Authorization header is let through, rate-limited per
visitor; the route confines it to that sheet and its own daily cap. Keyless
GET /namespaces and /namespaces/{ns}/sources are let through the same way, so
the console can show a visitor the demo sheet; the visitor's principal reads
that sheet only, so the listing shows nothing else.

Which paths are public is `authz.POLICY`'s decision, not this file's. /keys
is there because it is guarded by X-Admin-Secret and must be reachable before
the first key exists; /warm because `atlas-keepwarm` calls it without a key
(it makes no model calls and cannot spend).

A signed session cookie (atlas.api.sessions, set by POST /auth/google) is
read first: the principal is the person's, read from the store on every
request, limited to 60 a minute, and a cookie-carrying write must also carry
the console's X-Requested-With header.

A tenancy store that cannot be read answers 503: the caller's access cannot
be known, and guessing would hand an organisation's key the public one.
"""

from __future__ import annotations

import contextlib
from typing import Any

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from atlas.api import auth as auth_db
from atlas.api import sessions, tenancy
from atlas.api.authz import is_public

# A caller on a public path, before or without a key. Not legacy: it can
# reach no workspace.
_PUBLIC_CALLER = tenancy.Principal(kind="anonymous")

# Keyless browsing of the demo sheet's listing. Cheap (no model call) but it
# reads Qdrant, so it is limited too, separately from questions.
_DEMO_BROWSE_RPM = 30

# A signed-in person, the same default a new API key gets.
_USER_RPM = 60
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _unavailable() -> JSONResponse:
    return JSONResponse(
        {"error": "Access check unavailable",
         "detail": "Atlas could not check your access just now. Try again shortly."},
        status_code=503, headers={"Retry-After": "5"},
    )


def _bind(principal: tenancy.Principal) -> None:
    # On every log line of the request, so E4's audit can be built from them.
    structlog.contextvars.bind_contextvars(
        principal_kind=principal.kind, org_id=principal.home_org or None,
    )


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validate Bearer tokens and enforce per-key rate limits."""

    def __init__(self, app: ASGIApp, *, enabled: bool, demo_rpm: int = 3,
                 session_secret: str = "") -> None:
        super().__init__(app)
        self._enabled = enabled
        self._demo_rpm = demo_rpm
        self._session_secret = session_secret

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._enabled:
            request.state.principal = tenancy.ANONYMOUS
            return await call_next(request)

        if is_public(request.url.path):
            request.state.principal = _PUBLIC_CALLER
            return await call_next(request)

        # Use Redis from app cache if available for distributed rate limiting
        redis_client = None
        with contextlib.suppress(AttributeError):
            redis_client = request.app.state.atlas.cache._redis

        # A signed-in person. Checked before the Bearer header: a browser that
        # also holds an old key in its settings acts as the person signed in.
        user_id = sessions.read_session(request.cookies.get(sessions.COOKIE, ""),
                                        self._session_secret)
        if user_id:
            return await self._admit_user(request, call_next, user_id, redis_client)

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
        try:
            principal = await tenancy.principal_for_key(api_key.id)
        except tenancy.TenancyUnavailable:
            return _unavailable()
        request.state.principal = principal
        _bind(principal)
        return await call_next(request)

    async def _admit_user(
        self, request: Request, call_next: RequestResponseEndpoint, user_id: str,
        redis_client: Any,
    ) -> Response:
        # The cookie rides along on any request to this site, including one a
        # form on another site makes; a write must also carry the header only
        # the console sends.
        if (request.method not in _SAFE_METHODS
                and request.headers.get(sessions.CSRF_HEADER) != sessions.CSRF_VALUE):
            return JSONResponse(
                {"error": "Missing request header",
                 "detail": {"code": "csrf", "message": "This request did not come from Atlas."}},
                status_code=403,
            )
        try:
            principal = await tenancy.principal_for_user(user_id)
        except tenancy.TenancyUnavailable:
            return _unavailable()
        if principal is None:
            # Removed since the cookie was issued: signed out, not forbidden.
            response = JSONResponse(
                {"error": "Signed out",
                 "detail": {"code": "signed_out",
                            "message": "This account no longer has access to Atlas."}},
                status_code=401,
            )
            response.delete_cookie(sessions.COOKIE, path="/")
            return response
        if not await auth_db.check_rate_limit(f"user:{user_id}", _USER_RPM, redis_client):
            return JSONResponse(
                {"error": "Rate limit exceeded", "detail": f"Limit: {_USER_RPM} rpm"},
                status_code=429, headers={"Retry-After": "60"},
            )
        request.state.user_id = user_id
        request.state.principal = principal
        _bind(principal)
        return await call_next(request)

    async def _admit_demo(
        self, request: Request, call_next: RequestResponseEndpoint, redis_client: Any
    ) -> Response:
        # A keyless question. The route keeps it to the demo sheet and charges
        # it to the demo cap; this only limits how fast one visitor can ask.
        ip = _client_ip(request)
        asking = request.method == "POST"
        bucket, rpm = (f"demo:{ip}", self._demo_rpm) if asking else (
            f"demo-browse:{ip}", _DEMO_BROWSE_RPM)
        if not await auth_db.check_rate_limit(bucket, rpm, redis_client):
            what = "ask" if asking else "open"
            noun = "questions" if asking else "listings"
            return JSONResponse(
                {"error": "Rate limit exceeded", "detail": {
                    "code": "demo_rate",
                    "message": f"Without a key, each visitor can {what} {rpm} {noun} a minute.",
                }},
                status_code=429,
                headers={"Retry-After": "60"},
            )
        request.state.demo = True
        demo_ns = getattr(request.app.state.atlas, "demo_namespace", "")
        try:
            principal = await tenancy.principal_for_visitor(f"demo:{ip}", demo_ns)
        except tenancy.TenancyUnavailable:
            return _unavailable()
        request.state.principal = principal
        _bind(principal)
        return await call_next(request)


def _demo_open(request: Request) -> bool:
    path = request.url.path
    asks = request.method == "POST" and path == "/query"
    browses = request.method == "GET" and (path == "/namespaces"
                                           or path.startswith("/namespaces/"))
    if not (asks or browses):
        return False
    state = getattr(request.app.state, "atlas", None)
    return bool(getattr(state, "demo_namespace", ""))


def _client_ip(request: Request) -> str:
    # Vercel overwrites X-Forwarded-For with the visitor's address and Cloud
    # Run appends its own hop, so the first entry is the visitor. A caller
    # hitting run.app directly can forge it; the daily demo cap still holds.
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")
