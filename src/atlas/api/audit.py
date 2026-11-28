"""
The audit record (E4.1): who did what, when, on which sheet, kept for as long
as the organisation's retention setting says and then deleted.

One entry per request that changes something, plus every question asked (in
the console, by API or over MCP), whatever its outcome. Routes add what only
they know (the question, the document) with `note`; `AuditMiddleware` writes
the entry once the response is decided, off the response path.

Append-only: nothing in Atlas updates or deletes an entry; entries leave only
by expiry (SQLite: pruned on write; Firestore: a TTL policy). Only the
organisation's admins can read it, through `GET /org/audit`. Question text
lives here and not in the general logs (E4.2), so who may read it is decided
by one rule instead of by whoever can open Cloud Logging.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from atlas.api import tenancy
from atlas.api.background import spawn

logger = structlog.get_logger(__name__)

SETTINGS_KIND = "org_settings"
DEFAULT_RETENTION_DAYS = 90
MIN_RETENTION_DAYS, MAX_RETENTION_DAYS = 7, 3650
QUESTION_CHARS = 2000
_SAFE = {"GET", "HEAD", "OPTIONS"}
# Written by machines on a timer or before anyone is known: not activity.
_SKIP = {"/connectors/drive/tick", "/warm", "/auth/logout", "/mcp"}
_PRUNE_EVERY = 200

_retention: dict[str, tuple[int, float]] = {}   # org id -> (days, read at)
_writes = 0


def note(request: Request, action: str, **detail: Any) -> None:
    """Name this request's action and add what the middleware cannot see."""
    if isinstance(detail.get("question"), str):
        detail["question"] = detail["question"][:QUESTION_CHARS]
    request.state.audit = {"action": action, **detail}


async def retention_days(org_id: str) -> int:
    found = _retention.get(org_id)
    if found is not None and time.time() - found[1] < 60:
        return found[0]
    record = await tenancy.get_tenancy().get_record(SETTINGS_KIND, org_id) or {}
    days = int(record.get("audit_retention_days") or DEFAULT_RETENTION_DAYS)
    _retention[org_id] = (days, time.time())
    return days


async def set_retention_days(org_id: str, days: int) -> None:
    store = tenancy.get_tenancy()
    record = await store.get_record(SETTINGS_KIND, org_id) or {"org_id": org_id}
    record["audit_retention_days"] = days
    await store.put_record(SETTINGS_KIND, org_id, org_id, record)
    _retention.pop(org_id, None)


def _actor(request: Request, principal: tenancy.Principal) -> dict[str, Any]:
    actor: dict[str, Any] = {"kind": principal.kind, "id": principal.subject_id}
    if principal.email:
        actor["email"] = principal.email
    key_id = getattr(request.state, "api_key_id", None)
    if key_id is not None:
        actor["key_id"] = str(key_id)
        actor["key_name"] = getattr(request.state, "api_key_name", "")
    return actor


def _entry(request: Request, response: Response) -> dict[str, Any] | None:
    # A sign-in names the person it admitted; the request itself came in anonymous.
    principal = getattr(request.state, "audit_principal", None) or getattr(
        request.state, "principal", None)
    if not isinstance(principal, tenancy.Principal) or not principal.org_id:
        return None
    noted: dict[str, Any] | None = getattr(request.state, "audit", None)
    path = request.url.path
    if noted is None and (request.method in _SAFE or path in _SKIP):
        return None
    route = request.scope.get("route")
    template = getattr(route, "path", path)
    detail = dict(noted or {"action": f"{request.method} {template}"})
    sheet = detail.pop("sheet", None) or request.path_params.get("namespace")
    entry: dict[str, Any] = {
        "id": f"{time.time_ns():x}-{secrets.token_hex(4)}", "ts": time.time(),
        "org_id": principal.org_id, "actor": _actor(request, principal),
        "action": detail.pop("action"), "status": response.status_code,
    }
    if sheet:
        entry["sheet"] = str(sheet)
    if detail:
        entry["detail"] = detail
    return entry


def base(request: Request, sheet: str) -> dict[str, Any] | None:
    """Who is asking, captured now, for an entry made after the response
    has started (a streamed answer's outcome)."""
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, tenancy.Principal) or not principal.org_id:
        return None
    return {"org_id": principal.org_id, "actor": _actor(request, principal), "sheet": sheet}


def emit(trail: dict[str, Any] | None, action: str, **detail: Any) -> None:
    """Record an outcome the middleware could not see, off the response path."""
    if trail is None:
        return
    if isinstance(detail.get("question"), str):
        detail["question"] = detail["question"][:QUESTION_CHARS]
    spawn(write({**trail, "id": f"{time.time_ns():x}-{secrets.token_hex(4)}",
                 "ts": time.time(), "action": action, "status": 200, "detail": detail}),
          name="audit_write")


async def write(entry: dict[str, Any]) -> None:
    """Never raises: a failed write is logged, the request it describes stands."""
    global _writes
    store = tenancy.get_tenancy()
    try:
        days = await retention_days(entry["org_id"])
        entry["expires_at"] = entry["ts"] + days * 86400
        await store.append_audit(entry["org_id"], entry)
        _writes += 1
        if _writes % _PRUNE_EVERY == 0:
            await store.prune_audit(time.time())
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit_write_failed", action=entry.get("action"), error=str(exc))


class AuditMiddleware(BaseHTTPMiddleware):
    """Inside the auth middleware, so the caller is known when the entry is made."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        entry = _entry(request, response)
        if entry is not None:
            spawn(write(entry), name="audit_write")
        return response
