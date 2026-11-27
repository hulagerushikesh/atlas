"""
A sheet's Drive connection: who connected it, which folder, the sealed
refresh token, and what the last sync did (E3.1).

Stored as a tenancy record (kind "drive", key = workspace id), so SQLite on
the laptop and Firestore live need no new schema. The refresh token is
sealed with Fernet under DRIVE_TOKEN_KEY before it is stored and is never
returned by any route or written to a log.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import time
from typing import Any

import structlog
from cryptography.fernet import Fernet, InvalidToken

from atlas.api import tenancy

logger = structlog.get_logger(__name__)

KIND = "drive"
GROUP_LINK = "google_group"


def seal(token: str, key: str) -> str:
    return Fernet(key.encode()).encrypt(token.encode()).decode()


def unseal(sealed: str, key: str) -> str | None:
    try:
        return Fernet(key.encode()).decrypt(sealed.encode()).decode()
    except (InvalidToken, ValueError):
        return None


# ── OAuth state: which sheet and which person a consent belongs to ────────────

def _mac(secret: str, payload: str) -> str:
    digest = hmac.new(secret.encode(), f"drive-state:{payload}".encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode()


def sign_state(workspace_id: str, user_id: str, secret: str, *,
               now: float | None = None, seconds: int = 600) -> str:
    expires = int((now if now is not None else time.time()) + seconds)
    payload = f"{workspace_id}.{user_id}.{expires}"
    return f"{payload}.{_mac(secret, payload)}"


def read_state(state: str, secret: str, *, now: float | None = None) -> tuple[str, str] | None:
    """(workspace id, user id) from a state Atlas signed in the last 10 minutes."""
    parts = state.split(".")
    if len(parts) != 4 or not secret:
        return None
    payload = ".".join(parts[:3])
    if not hmac.compare_digest(parts[3], _mac(secret, payload)):
        return None
    try:
        if int(parts[2]) <= (now if now is not None else time.time()):
            return None
    except ValueError:
        return None
    return parts[0], parts[1]


# ── Records ───────────────────────────────────────────────────────────────────

async def get(workspace_id: str) -> dict[str, Any] | None:
    return await tenancy.get_tenancy().get_record(KIND, workspace_id)


async def put(record: dict[str, Any]) -> None:
    await tenancy.get_tenancy().put_record(KIND, record["workspace_id"], record["org_id"],
                                           record)


async def delete(workspace_id: str) -> None:
    await tenancy.get_tenancy().delete_record(KIND, workspace_id)


async def all_connections() -> list[dict[str, Any]]:
    return await tenancy.get_tenancy().list_records(KIND)


def public_view(record: dict[str, Any] | None) -> dict[str, Any]:
    """What a route may show: never the token."""
    if record is None:
        return {"connected": False}
    return {
        "connected": bool(record.get("token")),
        "folder_id": record.get("folder_id", ""),
        "connected_by": record.get("connected_by_email", ""),
        "last_sync": record.get("last_sync"),
        "last_check": record.get("last_check"),
        "syncing": bool(record.get("syncing")),
        "files": len(record.get("files") or {}),
        "report": record.get("report") or {},
        "error": record.get("error", ""),
    }


async def group_links(org_id: str) -> dict[str, str]:
    """Google Group address -> Atlas group id, for one organisation."""
    rows = await tenancy.get_tenancy().list_records(GROUP_LINK, org_id)
    return {r["email"]: r["group_id"] for r in rows if r.get("group_id")}


async def link_group(org_id: str, email: str, group_id: str | None) -> None:
    key = f"{org_id}:{email}"
    store = tenancy.get_tenancy()
    if group_id is None:
        await store.delete_record(GROUP_LINK, key)
    else:
        await store.put_record(GROUP_LINK, key, org_id,
                               {"email": email, "group_id": group_id, "org_id": org_id})


# One sync per sheet at a time on this server; a second request waits.
_locks: dict[str, asyncio.Lock] = {}


def lock_for(workspace_id: str) -> asyncio.Lock:
    return _locks.setdefault(workspace_id, asyncio.Lock())
