"""POST /keys — create API keys; GET /usage — per-key usage stats."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from atlas.api import auth as auth_db
from atlas.api.schemas import KeyCreateRequest, KeyCreateResponse, NamespaceUsage, UsageResponse
from atlas.config import get_settings

router = APIRouter()


@router.post("/keys", response_model=KeyCreateResponse, status_code=201)
async def create_key(
    body: KeyCreateRequest,
    x_admin_secret: str = Header("", alias="X-Admin-Secret"),
) -> KeyCreateResponse:
    """
    Create a new API key.

    Requires the X-Admin-Secret header to match ADMIN_SECRET in settings.
    The raw key is returned once — it is not stored and cannot be retrieved again.
    """
    settings = get_settings()
    if not settings.admin_secret or x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Admin-Secret header")

    raw_key, key_id = await auth_db.create_key(
        name=body.name,
        email=body.email,
        rate_limit_rpm=body.rate_limit_rpm,
    )
    return KeyCreateResponse(
        key=raw_key,
        key_id=key_id,
        name=body.name,
        rate_limit_rpm=body.rate_limit_rpm,
    )


@router.get("/usage", response_model=UsageResponse)
async def get_usage(request: Request) -> UsageResponse:
    """
    Return aggregated usage stats for the authenticated API key.

    Requires AUTH_ENABLED=true and a valid Bearer token.
    Returns zeros when auth is disabled (no key ID in request state).
    """
    key_id = getattr(request.state, "api_key_id", None)
    if key_id is None:
        return UsageResponse(
            total_queries=0, cache_hits=0, total_prompt_tokens=0,
            total_completion_tokens=0, avg_latency_ms=0.0,
            first_query_at=None, last_query_at=None, by_namespace=[],
        )

    stats = await auth_db.get_usage_stats(key_id)
    return UsageResponse(
        total_queries=stats["total_queries"],
        cache_hits=stats["cache_hits"],
        total_prompt_tokens=stats["total_prompt_tokens"],
        total_completion_tokens=stats["total_completion_tokens"],
        avg_latency_ms=stats["avg_latency_ms"],
        first_query_at=stats["first_query_at"],
        last_query_at=stats["last_query_at"],
        by_namespace=[NamespaceUsage(**ns) for ns in stats["by_namespace"]],
    )
