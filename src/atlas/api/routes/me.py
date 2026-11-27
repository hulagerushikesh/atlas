"""
A signed-in person's own keys, for AI assistants (E4).

    GET    /me/keys            the caller's live personal keys (never the key itself)
    POST   /me/keys            make one; the key is shown once
    DELETE /me/keys/{key_id}   revoke one

Signed-in people only, from the console: a key cannot mint another key, so a
leaked key cannot outlive its own revocation.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from atlas.api import personal_keys, tenancy
from atlas.api.authz import access_unavailable
from atlas.api.dependencies import get_principal

logger = structlog.get_logger(__name__)
router = APIRouter()


class PersonalKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80,
                      description="Where it will be used, e.g. 'Claude Code on my laptop'")


def _person(request: Request) -> tenancy.Principal:
    principal = get_principal(request)
    if principal.kind != "user" or getattr(request.state, "api_key_id", None) is not None:
        raise HTTPException(status_code=403, detail={
            "code": "sign_in_needed",
            "message": "Sign in to Atlas in the console to manage your keys."})
    return principal


def _view(r: dict[str, Any]) -> dict[str, Any]:
    return {"key_id": r["key_id"], "name": r.get("name", ""), "created_at": r.get("created_at")}


@router.get("/me/keys")
async def list_keys(request: Request) -> dict[str, Any]:
    person = _person(request)
    try:
        return {"keys": [_view(r) for r in await personal_keys.mine(person)]}
    except Exception as exc:
        raise access_unavailable() from exc


@router.post("/me/keys", status_code=201)
async def create_key(body: PersonalKeyRequest, request: Request) -> dict[str, Any]:
    person = _person(request)
    try:
        if len(await personal_keys.mine(person)) >= personal_keys.MAX_PER_PERSON:
            raise HTTPException(status_code=409, detail={
                "code": "too_many_keys",
                "message": f"You have {personal_keys.MAX_PER_PERSON} keys. Revoke one first."})
        raw, key_id = await personal_keys.create(person, body.name.strip())
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("personal_key_failed", error=str(exc))
        raise access_unavailable() from exc
    logger.info("personal_key_created", org_id=person.org_id)
    return {"key": raw, "key_id": key_id, "name": body.name.strip()}


@router.delete("/me/keys/{key_id}", status_code=204)
async def revoke_key(key_id: str, request: Request) -> Response:
    person = _person(request)
    try:
        found = await personal_keys.revoke(person, key_id)
    except Exception as exc:
        raise access_unavailable() from exc
    if not found:
        raise HTTPException(status_code=404, detail={
            "code": "key_not_found", "message": "No key of yours with that id."})
    logger.info("personal_key_revoked", org_id=person.org_id)
    return Response(status_code=204)
