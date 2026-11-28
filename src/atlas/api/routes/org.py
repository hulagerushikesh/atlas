"""One organisation's people, workspaces and service accounts (E1.3).

Every /org route acts on the caller's own organisation, taken from its
principal and never from the request, and needs an organisation admin
(`authz.require_org_admin`). Something of another organisation answers 404,
the same as something that does not exist.

/admin/orgs and /admin/invitations are the break-glass pair the shared admin
secret keeps (docs/e1-identity.md §3): create an organisation, and invite its
first admin. Everything after that is done by that admin, signed in.

Roles are given by workspace *name*, the thing an admin sees, and resolved
inside the admin's organisation only.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable
from typing import Any, TypeVar

import structlog
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from atlas.api import audit, tenancy
from atlas.api import auth as auth_db
from atlas.api.authz import access_unavailable, require_org_admin
from atlas.api.routes.keys import _require_admin
from atlas.api.schemas import (
    AdminInvitationRequest,
    AdminOrgRequest,
    AdminOrgResponse,
    GroupCreateRequest,
    InvitationRequest,
    MemberUpdateRequest,
    MeOrg,
    OrgGroup,
    OrgInvitation,
    OrgMember,
    OrgResponse,
    OrgServiceAccount,
    OrgWorkspace,
    RoleGrants,
    ServiceAccountCreateRequest,
    ServiceAccountCreateResponse,
    WorkspaceCreateRequest,
)
from atlas.api.tenancy import Invitation, Role, Subject, normalise_email

logger = structlog.get_logger(__name__)
router = APIRouter()

T = TypeVar("T")

# Lower-case letters, digits, - and _, so the name is already its own
# collection slug (two names can never share a collection) and never holds
# the "__" that separates organisation from workspace in a collection name.
_WORKSPACE_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]|_(?!_)){0,63}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def _s(aw: Awaitable[T]) -> T:
    """A store call; a store that cannot be read refuses, as everywhere else."""
    try:
        return await aw
    except (HTTPException, tenancy.WorkspaceNameTaken, tenancy.GroupNameTaken):
        raise
    except Exception as exc:
        logger.warning("org_store_failed", error=str(exc))
        raise access_unavailable() from exc


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail={
        "code": "not_found", "message": f"No {what} by that name in your organisation."})


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message})


def _email(raw: str) -> str:
    email = normalise_email(raw)
    if not _EMAIL.match(email):
        raise HTTPException(status_code=422, detail={
            "code": "bad_email", "message": f"'{raw}' is not an email address."})
    return email


async def _workspaces(org_id: str) -> dict[str, tenancy.Workspace]:
    return {w.id: w for w in await _s(tenancy.get_tenancy().list_workspaces(org_id))}


def _by_id(grants: RoleGrants, workspaces: dict[str, tenancy.Workspace]) -> dict[str, Role]:
    ids = {w.name: w.id for w in workspaces.values()}
    unknown = sorted(set(grants) - set(ids))
    if unknown:
        raise HTTPException(status_code=422, detail={
            "code": "unknown_workspace",
            "message": f"Your organisation has no sheet called {', '.join(unknown)}."})
    return {ids[name]: Role(role) for name, role in grants.items()}


def _by_name(roles: dict[str, Role], workspaces: dict[str, tenancy.Workspace]) -> RoleGrants:
    # A grant on a workspace that has since gone is dropped from the view.
    return {workspaces[ws].name: role.value for ws, role in roles.items() if ws in workspaces}


async def _groups(org_id: str) -> dict[str, tenancy.Group]:
    return {g.id: g for g in await _s(tenancy.get_tenancy().list_groups(org_id))}


def _group_ids(names: list[str], groups: dict[str, tenancy.Group]) -> tuple[str, ...]:
    ids = {g.name: g.id for g in groups.values()}
    unknown = sorted(set(names) - set(ids))
    if unknown:
        raise HTTPException(status_code=422, detail={
            "code": "unknown_group",
            "message": f"Your organisation has no group called {', '.join(unknown)}."})
    return tuple(sorted({ids[n] for n in names}))


def _group_names(ids: tuple[str, ...], groups: dict[str, tenancy.Group]) -> list[str]:
    return sorted(groups[g].name for g in ids if g in groups)


# ── The organisation page ─────────────────────────────────────────────────────

@router.get("/org", response_model=OrgResponse)
async def get_org(request: Request) -> OrgResponse:
    principal = require_org_admin(request)
    store = tenancy.get_tenancy()
    org_id = principal.org_id
    org = await _s(store.get_org(org_id))
    if org is None:
        raise access_unavailable()
    workspaces = await _workspaces(org_id)
    groups = await _groups(org_id)

    members = []
    for user in await _s(store.list_users(org_id)):
        subject = await _s(store.get_subject("user", user.id))
        if subject is None:
            continue
        members.append(OrgMember(
            id=user.id, email=user.email, name=user.name, org_admin=subject.org_admin,
            roles=_by_name(subject.roles, workspaces), you=user.id == principal.subject_id,
            groups=_group_names(subject.groups, groups)))

    invitations = [
        OrgInvitation(email=i.email, org_admin=i.org_admin,
                      roles=_by_name(i.roles, workspaces), created_at=i.created_at)
        for i in await _s(store.list_invitations(org_id))
    ]

    keys = {str(k.id): k for k in await _s(auth_db.list_keys())}
    accounts = []
    for subject in await _s(store.list_subjects(org_id, "service")):
        record = keys.get(subject.id)
        if record is None:
            continue
        accounts.append(OrgServiceAccount(
            key_id=record.id, name=record.name, is_active=record.is_active,
            roles=_by_name(subject.roles, workspaces), total_queries=record.total_queries,
            last_query_at=record.last_query_at))

    return OrgResponse(
        org=MeOrg(id=org.id, name=org.name), domain=org.domain,
        workspaces=[OrgWorkspace(id=w.id, name=w.name)
                    for w in sorted(workspaces.values(), key=lambda w: w.name)],
        members=members, invitations=invitations, service_accounts=accounts,
        groups=[OrgGroup(id=g.id, name=g.name)
                for g in sorted(groups.values(), key=lambda g: g.name)],
    )


@router.post("/org/workspaces", response_model=OrgWorkspace, status_code=201)
async def create_workspace(body: WorkspaceCreateRequest, request: Request) -> OrgWorkspace:
    principal = require_org_admin(request)
    name = body.name.strip()
    if not _WORKSPACE_NAME.match(name):
        raise HTTPException(status_code=422, detail={
            "code": "bad_workspace_name",
            "message": "A sheet name uses lower-case letters, digits, - and _ only, "
                       "starts with a letter or digit, and never has two _ in a row."})
    try:
        ws = await _s(tenancy.get_tenancy().create_workspace(principal.org_id, name))
    except tenancy.WorkspaceNameTaken as exc:
        raise _conflict("workspace_exists",
                        f"Your organisation already has a sheet called '{name}'.") from exc
    logger.info("workspace_created", org_id=principal.org_id, workspace_id=ws.id)
    return OrgWorkspace(id=ws.id, name=ws.name)


# ── Invitations ───────────────────────────────────────────────────────────────

@router.post("/org/invitations", response_model=OrgInvitation, status_code=201)
async def invite(body: InvitationRequest, request: Request) -> OrgInvitation:
    principal = require_org_admin(request)
    store = tenancy.get_tenancy()
    email = _email(body.email)
    workspaces = await _workspaces(principal.org_id)
    roles = _by_id(body.roles, workspaces)
    if await _s(store.find_user(email)) is not None:
        raise _conflict("already_member", f"{email} already has an Atlas account.")
    existing = await _s(store.get_invitation(email))
    if existing is not None and existing.org_id != principal.org_id:
        # Said the same way as an existing account: whose invitation it is
        # belongs to the other organisation.
        raise _conflict("already_member", f"{email} already has an Atlas account.")
    inv = Invitation(email=email, org_id=principal.org_id, org_admin=body.org_admin,
                     roles=roles, invited_by=principal.subject_id)
    await _s(store.put_invitation(inv))
    logger.info("member_invited", org_id=principal.org_id, org_admin=body.org_admin)
    return OrgInvitation(email=email, org_admin=inv.org_admin,
                         roles=_by_name(roles, workspaces), created_at=None)


@router.delete("/org/invitations/{email}", status_code=204)
async def withdraw_invitation(email: str, request: Request) -> Response:
    principal = require_org_admin(request)
    store = tenancy.get_tenancy()
    inv = await _s(store.get_invitation(email))
    if inv is None or inv.org_id != principal.org_id:
        raise _not_found("invitation")
    await _s(store.delete_invitation(email))
    return Response(status_code=204)


# ── Members ───────────────────────────────────────────────────────────────────

async def _member(principal: tenancy.Principal, user_id: str) -> tenancy.User:
    user = await _s(tenancy.get_tenancy().get_user(user_id))
    if user is None or user.org_id != principal.org_id:
        raise _not_found("member")
    return user


@router.put("/org/members/{user_id}", response_model=OrgMember)
async def update_member(user_id: str, body: MemberUpdateRequest,
                        request: Request) -> OrgMember:
    principal = require_org_admin(request)
    user = await _member(principal, user_id)
    if user.id == principal.subject_id and not body.org_admin:
        raise _conflict("last_admin_guard",
                        "You cannot take away your own admin rights. Ask another admin.")
    workspaces = await _workspaces(principal.org_id)
    roles = _by_id(body.roles, workspaces)
    groups = await _groups(principal.org_id)
    store = tenancy.get_tenancy()
    current = await _s(store.get_subject("user", user.id))
    group_ids = (_group_ids(body.groups, groups) if body.groups is not None
                 else current.groups if current else ())
    await _s(store.put_subject(Subject(
        kind="user", id=user.id, org_id=principal.org_id, org_admin=body.org_admin,
        roles=roles, groups=group_ids)))
    logger.info("member_updated", org_id=principal.org_id, org_admin=body.org_admin)
    return OrgMember(id=user.id, email=user.email, name=user.name, org_admin=body.org_admin,
                     roles=_by_name(roles, workspaces), you=user.id == principal.subject_id,
                     groups=_group_names(group_ids, groups))


# ── Groups (E2) ───────────────────────────────────────────────────────────────

_GROUP_NAME = re.compile(r"^[\w][\w .&-]{0,63}$")


@router.post("/org/groups", response_model=OrgGroup, status_code=201)
async def create_group(body: GroupCreateRequest, request: Request) -> OrgGroup:
    principal = require_org_admin(request)
    name = body.name.strip()
    if not _GROUP_NAME.match(name):
        raise HTTPException(status_code=422, detail={
            "code": "bad_group_name",
            "message": "A group name uses letters, digits, spaces, '.', '&', '-' and '_', "
                       "and starts with a letter or digit."})
    try:
        group = await _s(tenancy.get_tenancy().create_group(principal.org_id, name))
    except tenancy.GroupNameTaken as exc:
        raise _conflict("group_exists",
                        f"Your organisation already has a group called '{name}'.") from exc
    logger.info("group_created", org_id=principal.org_id, group_id=group.id)
    return OrgGroup(id=group.id, name=group.name)


@router.delete("/org/groups/{group_id}", status_code=204)
async def delete_group(group_id: str, request: Request) -> Response:
    principal = require_org_admin(request)
    store = tenancy.get_tenancy()
    group = await _s(store.get_group(group_id))
    if group is None or group.org_id != principal.org_id:
        raise _not_found("group")
    await _s(store.delete_group(group_id))
    logger.info("group_deleted", org_id=principal.org_id, group_id=group_id)
    return Response(status_code=204)


@router.delete("/org/members/{user_id}", status_code=204)
async def remove_member(user_id: str, request: Request) -> Response:
    principal = require_org_admin(request)
    user = await _member(principal, user_id)
    if user.id == principal.subject_id:
        raise _conflict("last_admin_guard", "You cannot remove yourself. Ask another admin.")
    await _s(tenancy.get_tenancy().delete_user(user.id))
    logger.info("member_removed", org_id=principal.org_id)
    return Response(status_code=204)


# ── Service accounts ──────────────────────────────────────────────────────────

@router.post("/org/service-accounts", response_model=ServiceAccountCreateResponse,
             status_code=201)
async def create_service_account(body: ServiceAccountCreateRequest,
                                 request: Request) -> ServiceAccountCreateResponse:
    principal = require_org_admin(request)
    roles = _by_id(body.roles, await _workspaces(principal.org_id))
    raw, key_id = await _s(auth_db.create_key(name=body.name, rate_limit_rpm=body.rate_limit_rpm))
    # Written straight after the key: a key with no record would be a legacy
    # key, which reaches the public organisation.
    await _s(tenancy.get_tenancy().put_subject(Subject(
        kind="service", id=str(key_id), org_id=principal.org_id, roles=roles)))
    logger.info("service_account_created", org_id=principal.org_id)
    return ServiceAccountCreateResponse(key=raw, key_id=key_id, name=body.name)


@router.delete("/org/service-accounts/{key_id}", status_code=204)
async def revoke_service_account(key_id: str, request: Request) -> Response:
    principal = require_org_admin(request)
    subject = await _s(tenancy.get_tenancy().get_subject("service", key_id))
    if subject is None or subject.org_id != principal.org_id:
        raise _not_found("service account")
    # Revoked, not deleted: deleting the record would turn the key back into
    # a legacy one. The key is refused from the next request.
    if await _s(auth_db.set_key_active(key_id, False)) is None:
        raise _not_found("service account")
    logger.info("service_account_revoked", org_id=principal.org_id)
    return Response(status_code=204)


# ── The audit record (E4.1) ───────────────────────────────────────────────────

class AuditSettings(BaseModel):
    retention_days: int = Field(..., ge=audit.MIN_RETENTION_DAYS, le=audit.MAX_RETENTION_DAYS)


@router.get("/org/audit")
async def read_audit(request: Request, before: float | None = None,
                     limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    """The organisation's newest entries, newest first; page with `before`."""
    principal = require_org_admin(request)
    entries = await _s(tenancy.get_tenancy().list_audit(principal.org_id, before=before,
                                                        limit=limit))
    return {"entries": entries,
            "retention_days": await _s(audit.retention_days(principal.org_id))}


@router.put("/org/audit/settings")
async def set_audit_settings(body: AuditSettings, request: Request) -> dict[str, Any]:
    """How long new entries are kept. Entries already written keep their date."""
    principal = require_org_admin(request)
    await _s(audit.set_retention_days(principal.org_id, body.retention_days))
    audit.note(request, "audit.retention", retention_days=body.retention_days)
    return {"retention_days": body.retention_days}


# ── Break-glass: the shared admin secret ──────────────────────────────────────

@router.post("/admin/orgs", response_model=AdminOrgResponse, status_code=201)
async def admin_create_org(
    body: AdminOrgRequest, x_admin_secret: str = Header("", alias="X-Admin-Secret"),
) -> AdminOrgResponse:
    _require_admin(x_admin_secret)
    store = tenancy.get_tenancy()
    domain = body.domain.strip().lower()
    if domain and await _s(store.find_org_by_domain(domain)) is not None:
        raise _conflict("domain_taken", f"Another organisation already has {domain}.")
    org = await _s(store.create_org(body.name.strip(), domain))
    logger.info("org_created", org_id=org.id)
    return AdminOrgResponse(id=org.id, name=org.name, domain=org.domain)


@router.post("/admin/invitations", response_model=OrgInvitation, status_code=201)
async def admin_invite_org_admin(
    body: AdminInvitationRequest, x_admin_secret: str = Header("", alias="X-Admin-Secret"),
) -> OrgInvitation:
    _require_admin(x_admin_secret)
    store = tenancy.get_tenancy()
    email = _email(body.email)
    if await _s(store.get_org(body.org_id)) is None:
        raise HTTPException(status_code=404, detail={
            "code": "not_found", "message": f"No organisation {body.org_id!r}."})
    if await _s(store.find_user(email)) is not None:
        raise _conflict("already_member", f"{email} already has an Atlas account.")
    await _s(store.put_invitation(Invitation(email=email, org_id=body.org_id, org_admin=True,
                                             invited_by="admin_secret")))
    logger.info("org_admin_invited", org_id=body.org_id)
    return OrgInvitation(email=email, org_admin=True, roles={}, created_at=None)
