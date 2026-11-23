"""Sign-in, sessions, invitations and the organisation routes (E1.3).

Google is replaced by a key this file makes: tokens are signed with it, and
the verifier is handed its certificate in place of Google's published ones.
Everything after the signature check is the real code: audience, issuer,
expiry, verified email, placement by invitation or domain, the cookie, the
middleware, and every /org route tried from the other organisation.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from google.auth import crypt
from google.auth import jwt as gjwt

from atlas.api import auth, sessions, tenancy
from atlas.api.middleware.auth_mw import APIKeyMiddleware
from atlas.api.routes import auth as auth_routes
from atlas.api.routes import keys as key_routes
from atlas.api.routes import org as org_routes
from atlas.api.tenancy import Invitation, Role
from atlas.config import IngestConfig, get_settings
from atlas.ingestion.indexer import IndexResult

CLIENT_ID = "test-client.apps.googleusercontent.com"
SECRET = "session-secret-for-tests-only"
KID = "test-kid"
CONSOLE = {sessions.CSRF_HEADER: sessions.CSRF_VALUE}


# ── A stand-in for Google's signing key ──────────────────────────────────────

@dataclass(frozen=True)
class Key:
    pem: bytes
    cert: str


def _make_key() -> Key:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = dt.datetime.now(dt.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(private.public_key()).serial_number(1)
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=1))
            .sign(private, hashes.SHA256()))
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    return Key(pem=pem, cert=cert.public_bytes(serialization.Encoding.PEM).decode())


@pytest.fixture(scope="module")
def google_key() -> Key:
    return _make_key()


@pytest.fixture(scope="module")
def other_key() -> Key:
    return _make_key()


def token(key: Key, email: str, *, hd: str = "", aud: str = CLIENT_ID,
          iss: str = "https://accounts.google.com", expires_in: int = 3600,
          verified: Any = True, kid: str = KID) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {"iss": iss, "aud": aud, "sub": f"g-{email}", "email": email,
                              "email_verified": verified, "name": email.split("@")[0],
                              "iat": now - 10, "exp": now + expires_in}
    if hd:
        claims["hd"] = hd
    signer = crypt.RSASigner.from_string(key.pem, key_id=kid)
    return gjwt.encode(signer, claims).decode()


def verifier(key: Key) -> sessions.GoogleVerifier:
    return sessions.GoogleVerifier(CLIENT_ID, certs={KID: key.cert})


# ── The token check ──────────────────────────────────────────────────────────

class TestGoogleToken:
    def test_a_good_token_names_the_account(self, google_key: Key) -> None:
        who = asyncio.run(verifier(google_key).verify(
            token(google_key, "Ana@Acme.com", hd="ACME.com")))
        assert who.email == "Ana@Acme.com" and who.hosted_domain == "acme.com"

    @pytest.mark.parametrize("bad", [
        {"aud": "someone-elses-client"},
        {"expires_in": -3600},
        {"iss": "https://evil.example"},
        {"verified": False},
    ], ids=["other-audience", "expired", "other-issuer", "unverified-email"])
    def test_a_token_atlas_did_not_ask_for_is_refused(
        self, google_key: Key, bad: dict[str, Any]
    ) -> None:
        with pytest.raises(sessions.InvalidToken):
            asyncio.run(verifier(google_key).verify(token(google_key, "a@acme.com", **bad)))

    def test_a_token_signed_by_another_key_is_refused(
        self, google_key: Key, other_key: Key
    ) -> None:
        # Same key id, wrong key: the forger's own signature.
        with pytest.raises(sessions.InvalidToken):
            asyncio.run(verifier(google_key).verify(token(other_key, "a@acme.com")))

    def test_an_unknown_key_id_is_refused(self, google_key: Key) -> None:
        with pytest.raises(sessions.InvalidToken):
            asyncio.run(verifier(google_key).verify(token(google_key, "a@x.com", kid="nope")))

    def test_garbage_is_refused(self, google_key: Key) -> None:
        with pytest.raises(sessions.InvalidToken):
            asyncio.run(verifier(google_key).verify("not-a-token"))

    def test_google_rotating_its_key_is_followed(self, google_key: Key) -> None:
        fetch = AsyncMock(side_effect=[({"old": "x"}, 3600.0), ({KID: google_key.cert}, 3600.0)])
        v = sessions.GoogleVerifier(CLIENT_ID, fetch=fetch)
        v._fetched_at = 0.0
        asyncio.run(v._load())  # the cache holds only the old key
        v._fetched_at = 0.0     # as if that fetch were over a minute ago
        assert asyncio.run(v.verify(token(google_key, "a@x.com"))).email == "a@x.com"
        assert fetch.await_count == 2

    def test_made_up_key_ids_do_not_hammer_google(self, google_key: Key) -> None:
        fetch = AsyncMock(return_value=({KID: google_key.cert}, 3600.0))
        v = sessions.GoogleVerifier(CLIENT_ID, fetch=fetch)
        for _ in range(5):
            with pytest.raises(sessions.InvalidToken):
                asyncio.run(v.verify(token(google_key, "a@x.com", kid="made-up")))
        assert fetch.await_count == 1

    def test_unreachable_google_is_not_the_callers_fault(self, google_key: Key) -> None:
        v = sessions.GoogleVerifier(CLIENT_ID, fetch=AsyncMock(side_effect=OSError("down")))
        with pytest.raises(sessions.SignInUnavailable):
            asyncio.run(v.verify(token(google_key, "a@x.com")))


# ── The cookie ───────────────────────────────────────────────────────────────

class TestSessionCookie:
    def test_round_trip(self) -> None:
        assert sessions.read_session(sessions.sign_session("usr_1", SECRET), SECRET) == "usr_1"

    def test_another_secret_does_not_read_it(self) -> None:
        assert sessions.read_session(sessions.sign_session("usr_1", SECRET), "other") is None

    def test_an_edited_cookie_is_refused(self) -> None:
        value = sessions.sign_session("usr_1", SECRET)
        assert sessions.read_session(value.replace("usr_1", "usr_2"), SECRET) is None

    def test_it_expires_after_eight_hours(self) -> None:
        value = sessions.sign_session("usr_1", SECRET, now=0)
        assert sessions.read_session(value, SECRET, now=8 * 3600 - 1) == "usr_1"
        assert sessions.read_session(value, SECRET, now=8 * 3600) is None

    def test_no_secret_no_session(self) -> None:
        with pytest.raises(ValueError):
            sessions.sign_session("usr_1", "")
        assert sessions.read_session("v1.usr_1.9999999999.x", "") is None


# ── The app ──────────────────────────────────────────────────────────────────

@dataclass
class Site:
    app: Any
    ws: dict[str, str]           # "a/docs" -> workspace id
    key: Key

    def browser(self) -> TestClient:
        # https, or the client would not send back a Secure cookie.
        return TestClient(self.app, base_url="https://testserver")

    def sign_in(self, email: str, hd: str = "") -> TestClient:
        c = self.browser()
        r = c.post("/auth/google", json={"credential": token(self.key, email, hd=hd)},
                   headers=CONSOLE)
        assert r.status_code == 200, r.text
        return c


@pytest.fixture
def site(client: TestClient, tmp_path: Path, google_key: Key,
         monkeypatch: pytest.MonkeyPatch) -> Iterator[Site]:
    monkeypatch.setenv("ADMIN_SECRET", "s3cret")
    get_settings.cache_clear()
    asyncio.run(auth.configure_store("sqlite", sqlite_path=tmp_path / "k.db").init())
    auth._windows.clear()
    store = tenancy.get_tenancy()

    async def build() -> dict[str, str]:
        ws: dict[str, str] = {}
        await store.create_org("Acme", "acme.com", org_id="org_a")
        await store.create_org("Bolt", org_id="org_b")
        for org, name in (("org_a", "docs"), ("org_a", "hr"), ("org_b", "docs")):
            ws[f"{org[-1]}/{name}"] = (await store.create_workspace(org, name)).id
        await store.put_invitation(Invitation(email="admin@acme.com", org_id="org_a",
                                              org_admin=True))
        await store.put_invitation(Invitation(email="reader@gmail.com", org_id="org_a",
                                              roles={ws["a/docs"]: Role.READER}))
        await store.put_invitation(Invitation(email="admin@bolt.io", org_id="org_b",
                                              org_admin=True))
        return ws

    ws = asyncio.run(build())
    app = client.app
    app.include_router(auth_routes.router)  # type: ignore[attr-defined]
    app.include_router(org_routes.router)  # type: ignore[attr-defined]
    app.include_router(key_routes.router)  # type: ignore[attr-defined]
    app.add_middleware(APIKeyMiddleware, enabled=True,  # type: ignore[attr-defined]
                       session_secret=SECRET)
    app.state.sign_in = sessions.SignIn(CLIENT_ID, SECRET, verifier(google_key))  # type: ignore[attr-defined]
    state = app.state.atlas  # type: ignore[attr-defined]
    state.ingest = IngestConfig(root=str(tmp_path))
    state.registry.list_namespaces = AsyncMock(return_value=[])
    done = IndexResult()
    done.documents_processed, done.chunks_indexed = 1, 1
    state.registry.get.return_value.indexer.index_path = AsyncMock(return_value=done)
    (tmp_path / "doc.md").write_text("# hi")
    yield Site(app, ws, google_key)
    auth._windows.clear()
    get_settings.cache_clear()


def _sheets(c: TestClient) -> list[str]:
    return [n["name"] for n in c.get("/namespaces").json()["namespaces"]]


def _ask(c: TestClient, sheet: str, **headers: str) -> int:
    return c.post("/query", json={"query": "q", "namespace": sheet}, headers=headers or CONSOLE
                  ).status_code


class TestSignIn:
    def test_config_hands_out_the_public_client_id(self, site: Site) -> None:
        assert site.browser().get("/auth/config").json() == {
            "enabled": True, "google_client_id": CLIENT_ID}

    def test_an_invited_person_gets_a_locked_down_cookie(self, site: Site) -> None:
        c = site.browser()
        r = c.post("/auth/google", headers=CONSOLE,
                   json={"credential": token(site.key, "Reader@Gmail.com")})
        assert r.status_code == 200, r.text
        cookie = r.headers["set-cookie"].lower()
        for part in ("httponly", "secure", "samesite=lax", "max-age=28800", "path=/"):
            assert part in cookie
        body = r.json()
        assert body["user"]["email"] == "reader@gmail.com"
        assert body["org"] == {"id": "org_a", "name": "Acme"}
        assert body["workspaces"] == [{"name": "docs", "role": "reader"}]
        assert c.get("/auth/me").json()["user"]["email"] == "reader@gmail.com"

    def test_the_invitation_is_used_up_and_the_person_stays(self, site: Site) -> None:
        site.sign_in("reader@gmail.com")
        store = tenancy.get_tenancy()
        assert asyncio.run(store.get_invitation("reader@gmail.com")) is None
        site.sign_in("reader@gmail.com")  # second time: an existing user

    def test_an_uninvited_personal_account_is_refused(self, site: Site) -> None:
        c = site.browser()
        r = c.post("/auth/google", headers=CONSOLE,
                   json={"credential": token(site.key, "stranger@gmail.com")})
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "not_invited"
        assert "set-cookie" not in r.headers

    def test_a_workspace_account_joins_its_domains_organisation_with_no_access(
        self, site: Site
    ) -> None:
        c = site.sign_in("new@acme.com", hd="acme.com")
        me = c.get("/auth/me").json()
        assert me["org"]["id"] == "org_a" and me["workspaces"] == []
        assert _sheets(c) == []
        assert _ask(c, "docs") == 404

    def test_a_claimed_domain_needs_googles_hd_claim_not_just_the_address(
        self, site: Site
    ) -> None:
        # A personal Google account can have any address; only `hd` proves
        # Google manages it for that domain.
        r = site.browser().post("/auth/google", headers=CONSOLE,
                                json={"credential": token(site.key, "new@acme.com")})
        assert r.status_code == 403

    def test_a_bad_token_is_401(self, site: Site, other_key: Key) -> None:
        r = site.browser().post("/auth/google", headers=CONSOLE,
                                json={"credential": token(other_key, "admin@acme.com")})
        assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_token"

    def test_signing_in_from_another_site_is_refused(self, site: Site) -> None:
        r = site.browser().post("/auth/google",
                                json={"credential": token(site.key, "admin@acme.com")})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "csrf"

    def test_sign_in_off_says_so(self, site: Site) -> None:
        site.app.state.sign_in = sessions.SignIn("", "", verifier(site.key))
        c = site.browser()
        assert c.get("/auth/config").json()["enabled"] is False
        r = c.post("/auth/google", headers=CONSOLE,
                   json={"credential": token(site.key, "admin@acme.com")})
        assert r.status_code == 503

    def test_sign_out_clears_the_cookie(self, site: Site) -> None:
        c = site.sign_in("reader@gmail.com")
        assert c.post("/auth/logout", headers=CONSOLE).status_code == 204
        assert c.get("/auth/me").status_code == 401


class TestASignedInPerson:
    def test_sees_and_asks_only_its_own_workspaces(self, site: Site) -> None:
        c = site.sign_in("reader@gmail.com")
        assert _sheets(c) == ["docs"]
        assert _ask(c, "docs") == 200
        assert _ask(c, "hr") == 404             # own organisation, no role
        assert c.get("/namespaces/docs/sources").json()["writable"] is False

    def test_cannot_write_as_a_reader(self, site: Site) -> None:
        c = site.sign_in("reader@gmail.com")
        r = c.post("/ingest", headers=CONSOLE,
                   json={"path": f"{site.app.state.atlas.ingest.root}/doc.md",
                         "namespace": "docs"})
        assert r.status_code == 403

    def test_the_other_organisations_same_name_is_its_own(self, site: Site) -> None:
        a = site.sign_in("admin@acme.com")
        b = site.sign_in("admin@bolt.io")
        _ask(a, "docs")
        _ask(b, "docs")
        corpora = [c.args[0] for c in site.app.state.atlas.registry.get.call_args_list]
        assert {"org_a__docs", "org_b__docs"} <= set(corpora)

    def test_a_cookie_write_without_the_console_header_is_refused(self, site: Site) -> None:
        c = site.sign_in("admin@acme.com")
        r = c.post("/query", json={"query": "q", "namespace": "docs"})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "csrf"

    def test_a_forged_cookie_is_no_one(self, site: Site) -> None:
        c = site.browser()
        c.cookies.set(sessions.COOKIE, sessions.sign_session("usr_x", "guessed"),
                      domain="testserver")
        assert c.get("/auth/me").status_code == 401

    def test_removal_takes_effect_on_the_next_request(self, site: Site) -> None:
        admin = site.sign_in("admin@acme.com")
        reader = site.sign_in("reader@gmail.com")
        uid = reader.get("/auth/me").json()["user"]["id"]
        assert admin.delete(f"/org/members/{uid}", headers=CONSOLE).status_code == 204
        r = reader.get("/namespaces")
        assert r.status_code == 401 and r.json()["detail"]["code"] == "signed_out"

    def test_a_role_change_takes_effect_on_the_next_request(self, site: Site) -> None:
        admin = site.sign_in("admin@acme.com")
        reader = site.sign_in("reader@gmail.com")
        uid = reader.get("/auth/me").json()["user"]["id"]
        r = admin.put(f"/org/members/{uid}", headers=CONSOLE,
                      json={"org_admin": False, "roles": {"docs": "editor", "hr": "reader"}})
        assert r.status_code == 200, r.text
        assert _sheets(reader) == ["docs", "hr"]
        assert reader.get("/namespaces/docs/sources").json()["writable"] is True

    def test_a_tenancy_store_that_cannot_be_read_refuses(
        self, site: Site, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c = site.sign_in("admin@acme.com")

        async def broken(*_: Any) -> Any:
            raise OSError("firestore down")

        monkeypatch.setattr(tenancy.get_tenancy(), "get_subject", broken)
        assert c.get("/namespaces").status_code == 503


# ── The organisation page ────────────────────────────────────────────────────

class TestOrgAdmin:
    def test_shows_its_own_people_and_nobody_elses(self, site: Site) -> None:
        a = site.sign_in("admin@acme.com")
        site.sign_in("admin@bolt.io")
        body = a.get("/org").json()
        assert body["org"]["id"] == "org_a" and body["domain"] == "acme.com"
        assert [m["email"] for m in body["members"]] == ["admin@acme.com"]
        assert body["members"][0]["you"] is True
        assert [i["email"] for i in body["invitations"]] == ["reader@gmail.com"]
        assert body["invitations"][0]["roles"] == {"docs": "reader"}
        assert [w["name"] for w in body["workspaces"]] == ["docs", "hr"]

    def test_only_an_org_admin_may_open_it(self, site: Site) -> None:
        assert site.sign_in("reader@gmail.com").get("/org").status_code == 403

    def test_a_legacy_key_is_not_the_public_organisations_admin(self, site: Site) -> None:
        raw, _ = asyncio.run(auth.create_key("unmigrated"))
        r = site.browser().get("/org", headers={"Authorization": f"Bearer {raw}"})
        assert r.status_code == 403

    def test_invite_then_sign_in(self, site: Site) -> None:
        a = site.sign_in("admin@acme.com")
        r = a.post("/org/invitations", headers=CONSOLE,
                   json={"email": " New@Partner.org ", "roles": {"hr": "editor"}})
        assert r.status_code == 201, r.text
        new = site.sign_in("new@partner.org")
        assert new.get("/auth/me").json()["workspaces"] == [{"name": "hr", "role": "editor"}]

    @pytest.mark.parametrize(("payload", "status", "code"), [
        ({"email": "x@y.org", "roles": {"finance": "reader"}}, 422, "unknown_workspace"),
        ({"email": "not-an-email"}, 422, "bad_email"),
        ({"email": "admin@acme.com"}, 409, "already_member"),
    ])
    def test_invitations_that_cannot_work_are_refused(
        self, site: Site, payload: dict[str, Any], status: int, code: str
    ) -> None:
        a = site.sign_in("admin@acme.com")
        r = a.post("/org/invitations", headers=CONSOLE, json=payload)
        assert r.status_code == status and r.json()["detail"]["code"] == code

    def test_cannot_grant_a_workspace_of_another_organisation(self, site: Site) -> None:
        # B also has "docs"; from A, "docs" can only mean A's.
        a = site.sign_in("admin@acme.com")
        a.post("/org/invitations", headers=CONSOLE,
               json={"email": "x@y.org", "roles": {"docs": "reader"}})
        inv = asyncio.run(tenancy.get_tenancy().get_invitation("x@y.org"))
        assert inv is not None and inv.roles == {site.ws["a/docs"]: Role.READER}

    def test_cannot_take_another_organisations_pending_invitation(self, site: Site) -> None:
        b = site.sign_in("admin@bolt.io")
        r = b.post("/org/invitations", headers=CONSOLE, json={"email": "reader@gmail.com"})
        assert r.status_code == 409
        inv = asyncio.run(tenancy.get_tenancy().get_invitation("reader@gmail.com"))
        assert inv is not None and inv.org_id == "org_a"

    def test_every_change_to_another_organisation_is_not_found(self, site: Site) -> None:
        a = site.sign_in("admin@acme.com")
        b = site.sign_in("admin@bolt.io")
        a_id = a.get("/auth/me").json()["user"]["id"]
        assert b.put(f"/org/members/{a_id}", headers=CONSOLE,
                     json={"org_admin": False}).status_code == 404
        assert b.delete(f"/org/members/{a_id}", headers=CONSOLE).status_code == 404
        assert b.delete("/org/invitations/reader@gmail.com",
                        headers=CONSOLE).status_code == 404
        assert a.get("/auth/me").json()["org_admin"] is True

    def test_an_admin_cannot_lock_itself_out(self, site: Site) -> None:
        a = site.sign_in("admin@acme.com")
        me = a.get("/auth/me").json()["user"]["id"]
        assert a.put(f"/org/members/{me}", headers=CONSOLE,
                     json={"org_admin": False}).status_code == 409
        assert a.delete(f"/org/members/{me}", headers=CONSOLE).status_code == 409

    def test_withdraw_an_invitation(self, site: Site) -> None:
        a = site.sign_in("admin@acme.com")
        assert a.delete("/org/invitations/reader@gmail.com",
                        headers=CONSOLE).status_code == 204
        r = site.browser().post("/auth/google", headers=CONSOLE,
                                json={"credential": token(site.key, "reader@gmail.com")})
        assert r.status_code == 403

    def test_create_a_workspace(self, site: Site) -> None:
        a = site.sign_in("admin@acme.com")
        r = a.post("/org/workspaces", headers=CONSOLE, json={"name": "legal"})
        assert r.status_code == 201, r.text
        assert "legal" in _sheets(a)
        assert _ask(a, "legal") == 200
        corpora = [c.args[0] for c in site.app.state.atlas.registry.get.call_args_list]
        assert corpora[-1] == "org_a__legal"
        assert a.post("/org/workspaces", headers=CONSOLE,
                      json={"name": "legal"}).status_code == 409

    @pytest.mark.parametrize("name", ["Legal", "a__b", "-x", "a b", "x" * 65])
    def test_workspace_names_are_their_own_collection_slug(self, site: Site, name: str) -> None:
        a = site.sign_in("admin@acme.com")
        assert a.post("/org/workspaces", headers=CONSOLE,
                      json={"name": name}).status_code == 422

    def test_a_service_account_reaches_only_its_grants(self, site: Site) -> None:
        a = site.sign_in("admin@acme.com")
        r = a.post("/org/service-accounts", headers=CONSOLE,
                   json={"name": "ci", "roles": {"docs": "reader"}})
        assert r.status_code == 201, r.text
        bearer = {"Authorization": f"Bearer {r.json()['key']}"}
        machine = site.browser()
        assert _ask(machine, "docs", **bearer) == 200
        assert _ask(machine, "hr", **bearer) == 404
        assert [s["name"] for s in a.get("/org").json()["service_accounts"]] == ["ci"]

        key_id = r.json()["key_id"]
        b = site.sign_in("admin@bolt.io")
        assert b.delete(f"/org/service-accounts/{key_id}", headers=CONSOLE).status_code == 404
        assert _ask(machine, "docs", **bearer) == 200
        assert a.delete(f"/org/service-accounts/{key_id}", headers=CONSOLE).status_code == 204
        assert _ask(machine, "docs", **bearer) == 401
        # Revoked, not forgotten: the key never falls back to legacy access.
        assert asyncio.run(tenancy.get_tenancy().get_subject("service", str(key_id)))


class TestBreakGlass:
    def test_needs_the_admin_secret(self, site: Site) -> None:
        r = site.browser().post("/admin/orgs", json={"name": "Corp"})
        assert r.status_code == 403

    def test_first_organisation_and_first_admin(self, site: Site) -> None:
        c = site.browser()
        h = {"X-Admin-Secret": "s3cret"}
        org = c.post("/admin/orgs", headers=h, json={"name": "Corp", "domain": "Corp.example"})
        assert org.status_code == 201, org.text
        assert org.json()["domain"] == "corp.example"
        assert c.post("/admin/orgs", headers=h, json={"name": "Copy", "domain": "corp.example"}
                      ).status_code == 409
        org_id = org.json()["id"]
        assert c.post("/admin/invitations", headers=h,
                      json={"org_id": org_id, "email": "boss@corp.example"}).status_code == 201
        me = site.sign_in("boss@corp.example").get("/auth/me").json()
        assert me["org"]["id"] == org_id and me["org_admin"] is True

    def test_cannot_invite_into_an_organisation_that_does_not_exist(self, site: Site) -> None:
        r = site.browser().post("/admin/invitations", headers={"X-Admin-Secret": "s3cret"},
                                json={"org_id": "org_nope", "email": "x@y.org"})
        assert r.status_code == 404
