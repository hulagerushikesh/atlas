"""
E2.3: change who may read a document, remove a document, and make every
server notice (docs/e2-permissions.md §4).
"""

# ruff: noqa: F811 -- the sign-in suite's fixtures are imported, then used as arguments

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from atlas.api import tenancy
from atlas.api.namespaces import KeywordIndexStale, NamespaceRegistry
from atlas.config import RetrievalConfig
from atlas.ingestion.indexer import DocumentIndexer
from atlas.ingestion.sparse import BM25SparseIndex
from atlas.interfaces.document import Chunk, ChunkMetadata, Document, DocumentType
from tests.unit.api.test_sign_in import (  # noqa: F401 -- pytest fixtures
    CONSOLE,
    Site,
    google_key,
    other_key,
    site,
)


def _uid(c: TestClient) -> str:
    return str(c.get("/auth/me").json()["user"]["id"])


class _Sheet:
    def __init__(self, site: Site) -> None:
        self.site = site
        self.admin = site.sign_in("admin@acme.com")
        self.hr = self.admin.post("/org/groups", headers=CONSOLE,
                                  json={"name": "HR"}).json()["id"]
        self.ns = site.app.state.atlas.registry.get.return_value
        self.indexer = self.ns.indexer
        self.store = tenancy.get_tenancy()

    def editor(self, email: str = "ed@acme.com") -> TestClient:
        self.admin.post("/org/invitations", headers=CONSOLE,
                        json={"email": email, "roles": {"docs": "editor"}})
        return self.site.sign_in(email)

    def version(self) -> str:
        return asyncio.run(self.store.get_generation(self.site.ws["a/docs"]))

    def access(self, c: TestClient, **body: Any) -> Any:
        return c.put("/namespaces/docs/documents/access", headers=CONSOLE,
                     json={"source": "salaries.md", **body})


@pytest.fixture
def sheet(site: Site) -> _Sheet:
    return _Sheet(site)


class TestChangeAccess:
    def test_narrow_to_a_group(self, sheet: _Sheet) -> None:
        r = sheet.access(sheet.editor(), groups=["HR"])
        assert r.status_code == 200, r.text
        assert r.json() == {"source": "salaries.md", "everyone": False, "groups": ["HR"],
                            "people": [], "passages": 2}
        doc_id, acl = sheet.indexer.set_document_acl.await_args.args
        assert acl == [f"group:{sheet.hr}"]
        from atlas.interfaces.document import document_id
        assert doc_id == document_id("salaries.md")

    def test_share_with_a_person_by_email(self, sheet: _Sheet) -> None:
        ed = sheet.editor()
        r = sheet.access(ed, people=["ED@acme.com"])
        assert r.status_code == 200, r.text
        assert sheet.indexer.set_document_acl.await_args.args[1] == [f"user:{_uid(ed)}"]

    def test_reopen_to_everyone(self, sheet: _Sheet) -> None:
        r = sheet.access(sheet.editor(), everyone=True, groups=["HR"])
        assert r.json()["groups"] == [] and r.json()["everyone"] is True
        assert sheet.indexer.set_document_acl.await_args.args[1] == ["all"]

    @pytest.mark.parametrize(("body", "code"), [
        ({}, "no_readers"),
        ({"groups": ["Finance"]}, "unknown_group"),
        ({"people": ["stranger@elsewhere.org"]}, "unknown_person"),
        ({"people": ["admin@bolt.io"]}, "unknown_person"),   # another organisation
    ])
    def test_refused(self, sheet: _Sheet, body: dict[str, Any], code: str) -> None:
        sheet.site.sign_in("admin@bolt.io")
        r = sheet.access(sheet.editor(), **body)
        assert r.status_code == 422 and r.json()["detail"]["code"] == code
        sheet.indexer.set_document_acl.assert_not_awaited()

    def test_a_reader_cannot(self, sheet: _Sheet) -> None:
        reader = sheet.site.sign_in("reader@gmail.com")
        assert sheet.access(reader, everyone=True).status_code == 403

    def test_a_document_the_editor_cannot_read_is_not_found(self, sheet: _Sheet) -> None:
        # Exactly like one that does not exist, so its name cannot be probed.
        sheet.indexer.readable_passages = AsyncMock(return_value=0)
        ed = sheet.editor()
        hidden = sheet.access(ed, everyone=True).json()
        missing = ed.put("/namespaces/docs/documents/access", headers=CONSOLE,
                         json={"source": "nope.md", "everyone": True}).json()
        assert hidden["detail"]["code"] == missing["detail"]["code"] == "document_not_found"
        assert (hidden["detail"]["message"].replace("salaries.md", "X")
                == missing["detail"]["message"].replace("nope.md", "X"))
        sheet.indexer.set_document_acl.assert_not_awaited()

    def test_every_server_is_told(self, sheet: _Sheet) -> None:
        before = sheet.version()
        sheet.access(sheet.editor(), groups=["HR"])
        assert sheet.version() not in ("", before)
        # This server changed its own copy, so it is not made to rebuild it.
        registry = sheet.site.app.state.atlas.registry
        assert registry.mark_generation.call_args.args == ("org_a__docs", sheet.version())


class TestRemove:
    def test_remove(self, sheet: _Sheet) -> None:
        ed = sheet.editor()
        r = ed.delete("/namespaces/docs/documents", params={"source": "salaries.md"},
                      headers=CONSOLE)
        assert r.status_code == 200, r.text
        assert r.json() == {"source": "salaries.md", "passages_removed": 2}
        sheet.indexer.delete_document.assert_awaited_once()
        assert sheet.version() != ""

    def test_a_removed_documents_cached_answer_is_not_served_again(
        self, sheet: _Sheet
    ) -> None:
        ed = sheet.editor()
        ask = {"query": "What are the salary bands?", "namespace": "docs"}
        assert ed.post("/query", headers=CONSOLE, json=ask).json()["cached"] is False
        assert ed.post("/query", headers=CONSOLE, json=ask).json()["cached"] is True
        ed.delete("/namespaces/docs/documents", params={"source": "salaries.md"},
                  headers=CONSOLE)
        assert ed.post("/query", headers=CONSOLE, json=ask).json()["cached"] is False

    def test_another_servers_cached_answer_is_unreachable_too(self, sheet: _Sheet) -> None:
        # The other server's cache never hears of the removal; the new
        # version in every key is what makes its old entries unreachable.
        ed = sheet.editor()
        ask = {"query": "What are the salary bands?", "namespace": "docs"}
        ed.post("/query", headers=CONSOLE, json=ask)
        asyncio.run(sheet.store.bump_generation(sheet.site.ws["a/docs"]))  # elsewhere
        assert ed.post("/query", headers=CONSOLE, json=ask).json()["cached"] is False


# ── The other server's keyword copy ──────────────────────────────────────────

def _point(cid: str, acl: list[str]) -> MagicMock:
    p = MagicMock()
    p.id = cid
    p.payload = {"content": "salary", "content_hash": cid, "doc_id": "d", "source": "d.md",
                 "doc_type": "markdown", "chunk_index": 0, "start_char": 0, "end_char": 1,
                 "acl": acl}
    return p


async def _registry(tmp_path: Path, scroll: Any) -> tuple[NamespaceRegistry, BM25SparseIndex]:
    sparse = BM25SparseIndex(persist_path=tmp_path / "bm25.json")
    await sparse.replace_all([{"chunk_id": "c1", "content": "salary", "content_hash": "c1",
                               "metadata": {**_point("c1", ["all"]).payload}}])
    shared = MagicMock()
    shared.qdrant_client.scroll = scroll
    shared.qdrant_client.get_collection = AsyncMock(return_value=MagicMock(points_count=1))
    shared.settings.retrieval = RetrievalConfig(sparse_sync_ttl_seconds=60)
    registry = NamespaceRegistry(shared)
    components = MagicMock()
    components.sparse_index = sparse
    components.synced_at = None
    components.generation_seen = None
    components.sync_lock = asyncio.Lock()
    registry._cache["ns"] = components
    return registry, sparse


def _acl(sparse: BM25SparseIndex) -> list[Any]:
    return [e["metadata"]["acl"] for e in sparse._corpus]


class TestTheOtherServer:
    async def test_a_new_version_rebuilds_its_copy_even_at_the_same_count(
        self, tmp_path: Path
    ) -> None:
        # Narrowing changes no count, so only the version can reveal it.
        registry, sparse = await _registry(tmp_path, AsyncMock(
            return_value=([_point("c1", ["group:hr"])], None)))
        await registry.reconcile_sparse("ns", generation="")      # first sight, unchanged
        assert _acl(sparse) == [["all"]]
        sync = await registry.reconcile_sparse("ns", generation="v2")
        assert sync.rebuilt and _acl(sparse) == [["group:hr"]]
        again = await registry.reconcile_sparse("ns", generation="v2")
        assert not again.rebuilt                                     # once per version

    async def test_a_server_started_after_a_change_rebuilds_once(self, tmp_path: Path) -> None:
        # Its loaded copy (a baked file, say) predates the change.
        registry, sparse = await _registry(tmp_path, AsyncMock(
            return_value=([_point("c1", ["group:hr"])], None)))
        assert (await registry.reconcile_sparse("ns", generation="v1")).rebuilt
        assert _acl(sparse) == [["group:hr"]]

    async def test_a_rebuild_that_fails_refuses_rather_than_search_the_old_copy(
        self, tmp_path: Path
    ) -> None:
        registry, sparse = await _registry(tmp_path, AsyncMock(side_effect=OSError("qdrant down")))
        await registry.reconcile_sparse("ns", generation="")
        with pytest.raises(KeywordIndexStale):
            await registry.reconcile_sparse("ns", generation="v2")
        assert _acl(sparse) == [["all"]]   # kept on disk, but no request searches it

    def test_the_route_says_try_again(self, sheet: _Sheet) -> None:
        registry = sheet.site.app.state.atlas.registry
        registry.reconcile_sparse = AsyncMock(side_effect=KeywordIndexStale("org_a__docs"))
        r = sheet.editor().post("/query", headers=CONSOLE,
                                json={"query": "q", "namespace": "docs"})
        assert r.status_code == 503 and r.json()["detail"]["code"] == "sheet_updating"


# ── Pieces ───────────────────────────────────────────────────────────────────

class TestKeywordCopy:
    async def test_set_and_delete_one_document(self, tmp_path: Path) -> None:
        idx = BM25SparseIndex(tmp_path / "bm25.json")

        def c(doc: str, i: int) -> Chunk:
            return Chunk(content=f"text {doc}", metadata=ChunkMetadata(
                doc_id=doc, source=f"{doc}.md", doc_type=DocumentType.MARKDOWN,
                chunk_index=i, start_char=0, end_char=1, content_hash=f"{doc}{i}"))

        await idx.upsert([c("a", 0), c("a", 1), c("b", 0)])
        assert await idx.set_document_acl("a", ["group:hr"]) == 2
        assert idx.acl_tokens() == {"all", "group:hr"}
        assert await idx.delete_document("a") == 2
        assert [e["metadata"]["doc_id"] for e in idx._corpus] == ["b"]
        reloaded = BM25SparseIndex(tmp_path / "bm25.json")
        assert [e["metadata"]["doc_id"] for e in reloaded._corpus] == ["b"]


class TestReingest:
    async def test_an_edited_narrowed_document_stays_narrowed(self) -> None:
        dense, sparse = MagicMock(), MagicMock()
        dense.document_acl = AsyncMock(return_value=["group:hr"])
        dense.unchanged_ids = AsyncMock(return_value=set())
        dense.upsert = AsyncMock(return_value=1)
        dense.prune_document = AsyncMock(return_value=0)
        sparse.upsert = AsyncMock(return_value=1)
        sparse.prune_document = AsyncMock(return_value=0)
        embedder = MagicMock()
        embedder.embed_texts = AsyncMock(return_value=MagicMock(
            vectors=[[0.1]], total_tokens=1))
        chunker = MagicMock()
        chunker.chunk = AsyncMock(return_value=[Chunk(content="new text", metadata=ChunkMetadata(
            doc_id="d", source="d.md", doc_type=DocumentType.MARKDOWN, chunk_index=0,
            start_char=0, end_char=1))])
        indexer = DocumentIndexer(chunker, embedder, dense, sparse)
        await indexer.index_documents([Document(source="d.md", doc_type=DocumentType.MARKDOWN,
                                                content="new text")])
        written = dense.upsert.await_args.args[0]
        assert [c.metadata.acl for c in written] == [["group:hr"]]
