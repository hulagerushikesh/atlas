"""Isolation suite (E1.2): two organisations on one deployment, every route,
both directions.

Organisation A has "docs" and "hr"; organisation B has "docs" and "finance".
Each has one editor key, on its own "docs" only; A also has a reader key.
Beside them: an unmigrated key (legacy, the public organisation) and a keyless
visitor on the demo sheet. Every workspace route is tried by every caller
against every workspace it should not reach, and must answer exactly what a
workspace that does not exist answers.

The route matrix is checked against `authz.POLICY`, so a workspace route
added later fails here until it is in the matrix.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route

from atlas.api import auth, tenancy
from atlas.api.authz import POLICY, is_public
from atlas.api.budget import SpendMeter
from atlas.api.middleware.auth_mw import APIKeyMiddleware
from atlas.api.middleware.metrics_mw import REQUEST_COUNT, PrometheusMiddleware
from atlas.api.routes import keys as key_routes
from atlas.api.tenancy import Role
from atlas.config import IngestConfig
from atlas.ingestion.indexer import IndexResult

DEMO = "duckdb"


@dataclass
class World:
    client: TestClient
    keys: dict[str, str]          # caller -> raw key
    ws: dict[str, str]            # "a/docs" -> workspace id

    def h(self, who: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.keys[who]}"} if who in self.keys else {}

    def corpora(self) -> list[str]:
        """Every corpus the registry was asked for, in order."""
        registry = self.client.app.state.atlas.registry  # type: ignore[attr-defined]
        return [c.args[0] for c in registry.get.call_args_list]


def _indexed() -> IndexResult:
    r = IndexResult()
    r.documents_processed, r.documents_skipped, r.chunks_indexed, r.total_tokens = 1, 0, 1, 10
    return r


@pytest.fixture
def world(client: TestClient, tmp_path: Path) -> Iterator[World]:
    asyncio.run(auth.configure_store("sqlite", sqlite_path=tmp_path / "k.db").init())
    auth._windows.clear()
    store = tenancy.get_tenancy()

    async def build() -> tuple[dict[str, str], dict[str, str]]:
        ws: dict[str, str] = {}
        for org in ("org_a", "org_b"):
            await store.create_org(org.upper(), org_id=org)
        for org, name in (("org_a", "docs"), ("org_a", "hr"),
                          ("org_b", "docs"), ("org_b", "finance")):
            w = await store.create_workspace(org, name)
            ws[f"{org[-1]}/{name}"] = w.id
        keys: dict[str, str] = {}
        for who, org, target, role in (("a", "org_a", "a/docs", Role.EDITOR),
                                       ("b", "org_b", "b/docs", Role.EDITOR),
                                       ("a_reader", "org_a", "a/docs", Role.READER)):
            raw, key_id = await auth.create_key(who)
            await tenancy.grant(store, "service", str(key_id), org, ws[target], role)
            keys[who] = raw
        keys["legacy"], _ = await auth.create_key("unmigrated")
        return keys, ws

    keys, ws = asyncio.run(build())
    app = client.app
    app.include_router(key_routes.router)  # type: ignore[attr-defined]
    app.add_middleware(APIKeyMiddleware, enabled=True)  # type: ignore[attr-defined]
    app.add_middleware(PrometheusMiddleware)  # type: ignore[attr-defined]
    state = app.state.atlas  # type: ignore[attr-defined]
    state.demo_namespace = DEMO
    state.demo_spend = SpendMeter(budget_usd=1.0, scope="demo", parent=state.spend)
    state.ingest = IngestConfig(root=str(tmp_path))
    state.registry.list_namespaces = AsyncMock(
        return_value=["default", DEMO, "org_a__docs", "org_a__hr", "org_b__docs",
                      "org_b__finance"])
    state.registry.get.return_value.indexer.index_directory = AsyncMock(return_value=_indexed())
    state.registry.get.return_value.indexer.index_path = AsyncMock(return_value=_indexed())
    (tmp_path / "doc.md").write_text("# hi")
    yield World(client, keys, ws)
    auth._windows.clear()


# ── Every workspace route, one way to call it ────────────────────────────────

Call = Callable[[World, str, str], httpx.Response]


def _query(w: World, who: str, name: str) -> httpx.Response:
    return w.client.post("/query", json={"query": "what is here?", "namespace": name},
                         headers=w.h(who))


def _sources(w: World, who: str, name: str) -> httpx.Response:
    return w.client.get(f"/namespaces/{name}/sources", headers=w.h(who))


def _ingest(w: World, who: str, name: str) -> httpx.Response:
    root = w.client.app.state.atlas.ingest.root  # type: ignore[attr-defined]
    return w.client.post("/ingest", json={"path": f"{root}/doc.md", "namespace": name},
                         headers=w.h(who))


def _upload(w: World, who: str, name: str) -> httpx.Response:
    return w.client.post("/ingest/upload", data={"namespace": name}, headers=w.h(who),
                         files=[("files", ("n.md", b"# n", "text/markdown"))])


def _document_access(w: World, who: str, name: str) -> httpx.Response:
    return w.client.put(f"/namespaces/{name}/documents/access", headers=w.h(who),
                        json={"source": "n.md", "everyone": True})


def _read_document_access(w: World, who: str, name: str) -> httpx.Response:
    return w.client.get(f"/namespaces/{name}/documents/access", params={"source": "n.md"},
                        headers=w.h(who))


def _remove_document(w: World, who: str, name: str) -> httpx.Response:
    return w.client.delete(f"/namespaces/{name}/documents", params={"source": "n.md"},
                           headers=w.h(who))


def _drive_status(w: World, who: str, name: str) -> httpx.Response:
    return w.client.get(f"/namespaces/{name}/connectors/drive", headers=w.h(who))


def _drive_folder(w: World, who: str, name: str) -> httpx.Response:
    return w.client.put(f"/namespaces/{name}/connectors/drive", headers=w.h(who),
                        json={"folder": "https://drive.google.com/drive/folders/abcdefghijkl"})


def _drive_sync(w: World, who: str, name: str) -> httpx.Response:
    return w.client.post(f"/namespaces/{name}/connectors/drive/sync", headers=w.h(who))


def _drive_disconnect(w: World, who: str, name: str) -> httpx.Response:
    return w.client.delete(f"/namespaces/{name}/connectors/drive", headers=w.h(who))


# E3.1's routes act on a sheet's connection record, not on its corpus, so
# "which workspace did it open" is read from the records instead.
DRIVE_ROUTES: dict[tuple[str, str], Call] = {
    ("GET", "/namespaces/{namespace}/connectors/drive"): _drive_status,
    ("PUT", "/namespaces/{namespace}/connectors/drive"): _drive_folder,
    ("POST", "/namespaces/{namespace}/connectors/drive/sync"): _drive_sync,
    ("DELETE", "/namespaces/{namespace}/connectors/drive"): _drive_disconnect,
}

ROUTES: dict[tuple[str, str], Call] = {
    ("POST", "/query"): _query,
    ("GET", "/namespaces/{namespace}/sources"): _sources,
    ("POST", "/ingest"): _ingest,
    ("POST", "/ingest/upload"): _upload,
    ("GET", "/namespaces/{namespace}/documents/access"): _read_document_access,
    ("PUT", "/namespaces/{namespace}/documents/access"): _document_access,
    ("DELETE", "/namespaces/{namespace}/documents"): _remove_document,
    **DRIVE_ROUTES,
}
WRITES = {k for k, rule in POLICY.items() if rule == "write"}


def test_every_workspace_route_is_in_this_suite() -> None:
    workspace_routes = {k for k, rule in POLICY.items() if rule in ("read", "write", "manage")}
    assert workspace_routes == set(ROUTES)


# Names a caller must never reach: another organisation's workspace by its
# name and by its raw collection name, a workspace of its own organisation it
# holds no role on, and one that does not exist anywhere.
OUT_OF_REACH = {
    "a": ["finance", "org_b__finance", "org_b__docs", "hr"],
    "b": ["hr", "org_a__hr", "org_a__docs"],
    "a_reader": ["finance", "org_b__docs", "hr"],
    "legacy": ["org_a__docs", "org_b__finance"],
}


@pytest.mark.parametrize("route", list(ROUTES), ids=lambda r: f"{r[0]} {r[1]}")
@pytest.mark.parametrize(("who", "name"), [
    (who, name) for who, names in OUT_OF_REACH.items() for name in names])
def test_no_caller_reaches_a_workspace_it_has_no_role_on(
    world: World, route: tuple[str, str], who: str, name: str
) -> None:
    r = ROUTES[route](world, who, name)
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["code"] == "workspace_not_found"
    assert not any("org_" in c for c in world.corpora()), "a corpus was opened anyway"


@pytest.mark.parametrize("route", list(ROUTES), ids=lambda r: f"{r[0]} {r[1]}")
def test_out_of_reach_reads_exactly_like_nonexistent(
    world: World, route: tuple[str, str]
) -> None:
    # Different answers would let A learn which names B uses.
    other = ROUTES[route](world, "a", "finance").json()
    missing = ROUTES[route](world, "a", "no-such-sheet").json()
    assert other["detail"]["code"] == missing["detail"]["code"] == "workspace_not_found"
    assert other["detail"]["message"].replace("finance", "X") == (
        missing["detail"]["message"].replace("no-such-sheet", "X"))


@pytest.mark.parametrize("route", [r for r in ROUTES if r not in DRIVE_ROUTES],
                         ids=lambda r: f"{r[0]} {r[1]}")
@pytest.mark.parametrize(("who", "corpus"), [("a", "org_a__docs"), ("b", "org_b__docs")])
def test_the_same_name_opens_each_callers_own_workspace(
    world: World, route: tuple[str, str], who: str, corpus: str
) -> None:
    r = ROUTES[route](world, who, "docs")
    assert r.status_code == 200, r.text
    assert set(world.corpora()) == {corpus}


@pytest.mark.parametrize("route", list(DRIVE_ROUTES), ids=lambda r: f"{r[0]} {r[1]}")
@pytest.mark.parametrize("who", ["a", "b"])
def test_drive_routes_act_on_each_callers_own_connection(
    world: World, route: tuple[str, str], who: str
) -> None:
    store = tenancy.get_tenancy()
    for org in ("a", "b"):
        ws = world.ws[f"{org}/docs"]
        asyncio.run(store.put_record("drive", ws, f"org_{org}", {
            "workspace_id": ws, "org_id": f"org_{org}", "token": "sealed",
            "folder_id": f"folder_{org}", "files": {}}))
    r = DRIVE_ROUTES[route](world, who, "docs")
    assert r.status_code in (200, 202), r.text
    other = "b" if who == "a" else "a"
    mine = asyncio.run(store.get_record("drive", world.ws[f"{who}/docs"]))
    theirs = asyncio.run(store.get_record("drive", world.ws[f"{other}/docs"]))
    assert theirs is not None and theirs["folder_id"] == f"folder_{other}"
    if route[0] == "GET":
        assert r.json()["folder_id"] == f"folder_{who}"
    elif route[0] == "PUT":
        assert mine is not None and mine["folder_id"] == "abcdefghijkl"
    elif route[0] == "DELETE":
        assert mine is None


@pytest.mark.parametrize("route", sorted(WRITES), ids=lambda r: f"{r[0]} {r[1]}")
def test_a_reader_cannot_write_its_own_workspace(world: World, route: tuple[str, str]) -> None:
    r = ROUTES[route](world, "a_reader", "docs")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "forbidden"


def test_a_reader_can_ask_and_is_told_it_cannot_add(world: World) -> None:
    assert _query(world, "a_reader", "docs").status_code == 200
    assert _sources(world, "a_reader", "docs").json()["writable"] is False
    assert _sources(world, "a", "docs").json()["writable"] is True


def test_an_unmigrated_key_keeps_the_public_organisation(world: World) -> None:
    # Today's access, unchanged: any public sheet, read and write.
    assert _query(world, "legacy", "default").status_code == 200
    assert _upload(world, "legacy", "default").status_code == 200
    # "docs" means the public "docs" to it, never organisation A's.
    assert _sources(world, "legacy", "docs").status_code == 200
    assert "org_a__docs" not in world.corpora()


# ── Listings ─────────────────────────────────────────────────────────────────

def _listed(w: World, who: str) -> list[str]:
    r = w.client.get("/namespaces", headers=w.h(who))
    assert r.status_code == 200, r.text
    return [n["name"] for n in r.json()["namespaces"]]


@pytest.mark.parametrize(("who", "expected"), [
    ("a", ["docs"]),
    ("b", ["docs"]),
    ("a_reader", ["docs"]),
    ("legacy", ["default", DEMO]),
    ("visitor", [DEMO]),
])
def test_each_caller_lists_only_what_it_can_open(
    world: World, who: str, expected: list[str]
) -> None:
    assert _listed(world, who) == expected


def test_a_listing_shows_the_callers_own_collection(world: World) -> None:
    r = world.client.get("/namespaces", headers=world.h("b"))
    assert r.json()["namespaces"] == [{"name": "docs", "collection": "atlas_org_b__docs"}]


def test_an_org_admin_lists_every_workspace_of_its_organisation(world: World) -> None:
    store = tenancy.get_tenancy()
    raw, key_id = asyncio.run(auth.create_key("admin"))
    asyncio.run(store.put_subject(tenancy.Subject(
        kind="service", id=str(key_id), org_id="org_b", org_admin=True)))
    world.keys["b_admin"] = raw
    assert _listed(world, "b_admin") == ["docs", "finance"]
    assert _sources(world, "b_admin", "hr").status_code == 404


def test_without_a_key_or_a_demo_sheet_listings_are_closed(world: World) -> None:
    world.client.app.state.atlas.demo_namespace = ""  # type: ignore[attr-defined]
    assert world.client.get("/namespaces").status_code == 401
    assert world.client.get("/namespaces/default/sources").status_code == 401


def test_a_visitor_sees_the_demo_sheet_and_nothing_else(world: World) -> None:
    assert _sources(world, "visitor", DEMO).status_code == 200
    assert _sources(world, "visitor", DEMO).json()["writable"] is False
    assert _sources(world, "visitor", "default").status_code == 404
    assert _sources(world, "visitor", "org_a__docs").status_code == 404


def test_a_visitor_cannot_write_even_the_demo_sheet(world: World) -> None:
    assert _upload(world, "visitor", DEMO).status_code == 401


# ── Answers, usage and logs ──────────────────────────────────────────────────

def test_one_organisations_cached_answer_is_never_served_to_another(world: World) -> None:
    pipeline = world.client.app.state.atlas.registry.get.return_value.pipeline  # type: ignore[attr-defined]
    first = _query(world, "a", "docs")
    assert first.status_code == 200 and first.json()["cached"] is False
    again = _query(world, "a", "docs")
    assert again.json()["cached"] is True
    other = _query(world, "b", "docs")
    assert other.json()["cached"] is False
    assert pipeline.run.await_count == 2


def test_usage_is_the_callers_own(world: World) -> None:
    _query(world, "a", "docs")
    b = world.client.get("/usage", headers=world.h("b")).json()
    assert b["total_queries"] == 0 and b["by_namespace"] == []


def test_public_metrics_name_no_workspace(world: World) -> None:
    _sources(world, "b", "finance")
    _sources(world, "a", "docs")
    labels = {s.labels.get("path", "") for m in REQUEST_COUNT.collect() for s in m.samples}
    assert "/namespaces/{namespace}/sources" in labels
    assert not any("finance" in p or "docs/sources" in p for p in labels)


# ── Failure closes, never opens ──────────────────────────────────────────────

@pytest.mark.parametrize("route", list(ROUTES), ids=lambda r: f"{r[0]} {r[1]}")
def test_a_store_that_cannot_be_read_refuses(
    world: World, route: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_: Any) -> Any:
        raise RuntimeError("firestore down")

    monkeypatch.setattr(tenancy.get_tenancy(), "list_workspaces", broken)
    r = ROUTES[route](world, "a", "docs")
    assert r.status_code == 503
    assert world.client.get("/namespaces", headers=world.h("a")).status_code == 503


def test_a_visitor_lookup_that_fails_refuses(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_: Any) -> Any:
        raise RuntimeError("firestore down")

    monkeypatch.setattr(tenancy.get_tenancy(), "get_workspace", broken)
    assert _query(world, "visitor", DEMO).status_code == 503


# ── The policy table covers every route ──────────────────────────────────────

def _walk(routes: list[Any], prefix: str = "") -> Iterator[tuple[str, str]]:
    for r in routes:
        # FastAPI keeps an included router as one node; its routes are inside.
        if (inner := getattr(r, "original_router", None)) is not None:
            yield from _walk(inner.routes, prefix + r.include_context.prefix)
        elif isinstance(r, Route):  # APIRoute is one; static mounts are not
            yield from ((m, prefix + r.path) for m in (r.methods or set()) if m != "HEAD")


def _served() -> set[tuple[str, str]]:
    from atlas.api.app import create_app

    return set(_walk(create_app().routes))


def test_the_walk_finds_the_api_routes() -> None:
    # Without this, a walk that found nothing would pass the two tests below.
    assert {("POST", "/query"), ("PATCH", "/keys/{key_id}"), ("GET", "/usage")} <= _served()


def test_every_route_the_app_serves_has_a_policy() -> None:
    missing = _served() - set(POLICY)
    assert not missing, f"add these to authz.POLICY: {sorted(missing)}"


def test_the_policy_names_no_route_that_is_gone() -> None:
    # "/", "/app" and "/privacy" exist only when the console build is present.
    optional = {("GET", "/"), ("GET", "/app"), ("GET", "/privacy")}
    stale = set(POLICY) - _served() - optional
    assert not stale, f"remove from authz.POLICY: {sorted(stale)}"


@pytest.mark.parametrize(("key", "rule"), sorted(POLICY.items()))
def test_the_middleware_lets_through_exactly_what_the_table_calls_public(
    key: tuple[str, str], rule: str
) -> None:
    path = (key[1].replace("{key_id}", "7").replace("{namespace}", "docs")
            .replace("{email}", "x@y.z").replace("{user_id}", "usr_1"))
    assert is_public(path) is (rule in ("public", "admin_secret"))
