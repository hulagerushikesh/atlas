"""POST/GET /keys and PATCH /keys/{id} — key lifecycle; GET /usage — per-key stats."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from atlas.api import auth as auth_db
from atlas.api.keystore import KeyRecord
from atlas.api.schemas import (
    KeyActiveRequest,
    KeyCreateRequest,
    KeyCreateResponse,
    KeyListResponse,
    KeyRecordResponse,
    NamespaceUsage,
    UsageResponse,
)
from atlas.config import get_settings

router = APIRouter()


def _require_admin(x_admin_secret: str) -> None:
    """Guard the key-lifecycle routes.

    These are the only routes the Bearer middleware lets through unauthenticated
    (see `_PUBLIC_PATHS` / `_PUBLIC_PREFIXES` in auth_mw) — the first key could
    not otherwise be created. This header is therefore the whole guard, and an
    unset ADMIN_SECRET closes the routes rather than opening them.
    """
    settings = get_settings()
    if not settings.admin_secret or x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Admin-Secret header")


def _as_response(record: KeyRecord) -> KeyRecordResponse:
    return KeyRecordResponse(
        key_id=record.id,
        name=record.name,
        email=record.email,
        is_active=record.is_active,
        rate_limit_rpm=record.rate_limit_rpm,
        created_at=record.created_at,
        total_queries=record.total_queries,
        last_query_at=record.last_query_at,
    )


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
    _require_admin(x_admin_secret)

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


@router.get("/keys", response_model=KeyListResponse)
async def list_keys(
    x_admin_secret: str = Header("", alias="X-Admin-Secret"),
) -> KeyListResponse:
    """
    List every key the store holds, newest first, with its usage counters.

    No raw key and no hash of one is returned — `key_id` is a row id on SQLite
    and the document id on Firestore, which is what PATCH needs.
    """
    _require_admin(x_admin_secret)
    return KeyListResponse(keys=[_as_response(r) for r in await auth_db.list_keys()])


@router.patch("/keys/{key_id}", response_model=KeyRecordResponse)
async def set_key_active(
    key_id: str,
    body: KeyActiveRequest,
    x_admin_secret: str = Header("", alias="X-Admin-Secret"),
) -> KeyRecordResponse:
    """
    Revoke (`is_active: false`) or restore (`is_active: true`) a key.

    Revocation is immediate and reversible: `lookup_key` returns None for an
    inactive key from the next request onward, and nothing caches the result.
    Reversible on purpose — the alternative to a restore is hand-editing the
    production key store, which is how this field came to have no writer.
    """
    _require_admin(x_admin_secret)
    record = await auth_db.set_key_active(key_id, body.is_active)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No key with id {key_id!r}")
    return _as_response(record)


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
