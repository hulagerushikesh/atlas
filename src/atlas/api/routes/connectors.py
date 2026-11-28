"""
Google Drive on a sheet (E3.1, docs/e3-drive-connector.md §5).

    GET    /connectors/drive/connect?namespace=   send an editor to Google's consent
    GET    /connectors/drive/callback             Google sends them back here
    GET    /namespaces/{ns}/connectors/drive      the connection, without its token
    PUT    /namespaces/{ns}/connectors/drive      choose the folder; syncs it
    POST   /namespaces/{ns}/connectors/drive/sync sync now

Every sync runs inside the request that asked for it, under a time limit: a
server that bills by request (Cloud Run) slows work done after the reply to
a crawl. A pass that runs out of time stops cleanly and the next carries on.
    DELETE /namespaces/{ns}/connectors/drive      disconnect; removes what it synced
    POST   /connectors/drive/tick                 Cloud Scheduler, every 5 min (E3.2)
    GET    /connectors/google-groups              an admin's Google Group links
    PUT    /connectors/google-groups              link a Google Group to an Atlas group

Editors only: connecting a folder puts its documents in front of everyone
Drive shares them with, which is an editor's decision on the sheet. The sync
runs as the person who connected, with Drive's read-only scope.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from atlas.api import audit, sessions, tenancy
from atlas.api.authz import authorize, require_org_admin
from atlas.api.dependencies import get_app_state, get_principal, get_registry
from atlas.api.sheets import sheet_changed
from atlas.config import DriveConfig
from atlas.connectors import connections
from atlas.connectors.drive import (
    SCOPE,
    DriveAuthError,
    DriveSource,
    GoogleDrive,
    sync_folder,
    touches,
)

logger = structlog.get_logger(__name__)
router = APIRouter()

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_FOLDER_IN_URL = re.compile(r"/folders/([A-Za-z0-9_-]+)")
_FOLDER_ID = re.compile(r"^[A-Za-z0-9_-]{10,}$")


class FolderRequest(BaseModel):
    folder: str = Field(..., min_length=1, max_length=500,
                        description="A Drive folder link or its id")


class GroupLinkRequest(BaseModel):
    google_group: str = Field(..., min_length=3, max_length=320)
    group: str | None = Field(None, description="Atlas group name; null removes the link")


def _off() -> HTTPException:
    return HTTPException(status_code=503, detail={
        "code": "drive_off", "message": "Google Drive is not switched on for this Atlas."})


def _config(request: Request) -> tuple[DriveConfig, str, str]:
    """Drive settings, the sign-in client id and the session secret, or 503."""
    cfg: DriveConfig = get_app_state(request).drive
    sign_in = getattr(request.app.state, "sign_in", None)
    client_id = cfg.client_id or getattr(sign_in, "client_id", "")
    secret = getattr(sign_in, "secret", "")
    if not (cfg.client_secret and cfg.token_key and cfg.public_url and client_id and secret):
        raise _off()
    return cfg, client_id, secret


def _redirect_uri(cfg: DriveConfig) -> str:
    return f"{cfg.public_url.rstrip('/')}/connectors/drive/callback"


def _person(request: Request) -> tenancy.Principal:
    principal = get_principal(request)
    if principal.kind != "user" or not principal.email:
        raise HTTPException(status_code=403, detail={
            "code": "sign_in_needed",
            "message": "Sign in with Google to connect Drive; keys cannot."})
    return principal


def folder_id_from(text: str) -> str | None:
    text = text.strip()
    if m := _FOLDER_IN_URL.search(text):
        return m.group(1)
    return text if _FOLDER_ID.match(text) else None


async def exchange_code(code: str, redirect_uri: str, client_id: str,
                        client_secret: str) -> str | None:
    """The refresh token Google gives for a consent code, or None."""
    async with httpx.AsyncClient(timeout=15.0) as http:
        r = await http.post(_TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": client_id, "client_secret": client_secret})
    if r.status_code != 200:
        logger.warning("drive_code_refused", status=r.status_code)
        return None
    token = r.json().get("refresh_token")
    return str(token) if token else None


def _source_factory(request: Request) -> Callable[[str], DriveSource]:
    """How a sync reaches Drive. Tests put a fake on app.state."""
    custom = getattr(request.app.state, "drive_source", None)
    if custom is not None:
        return custom  # type: ignore[no-any-return]
    cfg, client_id, _ = _config(request)
    assert cfg.client_secret is not None
    secret = cfg.client_secret.get_secret_value()
    return lambda token: GoogleDrive(token, client_id, secret)


# ── Connecting ────────────────────────────────────────────────────────────────

@router.get("/connectors/drive/connect", response_model=None)
async def connect(request: Request, namespace: str = Query(..., min_length=1)
                  ) -> RedirectResponse:
    cfg, client_id, secret = _config(request)
    person = _person(request)
    ws = await authorize(request, namespace, "write")
    params = {
        "client_id": client_id, "redirect_uri": _redirect_uri(cfg),
        "response_type": "code", "scope": SCOPE, "access_type": "offline",
        # A refresh token is only returned on a fresh consent.
        "prompt": "consent", "include_granted_scopes": "true",
        "login_hint": person.email,
        "state": connections.sign_state(ws.id, person.subject_id, secret),
    }
    return RedirectResponse(f"{_AUTH_URL}?{urlencode(params)}", status_code=303)


@router.get("/connectors/drive/callback", response_model=None)
async def callback(request: Request, state: str = "", code: str = "",
                   error: str = "") -> RedirectResponse:
    cfg, client_id, secret = _config(request)
    person = _person(request)
    found = connections.read_state(state, secret)
    if found is None or found[1] != person.subject_id:
        raise HTTPException(status_code=400, detail={
            "code": "bad_state", "message": "This Drive connection link has expired. Try again."})
    ws = await tenancy.get_tenancy().get_workspace(found[0])
    if ws is None or not person.can(ws, "write"):
        raise HTTPException(status_code=404, detail={
            "code": "workspace_not_found", "message": "That sheet is no longer yours to edit."})
    audit.note(request, "drive.connect", sheet=ws.name)
    back = f"/app?namespace={ws.name}"
    if error or not code:
        return RedirectResponse(f"{back}&drive=declined", status_code=303)
    assert cfg.client_secret is not None and cfg.token_key is not None
    token = await exchange_code(code, _redirect_uri(cfg), client_id,
                                cfg.client_secret.get_secret_value())
    if token is None:
        return RedirectResponse(f"{back}&drive=failed", status_code=303)
    record = await connections.get(ws.id) or {"workspace_id": ws.id, "org_id": ws.org_id,
                                              "files": {}}
    record.update(token=connections.seal(token, cfg.token_key.get_secret_value()),
                  connected_by=person.subject_id, connected_by_email=person.email, error="")
    await connections.put(record)
    logger.info("drive_connected", workspace_id=ws.id)
    return RedirectResponse(f"{back}&drive=connected", status_code=303)


# ── One sheet's connection ───────────────────────────────────────────────────

@router.get("/namespaces/{namespace}/connectors/drive")
async def status(namespace: str, request: Request) -> dict[str, Any]:
    ws = await authorize(request, namespace, "write")
    return connections.public_view(await connections.get(ws.id))


@router.put("/namespaces/{namespace}/connectors/drive")
async def choose_folder(namespace: str, body: FolderRequest,
                        request: Request) -> dict[str, Any]:
    ws = await authorize(request, namespace, "write")
    record = await connections.get(ws.id)
    if record is None or not record.get("token"):
        raise HTTPException(status_code=409, detail={
            "code": "drive_not_connected", "message": "Connect Google Drive first."})
    folder = folder_id_from(body.folder)
    if folder is None:
        raise HTTPException(status_code=422, detail={
            "code": "not_a_folder", "message": "Paste a Google Drive folder link."})
    if record.get("folder_id") and record["folder_id"] != folder:
        # A different folder: what the old one brought in goes first.
        await _remove_synced(request, ws, record)
    record["folder_id"] = folder
    record.pop("cursor", None)
    await connections.put(record)
    return await _sync_now(request, ws)


@router.post("/namespaces/{namespace}/connectors/drive/sync")
async def sync_now(namespace: str, request: Request) -> dict[str, Any]:
    ws = await authorize(request, namespace, "write")
    record = await connections.get(ws.id)
    if record is None or not record.get("folder_id"):
        raise HTTPException(status_code=409, detail={
            "code": "drive_not_connected", "message": "Connect Drive and choose a folder first."})
    return await _sync_now(request, ws)


@router.delete("/namespaces/{namespace}/connectors/drive")
async def disconnect(namespace: str, request: Request) -> dict[str, Any]:
    ws = await authorize(request, namespace, "write")
    record = await connections.get(ws.id)
    if record is None:
        return {"connected": False, "removed": 0}
    async with connections.lock_for(ws.id):
        removed = await _remove_synced(request, ws, record)
        await connections.delete(ws.id)
    logger.info("drive_disconnected", workspace_id=ws.id, removed=removed)
    return {"connected": False, "removed": removed}


async def _remove_synced(request: Request, ws: tenancy.Workspace,
                         record: dict[str, Any]) -> int:
    from atlas.connectors.drive import drive_doc_id  # noqa: PLC0415

    files = record.get("files") or {}
    if not files:
        return 0
    registry = get_registry(request)
    corpus = tenancy.registry_namespace(ws)
    indexer = registry.get(corpus).indexer
    for file_id in files:
        await indexer.delete_document(drive_doc_id(file_id))
    record["files"] = {}
    await sheet_changed(registry, corpus, ws, get_app_state(request).cache)
    return len(files)


# ── The sync itself ──────────────────────────────────────────────────────────

async def _sync_now(request: Request, ws: tenancy.Workspace) -> dict[str, Any]:
    cfg: DriveConfig = get_app_state(request).drive
    return await run_sync(request, ws, full=True,
                          deadline=time.monotonic() + cfg.sync_seconds)


async def run_sync(request: Request, ws: tenancy.Workspace, *, full: bool = False,
                   deadline: float | None = None) -> dict[str, Any]:
    """One pass for one sheet. Never raises: the outcome is on the record.

    Not *full* (the 5-minute pass): Drive's change feed is read first and the
    folder is walked only if a change concerns it. A full pass is due daily
    anyway, in case a sharing change never reached the feed. A pass cut short
    by *deadline* leaves `resume` on the record, so the next one walks."""
    # The indexer's reads and writes by document id are not scoped to a
    # reader, so the editor's tokens carried into this task do not narrow it.
    async with connections.lock_for(ws.id):
        record = await connections.get(ws.id)
        if record is None or not record.get("folder_id"):
            return {}
        cfg: DriveConfig = get_app_state(request).drive
        key = cfg.token_key.get_secret_value() if cfg.token_key else ""
        token = connections.unseal(record.get("token", ""), key) if key else None
        record["syncing"] = True
        await connections.put(record)
        try:
            if token is None:
                raise DriveAuthError("the stored Drive grant cannot be read; reconnect Drive")
            source = _source_factory(request)(token)
            now = time.time()
            full = (full or not record.get("cursor")
                    or now - float(record.get("last_full") or 0) >= cfg.full_every_seconds)
            walk, cursor = True, ""
            if not (full or record.get("resume")):
                walk, cursor = await _feed(source, record)
            if not cursor:                      # read before the walk: nothing is missed
                cursor = await source.start_cursor()
            if walk:
                finished = await _pass(request, ws, record, source, cfg, deadline)
                record["resume"] = not finished
                if full and finished:
                    record["last_full"] = now
            record.update(cursor=cursor, last_check=now, error="")
        except DriveAuthError as exc:
            record["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 -- reported on the record, retried next pass
            logger.warning("drive_sync_failed", workspace_id=ws.id, error=str(exc))
            record["error"] = "The last sync could not finish. Atlas will try again."
        finally:
            record["syncing"] = False
            await connections.put(record)
        return connections.public_view(record)


async def _feed(source: DriveSource, record: dict[str, Any]) -> tuple[bool, str]:
    """(walk the folder?, the cursor to keep) from Drive's change feed. A feed
    that cannot be read walks the folder and starts a fresh cursor."""
    try:
        changes, cursor = await source.changes(str(record["cursor"]))
    except DriveAuthError:
        raise
    except Exception as exc:  # noqa: BLE001 -- an expired cursor: walk instead
        logger.warning("drive_feed_unreadable", error=str(exc))
        return True, ""
    held = (record.get("files") or {}).keys()
    folders = record.get("folders") or [record["folder_id"]]
    return touches(changes, held, folders), cursor


async def _pass(request: Request, ws: tenancy.Workspace, record: dict[str, Any],
                source: DriveSource, cfg: DriveConfig, deadline: float | None) -> bool:
    """Walk and sync the folder; False if time ran out before every file."""
    registry = get_registry(request)
    corpus = tenancy.registry_namespace(ws)
    report, files = await sync_folder(
        source, registry.get(corpus).indexer, record["folder_id"],
        dict(record.get("files") or {}), await connections.group_links(ws.org_id),
        max_files=cfg.max_files, max_file_bytes=cfg.max_file_bytes, deadline=deadline)
    record.update(files=files, report=report.as_dict(), last_sync=time.time(),
                  folders=report.folders)
    if report.indexed or report.access_changed or report.removed:
        await sheet_changed(registry, corpus, ws, get_app_state(request).cache)
    return report.left == 0


# ── Cloud Scheduler's 5-minute call ──────────────────────────────────────────

def _scheduler_verifier(request: Request, audience: str) -> sessions.GoogleVerifier:
    found = getattr(request.app.state, "drive_tick_verifier", None)
    if found is None or found.client_id != audience:
        found = sessions.GoogleVerifier(audience)
        request.app.state.drive_tick_verifier = found
    return found


@router.post("/connectors/drive/tick")
async def tick(request: Request, authorization: str = Header("")) -> dict[str, Any]:
    """Every connected sheet's 5-minute pass, run inside this request so a
    server that bills by request keeps its processor for the whole pass.
    Least recently checked first, under one time limit: sheets not reached
    go first next time."""
    cfg: DriveConfig = get_app_state(request).drive
    if not (cfg.scheduler_email and cfg.public_url):
        raise _off()
    refused = HTTPException(status_code=401, detail={
        "code": "not_the_scheduler", "message": "Only Atlas's scheduler may call this."})
    if not authorization.startswith("Bearer "):
        raise refused
    try:
        caller = await _scheduler_verifier(request, cfg.public_url).verify(authorization[7:])
    except (sessions.InvalidToken, sessions.SignInUnavailable) as exc:
        logger.info("drive_tick_refused", reason=str(exc))
        raise refused from exc
    if caller.email.lower() != cfg.scheduler_email.lower():
        raise refused
    store = tenancy.get_tenancy()
    deadline = time.monotonic() + cfg.tick_seconds
    sheets = failed = waiting = 0
    due = [r for r in await connections.all_connections()
           if r.get("folder_id") and r.get("token")]
    due.sort(key=lambda r: float(r.get("last_check") or 0))
    for record in due:
        if time.monotonic() >= deadline:
            waiting += 1
            continue
        ws = await store.get_workspace(record["workspace_id"])
        if ws is None:
            continue
        sheets += 1
        failed += bool((await run_sync(request, ws, deadline=deadline)).get("error"))
    logger.info("drive_tick", sheets=sheets, failed=failed, waiting=waiting)
    return {"sheets": sheets, "failed": failed}


# ── Google Groups → Atlas groups (organisation admins) ───────────────────────

@router.get("/connectors/google-groups")
async def list_links(request: Request) -> dict[str, Any]:
    principal = require_org_admin(request)
    links = await connections.group_links(principal.org_id)
    names = {g.id: g.name for g in await tenancy.get_tenancy().list_groups(principal.org_id)}
    return {"links": [{"google_group": e, "group": names.get(g, "")}
                      for e, g in sorted(links.items())]}


@router.put("/connectors/google-groups")
async def put_link(body: GroupLinkRequest, request: Request) -> dict[str, Any]:
    principal = require_org_admin(request)
    email = tenancy.normalise_email(body.google_group)
    group_id = None
    if body.group is not None:
        groups = {g.name: g.id for g in await tenancy.get_tenancy().list_groups(principal.org_id)}
        if body.group not in groups:
            raise HTTPException(status_code=422, detail={
                "code": "unknown_group",
                "message": f"Your organisation has no group called {body.group}."})
        group_id = groups[body.group]
    await connections.link_group(principal.org_id, email, group_id)
    # Takes effect on each sheet's next sync, which rewrites access lists.
    return {"google_group": email, "group": body.group}
