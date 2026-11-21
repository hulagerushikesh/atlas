"""Tenancy model, both stores, migration, and the principal on every request (E1.1)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from atlas.api import auth, tenancy
from atlas.api.dependencies import get_principal
from atlas.api.middleware.auth_mw import APIKeyMiddleware
from atlas.api.routes import keys
from atlas.api.tenancy import (
    PUBLIC_ORG_ID,
    FirestoreTenancyStore,
    Principal,
    Role,
    SQLiteTenancyStore,
    Subject,
    TenancyStore,
    Workspace,
    WorkspaceNameTaken,
    find_workspace,
    grant,
    legacy_workspace_id,
    migrate,
)
from atlas.config import get_settings

# ── A Firestore fake that understands where(filter=FieldFilter) ──────────────

class _Snap:
    def __init__(self, doc_id: str, data: dict[str, Any] | None) -> None:
        self.id, self._data = doc_id, data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return None if self._data is None else dict(self._data)


class _Doc:
    def __init__(self, docs: dict[str, dict[str, Any]], doc_id: str) -> None:
        self._docs, self.id = docs, doc_id

    async def set(self, data: dict[str, Any]) -> None:
        self._docs[self.id] = dict(data)

    async def get(self) -> _Snap:
        return _Snap(self.id, self._docs.get(self.id))


class _Query:
    def __init__(self, docs: dict[str, dict[str, Any]], filters: tuple[Any, ...] = (),
                 limit: int | None = None) -> None:
        self._docs, self._filters, self._limit = docs, filters, limit

    def where(self, *, filter: Any) -> _Query:  # noqa: A002 -- the real keyword
        assert filter.op_string == "=="
        return _Query(self._docs, (*self._filters, filter), self._limit)

    def limit(self, n: int) -> _Query:
        return _Query(self._docs, self._filters, n)

    async def get(self) -> list[_Snap]:
        hits = [(k, v) for k, v in self._docs.items()
                if all(v.get(f.field_path) == f.value for f in self._filters)]
        return [_Snap(k, v) for k, v in hits[: self._limit]]


class _Collection(_Query):
    def document(self, doc_id: str) -> _Doc:
        return _Doc(self._docs, doc_id)


class _FakeClient:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, dict[str, Any]]] = {}

    def collection(self, name: str) -> _Collection:
        return _Collection(self.collections.setdefault(name, {}))


@pytest.fixture(params=["sqlite", "firestore"])
async def store(request: pytest.FixtureRequest, tmp_path: Path) -> TenancyStore:
    s: TenancyStore
    if request.param == "sqlite":
        s = SQLiteTenancyStore(tmp_path / "t.db")
    else:
        s = FirestoreTenancyStore(client=_FakeClient())
    await s.init()
    return s


# ── Roles and principals ─────────────────────────────────────────────────────

_WS = Workspace(id="ws_a", org_id="org_a", name="docs", collection="atlas_org_a__docs")


class TestPrincipal:
    @pytest.mark.parametrize(("role", "read", "write", "manage"), [
        (Role.READER, True, False, False),
        (Role.EDITOR, True, True, False),
        (Role.ADMIN, True, True, True),
    ])
    def test_each_role_allows_what_it_says(
        self, role: Role, read: bool, write: bool, manage: bool
    ) -> None:
        p = Principal(kind="user", org_id="org_a", roles={"ws_a": role})
        assert (p.can(_WS, "read"), p.can(_WS, "write"), p.can(_WS, "manage")) == (
            read, write, manage)

    def test_no_role_is_no_access(self) -> None:
        assert not Principal(kind="user", org_id="org_a").can(_WS, "read")

    def test_org_admin_is_admin_on_every_workspace_in_it(self) -> None:
        assert Principal(kind="user", org_id="org_a", org_admin=True).can(_WS, "manage")

    def test_another_organisation_never_gets_in_whatever_it_holds(self) -> None:
        p = Principal(kind="user", org_id="org_b", org_admin=True, roles={"ws_a": Role.ADMIN})
        assert not p.can(_WS, "read")

    def test_legacy_keeps_todays_access(self) -> None:
        assert tenancy.legacy_key_principal(7).can(_WS, "write")

    def test_visitor_reads_only_the_demo_workspace(self) -> None:
        p = tenancy.visitor_principal("demo:1.1.1.1", _WS)
        other = Workspace(id="ws_b", org_id="org_a", name="hr", collection="atlas_hr")
        assert p.can(_WS, "read") and not p.can(_WS, "write") and not p.can(other, "read")

    def test_visitor_without_a_demo_workspace_gets_nothing(self) -> None:
        assert not tenancy.visitor_principal("demo:x", None).can(_WS, "read")


def test_new_collections_are_namespaced_by_organisation() -> None:
    assert tenancy.new_collection_name("org_a", "Eng Docs") == "atlas_org_a__eng-docs"
    with pytest.raises(ValueError):
        tenancy.slug("   ")


# ── Both stores ──────────────────────────────────────────────────────────────

class TestStore:
    async def test_org_with_a_fixed_id_is_created_once(self, store: TenancyStore) -> None:
        a = await store.create_org("Public", org_id="org_x")
        b = await store.create_org("Renamed", org_id="org_x")
        assert a == b and (await store.get_org("org_x")) == a
        assert await store.get_org("org_missing") is None

    async def test_two_organisations_may_both_have_docs(self, store: TenancyStore) -> None:
        a = await store.create_org("A")
        b = await store.create_org("B")
        wa = await store.create_workspace(a.id, "docs")
        wb = await store.create_workspace(b.id, "docs")
        assert wa.id != wb.id and wa.collection != wb.collection
        assert [w.id for w in await store.list_workspaces(a.id)] == [wa.id]

    async def test_a_name_is_unique_inside_one_organisation(self, store: TenancyStore) -> None:
        org = await store.create_org("A")
        await store.create_workspace(org.id, "docs")
        with pytest.raises(WorkspaceNameTaken):
            await store.create_workspace(org.id, "docs")

    async def test_another_orgs_workspace_is_not_found_by_name(
        self, store: TenancyStore
    ) -> None:
        a, b = await store.create_org("A"), await store.create_org("B")
        await store.create_workspace(a.id, "secret")
        assert await find_workspace(store, b.id, "secret") is None
        assert (await find_workspace(store, a.id, "secret")) is not None

    async def test_workspace_with_a_fixed_id_keeps_its_collection(
        self, store: TenancyStore
    ) -> None:
        org = await store.create_org("P", org_id="org_p")
        ws = await store.create_workspace(org.id, "duckdb", collection="atlas_duckdb",
                                          workspace_id="ws_public_duckdb")
        again = await store.create_workspace(org.id, "duckdb", workspace_id="ws_public_duckdb")
        assert again == ws and ws.collection == "atlas_duckdb"
        assert await store.get_workspace("ws_nope") is None

    async def test_users_are_found_by_email_whatever_its_case(
        self, store: TenancyStore
    ) -> None:
        org = await store.create_org("A")
        user = await store.create_user(org.id, "Ana@Example.com", "Ana")
        assert await store.find_user("ana@example.COM ") == user
        assert await store.find_user("nobody@example.com") is None

    async def test_subject_roundtrips_and_replaces(self, store: TenancyStore) -> None:
        org = await store.create_org("A")
        ws = await store.create_workspace(org.id, "docs")
        s = Subject(kind="service", id="42", org_id=org.id, roles={ws.id: Role.EDITOR})
        await store.put_subject(s)
        assert await store.get_subject("service", "42") == s
        await store.put_subject(Subject(kind="service", id="42", org_id=org.id, org_admin=True))
        got = await store.get_subject("service", "42")
        assert got is not None and got.org_admin and got.roles == {}
        assert await store.get_subject("user", "42") is None

    async def test_grant_adds_a_role(self, store: TenancyStore) -> None:
        org = await store.create_org("A")
        w1 = await store.create_workspace(org.id, "one")
        w2 = await store.create_workspace(org.id, "two")
        await grant(store, "user", "u1", org.id, w1.id, Role.READER)
        s = await grant(store, "user", "u1", org.id, w2.id, Role.ADMIN)
        assert s.roles == {w1.id: Role.READER, w2.id: Role.ADMIN}

    async def test_grant_refuses_another_orgs_workspace(self, store: TenancyStore) -> None:
        a, b = await store.create_org("A"), await store.create_org("B")
        wb = await store.create_workspace(b.id, "docs")
        with pytest.raises(ValueError):
            await grant(store, "user", "u1", a.id, wb.id, Role.READER)

    async def test_grant_refuses_a_subject_from_another_org(self, store: TenancyStore) -> None:
        a, b = await store.create_org("A"), await store.create_org("B")
        wa, wb = await store.create_workspace(a.id, "x"), await store.create_workspace(b.id, "x")
        await grant(store, "user", "u1", a.id, wa.id, Role.READER)
        with pytest.raises(ValueError):
            await grant(store, "user", "u1", b.id, wb.id, Role.READER)


def test_unknown_backend_raises() -> None:
    with pytest.raises(ValueError):
        tenancy.build_tenancy_store("postgres")


def test_firestore_backend_builds_without_a_client() -> None:
    assert isinstance(tenancy.build_tenancy_store("firestore"), FirestoreTenancyStore)


# ── Migration ────────────────────────────────────────────────────────────────

class TestMigration:
    async def test_dry_run_writes_nothing(self, store: TenancyStore) -> None:
        report = await migrate(store, ["duckdb", "fastapi"], [1, 2], apply=False)
        assert report.org_created and report.workspaces_created == ["duckdb", "fastapi"]
        assert report.keys_granted == 2
        assert await store.get_org(PUBLIC_ORG_ID) is None
        assert await store.get_subject("service", "1") is None

    async def test_every_key_keeps_access_to_every_existing_set(
        self, store: TenancyStore
    ) -> None:
        await migrate(store, ["duckdb", "fastapi"], [1, "abc"], apply=True)
        for ns in ("duckdb", "fastapi"):
            ws = await store.get_workspace(legacy_workspace_id(ns))
            assert ws is not None and ws.collection == f"atlas_{ns}"
            for key in ("1", "abc"):
                subject = await store.get_subject("service", key)
                assert subject is not None
                p = tenancy.principal_from_subject(subject)
                assert p.can(ws, "read") and p.can(ws, "write") and not p.can(ws, "manage")

    async def test_rerunning_changes_nothing(self, store: TenancyStore) -> None:
        await migrate(store, ["duckdb"], [1], apply=True)
        again = await migrate(store, ["duckdb"], [1], apply=True)
        assert not again.org_created and again.workspaces_kept == ["duckdb"]
        assert again.keys_granted == 0 and again.keys_already_done == 1

    async def test_a_set_added_later_is_granted_on_rerun(self, store: TenancyStore) -> None:
        await migrate(store, ["duckdb"], [1], apply=True)
        report = await migrate(store, ["duckdb", "new"], [1, 2], apply=True)
        assert report.workspaces_created == ["new"] and report.keys_granted == 2
        s = await store.get_subject("service", "1")
        assert s is not None and set(s.roles) == {"ws_public_duckdb", "ws_public_new"}

    async def test_grants_made_since_are_kept(self, store: TenancyStore) -> None:
        await migrate(store, ["duckdb"], [1], apply=True)
        await grant(store, "service", "1", PUBLIC_ORG_ID, "ws_public_duckdb", Role.ADMIN)
        await migrate(store, ["duckdb"], [1], apply=True)
        s = await store.get_subject("service", "1")
        assert s is not None and s.roles["ws_public_duckdb"] is Role.ADMIN

    async def test_a_key_moved_to_another_org_is_left_alone(self, store: TenancyStore) -> None:
        await store.put_subject(Subject(kind="service", id="9", org_id="org_other"))
        report = await migrate(store, ["duckdb"], [9], apply=True)
        assert report.keys_skipped_other_org == 1
        s = await store.get_subject("service", "9")
        assert s is not None and s.org_id == "org_other" and s.roles == {}


# ── Principal on every request ───────────────────────────────────────────────

@pytest.fixture
def who(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ADMIN_SECRET", "s3cret")
    get_settings.cache_clear()
    key_store = auth.configure_store("sqlite", sqlite_path=tmp_path / "k.db")
    asyncio.run(key_store.init())
    auth._windows.clear()

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware, enabled=True)
    app.include_router(keys.router)

    @app.get("/whoami")
    async def whoami(request: Request) -> dict[str, Any]:
        p = get_principal(request)
        return {"kind": p.kind, "org": p.org_id, "legacy": p.legacy,
                "roles": {k: v.value for k, v in p.roles.items()}}

    @app.get("/out/whoami")
    async def public_whoami(request: Request) -> dict[str, Any]:
        return await whoami(request)

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def _mint(client: TestClient) -> tuple[str, str]:
    r = client.post("/keys", headers={"X-Admin-Secret": "s3cret"}, json={"name": "t"})
    assert r.status_code == 201, r.text
    return r.json()["key"], str(r.json()["key_id"])


class TestEveryRequestCarriesAPrincipal:
    def test_an_unmigrated_key_is_legacy_with_todays_access(self, who: TestClient) -> None:
        raw, _ = _mint(who)
        body = who.get("/whoami", headers={"Authorization": f"Bearer {raw}"}).json()
        assert body == {"kind": "service", "org": "", "legacy": True, "roles": {}}

    def test_a_migrated_key_carries_its_organisation_and_roles(self, who: TestClient) -> None:
        raw, key_id = _mint(who)
        asyncio.run(migrate(tenancy.get_tenancy(), ["duckdb"], [key_id], apply=True))
        body = who.get("/whoami", headers={"Authorization": f"Bearer {raw}"}).json()
        assert body == {"kind": "service", "org": PUBLIC_ORG_ID, "legacy": False,
                        "roles": {"ws_public_duckdb": "editor"}}

    def test_a_public_path_carries_an_anonymous_non_legacy_caller(
        self, who: TestClient
    ) -> None:
        body = who.get("/out/whoami").json()
        assert body["kind"] == "anonymous" and body["legacy"] is False

    def test_a_store_failure_keeps_the_request_working(
        self, who: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        raw, _ = _mint(who)

        async def broken(*_: object) -> None:
            raise RuntimeError("firestore down")

        monkeypatch.setattr(tenancy.get_tenancy(), "get_subject", broken)
        r = who.get("/whoami", headers={"Authorization": f"Bearer {raw}"})
        assert r.status_code == 200 and r.json()["legacy"] is True


def test_with_auth_off_the_caller_is_the_dev_box() -> None:
    app = FastAPI()
    app.add_middleware(APIKeyMiddleware, enabled=False)

    @app.get("/whoami")
    async def whoami(request: Request) -> dict[str, Any]:
        p = get_principal(request)
        return {"kind": p.kind, "legacy": p.legacy}

    with TestClient(app) as c:
        assert c.get("/whoami").json() == {"kind": "anonymous", "legacy": True}


async def test_a_visitor_is_reader_on_the_migrated_demo_workspace() -> None:
    await migrate(tenancy.get_tenancy(), ["duckdb"], [], apply=True)
    p = await tenancy.principal_for_visitor("demo:1.1.1.1", "duckdb")
    assert p.kind == "visitor" and p.roles == {"ws_public_duckdb": Role.READER}
    nobody = await tenancy.principal_for_visitor("demo:1.1.1.1", "unmigrated")
    assert nobody.roles == {}
