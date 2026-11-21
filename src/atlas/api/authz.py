"""
Route policy and the one permission check every workspace route makes.

Design rationale (docs/e1-identity.md §4):
    `POLICY` names every route the app serves and what it needs: public,
    the admin secret, any authenticated caller, or an action on the workspace
    the request names. `tests/unit/api/test_isolation.py` walks the app's
    routes and fails on one missing from this table, so a route added later
    cannot ship without a decision about who may call it. The auth middleware
    reads its public list from here too, so the table and what the middleware
    lets through cannot disagree.

    A workspace route calls `authorize(request, name, action)` and gets the
    Workspace back. The name is looked up inside the caller's organisation,
    and a workspace the caller cannot read answers 404 exactly like one that
    does not exist: "forbidden" would confirm that another organisation has
    a workspace by that name. A caller who can read but not write gets 403.
"""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import HTTPException, Request

from atlas.api.dependencies import get_principal
from atlas.api.tenancy import Action, TenancyUnavailable, Workspace, resolve_workspace

Rule = Literal["public", "admin_secret", "authenticated", "read", "write", "manage"]

POLICY: dict[tuple[str, str], Rule] = {
    ("GET", "/"): "public",
    ("GET", "/app"): "public",
    ("GET", "/health"): "public",
    ("GET", "/warm"): "public",
    ("POST", "/warm"): "public",
    ("GET", "/metrics"): "public",
    ("GET", "/docs"): "public",
    ("GET", "/docs/oauth2-redirect"): "public",
    ("GET", "/redoc"): "public",
    ("GET", "/openapi.json"): "public",
    # Reachable before the first key exists; each checks X-Admin-Secret.
    ("POST", "/keys"): "admin_secret",
    ("GET", "/keys"): "admin_secret",
    ("PATCH", "/keys/{key_id}"): "admin_secret",
    # The caller's own key's usage.
    ("GET", "/usage"): "authenticated",
    # Lists only what the caller may read.
    ("GET", "/namespaces"): "authenticated",
    ("GET", "/namespaces/{namespace}/sources"): "read",
    ("POST", "/query"): "read",
    ("POST", "/ingest"): "write",
    ("POST", "/ingest/upload"): "write",
}

# What the auth middleware lets through without a key: every public or
# admin-secret route above, plus the static mounts, which are not routes.
PUBLIC_PATHS = frozenset(
    path for (_, path), rule in POLICY.items()
    if rule in ("public", "admin_secret") and "{" not in path
)
PUBLIC_PREFIXES = ("/app/", "/out/", "/keys/")


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def access_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail={
        "code": "access_check_unavailable",
        "message": "Atlas could not check your access just now. Try again shortly.",
    })


def _not_found(name: str) -> HTTPException:
    return HTTPException(status_code=404, detail={
        "code": "workspace_not_found",
        "message": f"No sheet called '{name}' that you can open.",
    })


async def authorize(request: Request, name: str, action: Action) -> Workspace:
    """The workspace *name* names, if the caller may do *action* on it."""
    principal = get_principal(request)
    try:
        ws = await resolve_workspace(principal, name)
    except TenancyUnavailable as exc:
        raise access_unavailable() from exc
    if ws is None or not principal.can(ws, "read"):
        raise _not_found(name)
    if not principal.can(ws, action):
        raise HTTPException(status_code=403, detail={
            "code": "forbidden",
            "message": f"Your access to '{name}' does not allow this.",
        })
    structlog.contextvars.bind_contextvars(org_id=ws.org_id, workspace_id=ws.id)
    return ws
