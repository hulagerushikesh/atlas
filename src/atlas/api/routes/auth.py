"""Sign-in with Google, sign-out, and who the caller is (E1.3).

GET  /auth/config  — whether sign-in is on, and the public client id
POST /auth/google  — a Google ID token in, a session cookie out
POST /auth/logout  — the cookie cleared
GET  /auth/me      — the caller: person, organisation, workspaces and roles

How a token is checked and why the cookie holds no roles: atlas.api.sessions.
Who a verified account becomes: tenancy.place_user.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request, Response

from atlas.api import sessions, tenancy
from atlas.api.authz import access_unavailable
from atlas.api.dependencies import get_principal
from atlas.api.schemas import (
    AuthConfigResponse,
    GoogleSignInRequest,
    MeOrg,
    MeResponse,
    MeUser,
    MeWorkspace,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


def _sign_in(request: Request) -> sessions.SignIn | None:
    s: sessions.SignIn | None = getattr(request.app.state, "sign_in", None)
    return s if s is not None and s.enabled else None


def _from_console(request: Request) -> None:
    # Without this, a page on another site could post a token of the
    # attacker's own account and sign a visitor into it.
    if request.headers.get(sessions.CSRF_HEADER) != sessions.CSRF_VALUE:
        raise HTTPException(status_code=403, detail={
            "code": "csrf", "message": "This request did not come from Atlas."})


def _set_cookie(response: Response, value: str) -> None:
    response.set_cookie(sessions.COOKIE, value, max_age=sessions.SESSION_SECONDS,
                        path="/", httponly=True, secure=True, samesite="lax")


@router.get("/auth/config", response_model=AuthConfigResponse)
async def auth_config(request: Request) -> AuthConfigResponse:
    s = _sign_in(request)
    return AuthConfigResponse(enabled=s is not None,
                              google_client_id=s.client_id if s else "")


@router.post("/auth/google", response_model=MeResponse)
async def sign_in_with_google(body: GoogleSignInRequest, request: Request,
                              response: Response) -> MeResponse:
    s = _sign_in(request)
    if s is None:
        raise HTTPException(status_code=503, detail={
            "code": "sign_in_off", "message": "Sign-in is not switched on for this Atlas."})
    _from_console(request)
    try:
        identity = await s.verifier.verify(body.credential)
    except sessions.InvalidToken as exc:
        logger.info("sign_in_refused", reason=str(exc))
        raise HTTPException(status_code=401, detail={
            "code": "invalid_token",
            "message": "Google did not confirm this sign-in. Try again."}) from exc
    except sessions.SignInUnavailable as exc:
        raise HTTPException(status_code=503, detail={
            "code": "sign_in_unavailable",
            "message": "Atlas could not reach Google to check the sign-in. Try again shortly.",
        }) from exc

    store = tenancy.get_tenancy()
    try:
        user = await tenancy.place_user(store, identity.email, identity.name,
                                        identity.hosted_domain)
        subject = await store.get_subject("user", user.id)
    except tenancy.NotInvited as exc:
        logger.info("sign_in_refused", reason="not_invited")
        raise HTTPException(status_code=403, detail={
            "code": "not_invited",
            "message": f"{identity.email} has not been invited to Atlas. "
                       "Ask your organisation's admin for an invitation.",
        }) from exc
    except Exception as exc:
        logger.warning("sign_in_store_failed", error=str(exc))
        raise access_unavailable() from exc
    if subject is None:
        raise access_unavailable()

    _set_cookie(response, sessions.sign_session(user.id, s.secret))
    logger.info("signed_in", org_id=user.org_id)
    return await _describe(tenancy.principal_from_subject(subject), user)


@router.post("/auth/logout", status_code=204)
async def sign_out(request: Request) -> Response:
    _from_console(request)
    response = Response(status_code=204)
    response.delete_cookie(sessions.COOKIE, path="/", httponly=True, secure=True,
                           samesite="lax")
    return response


@router.get("/auth/me", response_model=MeResponse)
async def me(request: Request) -> MeResponse:
    principal = get_principal(request)
    user_id = getattr(request.state, "user_id", None)
    if principal.kind != "user" or not user_id:
        return MeResponse(kind=principal.kind)
    try:
        user = await tenancy.get_tenancy().get_user(user_id)
    except Exception as exc:
        raise access_unavailable() from exc
    if user is None:
        return MeResponse(kind=principal.kind)
    return await _describe(principal, user)


async def _describe(principal: tenancy.Principal, user: tenancy.User) -> MeResponse:
    store = tenancy.get_tenancy()
    try:
        org = await store.get_org(user.org_id)
        workspaces = await store.list_workspaces(user.org_id)
    except Exception as exc:
        raise access_unavailable() from exc
    mine = [MeWorkspace(name=w.name, role=role.value)
            for w in workspaces if (role := principal.role_on(w.id)) is not None]
    return MeResponse(
        kind="user",
        user=MeUser(id=user.id, email=user.email, name=user.name),
        org=MeOrg(id=org.id, name=org.name) if org else None,
        org_admin=principal.org_admin,
        workspaces=mine,
    )
