"""
E4: personal keys, and Atlas as an MCP server.

The MCP calls go through the real SDK client over the app's ASGI interface,
the auth middleware included, so the transport, the key check and each
tool's access check are tested together.
"""

# ruff: noqa: F811 -- the sign-in suite's fixtures are imported, then used as arguments

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.routing import Route

from atlas.access import reader_access
from atlas.api import mcp_server, personal_keys, tenancy
from atlas.api.routes import me
from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.pipeline import RetrievalPass
from tests.unit.api.test_sign_in import (  # noqa: F401 -- pytest fixtures
    CONSOLE,
    Site,
    google_key,
    site,
)


@pytest.fixture
def mcp_site(site: Site) -> Site:
    site.app.include_router(me.router)
    server, asgi = mcp_server.build()
    site.app.state.mcp = server
    site.app.router.routes.append(Route("/mcp", endpoint=asgi, methods=["GET", "POST", "DELETE"]))
    seen: list[frozenset[str] | None] = []

    async def retrieve(queries: list[str], original: str) -> RetrievalPass:
        seen.append(reader_access())
        meta = ChunkMetadata(doc_id="d1", source="Leave policy", doc_type=DocumentType.MARKDOWN,
                             chunk_index=0, start_char=0, end_char=20)
        return RetrievalPass(chunks=[RetrievedChunk(chunk_id="c1", content="Twenty days a year.",
                                                    score=1.0, metadata=meta)], evidence=[])

    state = site.app.state.atlas
    state.registry.get.return_value.pipeline._retrieve_all = AsyncMock(side_effect=retrieve)
    site.app.state.mcp_seen = seen
    return site


def _key(site: Site, email: str = "admin@acme.com") -> str:
    r = site.sign_in(email).post("/me/keys", headers=CONSOLE, json={"name": "Claude Code"})
    assert r.status_code == 201, r.text
    return str(r.json()["key"])


async def _session_calls(site: Site, headers: dict[str, str],
                         calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    out: list[Any] = []
    transport = httpx.ASGITransport(app=site.app)
    async with (site.app.state.mcp.session_manager.run(),
                httpx.AsyncClient(transport=transport, base_url="https://testserver",
                                  headers=headers) as http,
                streamable_http_client("https://testserver/mcp", http_client=http) as (
                    read, write, *_),
                ClientSession(read, write) as session):
        await session.initialize()
        for name, args in calls:
            if name == "tools":
                out.append([t.name for t in (await session.list_tools()).tools])
            else:
                out.append(await session.call_tool(name, args))
    return out


def _calls(site: Site, key: str, calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    return asyncio.run(_session_calls(site, {"Authorization": f"Bearer {key}"}, calls))


def _text(result: Any) -> str:
    return " ".join(getattr(c, "text", "") for c in result.content)


class TestPersonalKeys:
    def test_a_person_makes_lists_and_revokes_a_key(self, mcp_site: Site) -> None:
        admin = mcp_site.sign_in("admin@acme.com")
        made = admin.post("/me/keys", headers=CONSOLE, json={"name": "Claude Code"}).json()
        listed = admin.get("/me/keys").json()["keys"]
        assert [k["name"] for k in listed] == ["Claude Code"] and "key" not in listed[0]
        bearer = {"Authorization": f"Bearer {made['key']}"}
        assert mcp_site.browser().get("/namespaces", headers=bearer).status_code == 200
        assert admin.delete(f"/me/keys/{made['key_id']}", headers=CONSOLE).status_code == 204
        r = mcp_site.browser().get("/namespaces", headers=bearer)
        assert r.status_code == 401 and admin.get("/me/keys").json()["keys"] == []

    def test_a_key_acts_as_its_owner_drive_sharing_included(self, mcp_site: Site) -> None:
        _key(mcp_site)
        rows = asyncio.run(tenancy.get_tenancy().list_records(personal_keys.KIND))
        p = asyncio.run(personal_keys.principal_for_key(rows[0]["key_id"]))
        assert p is not None and p.kind == "user" and "email:admin@acme.com" in p.access

    def test_a_key_stops_when_its_owner_leaves(self, mcp_site: Site) -> None:
        _key(mcp_site, "reader@gmail.com")
        rows = asyncio.run(tenancy.get_tenancy().list_records(personal_keys.KIND))
        asyncio.run(tenancy.get_tenancy().delete_subject("user", rows[0]["user_id"]))
        assert asyncio.run(personal_keys.principal_for_key(rows[0]["key_id"])) is None

    def test_a_revoked_record_acts_as_nobody_even_if_the_key_were_live(
        self, mcp_site: Site
    ) -> None:
        _key(mcp_site)
        store = tenancy.get_tenancy()
        [row] = asyncio.run(store.list_records(personal_keys.KIND))
        asyncio.run(store.put_record(personal_keys.KIND, row["key_id"], row["org_id"],
                                     {**row, "revoked": True}))
        assert asyncio.run(personal_keys.principal_for_key(row["key_id"])) is None

    def test_the_key_may_come_in_x_api_key(self, mcp_site: Site) -> None:
        # Copilot Studio's API-key option names a header and sends the bare key.
        r = mcp_site.browser().get("/namespaces", headers={"X-API-Key": _key(mcp_site)})
        assert r.status_code == 200 and r.json()["total"] >= 1

    def test_a_key_cannot_make_a_key(self, mcp_site: Site) -> None:
        bearer = {"Authorization": f"Bearer {_key(mcp_site)}"}
        r = mcp_site.browser().post("/me/keys", headers=bearer, json={"name": "x"})
        assert r.status_code == 403

    def test_someone_elses_key_cannot_be_revoked(self, mcp_site: Site) -> None:
        _key(mcp_site, "reader@gmail.com")
        rows = asyncio.run(tenancy.get_tenancy().list_records(personal_keys.KIND))
        admin = mcp_site.sign_in("admin@acme.com")
        r = admin.delete(f"/me/keys/{rows[0]['key_id']}", headers=CONSOLE)
        assert r.status_code == 404


class TestMcp:
    def test_three_read_only_tools(self, mcp_site: Site) -> None:
        [names] = _calls(mcp_site, _key(mcp_site), [("tools", {})])
        assert sorted(names) == ["list_sheets", "list_sources", "search"]

    def test_sheets_are_the_owners(self, mcp_site: Site) -> None:
        [r] = _calls(mcp_site, _key(mcp_site, "reader@gmail.com"), [("list_sheets", {})])
        assert not r.is_error and "docs" in _text(r) and "hr" not in _text(r)

    def test_search_returns_cited_passages_read_as_the_owner(self, mcp_site: Site) -> None:
        [r] = _calls(mcp_site, _key(mcp_site),
                     [("search", {"question": "How much leave?", "sheet": "docs"})])
        assert not r.is_error, _text(r)
        assert r.structured_content["results"][0] == {
            "marker": "[1]", "source": "Leave policy", "page": None,
            "text": "Twenty days a year."}
        [access] = mcp_site.app.state.mcp_seen
        assert access is not None and "email:admin@acme.com" in access

    def test_a_sheet_the_owner_cannot_read_is_refused(self, mcp_site: Site) -> None:
        [r] = _calls(mcp_site, _key(mcp_site, "reader@gmail.com"),
                     [("search", {"question": "q", "sheet": "hr"})])
        assert r.is_error and mcp_site.app.state.mcp_seen == []

    def test_no_key_no_entry(self, mcp_site: Site) -> None:
        r = mcp_site.browser().post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                    headers={"Accept": "application/json, text/event-stream"})
        assert r.status_code == 401

    def test_a_browser_session_is_not_a_key(self, mcp_site: Site) -> None:
        browser = mcp_site.sign_in("admin@acme.com")
        cookie = "; ".join(f"{k}={v}" for k, v in browser.cookies.items())
        [r] = asyncio.run(_session_calls(mcp_site, {"Cookie": cookie, **CONSOLE},
                                         [("list_sheets", {})]))
        assert r.is_error and "personal key" in _text(r)
