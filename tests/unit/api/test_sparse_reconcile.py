"""
reconcile_sparse — making one container's keyword index agree with Qdrant.

A namespace has two halves in two places. The dense half is in Qdrant, shared
by every instance; the sparse half is a JSON file on the instance's own disk,
which Cloud Run discards when it recycles the container. On 2026-10-25 two
PDFs were uploaded in one session, both landed in Qdrant, and only one was in
the container that answered the next question — the other instance had taken
the upload and then gone away.

So Qdrant is the source of truth and the sparse index is a cache of it. These
tests cover the three things that makes true (a missing document arrives, a
deleted one goes, a stale container converges) and the four ways a naive
version of it would destroy a working index.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from atlas.api.namespaces import NamespaceRegistry
from atlas.config import RetrievalConfig
from atlas.ingestion.sparse import BM25SparseIndex


def _point(chunk_id: str, content: str, *, source: str = "a.md", index: int = 0) -> MagicMock:
    """A Qdrant point as the dense index writes it: flat payload, content included."""
    point = MagicMock()
    point.id = chunk_id
    point.payload = {
        "content": content,
        "content_hash": f"h-{chunk_id}",
        "doc_id": source,
        "source": source,
        "doc_type": "markdown",
        "chunk_index": index,
        "start_char": 0,
        "end_char": len(content),
    }
    return point


def _registry(
    tmp_path: Path,
    *,
    pages: list[list[MagicMock]] | None = None,
    dense: int | None = 0,
    ttl: float = 60.0,
    scroll_error: Exception | None = None,
) -> tuple[NamespaceRegistry, MagicMock, BM25SparseIndex]:
    """
    A registry over a real sparse index and a mocked Qdrant.

    `settings.retrieval` is a real `RetrievalConfig`, not an auto-mock: the TTL
    is compared with `<=`, and a MagicMock has no ordering, so an auto-mock
    turns the freshness check into a TypeError that every test would see as
    "no reconcile happened".
    """
    sparse = BM25SparseIndex(persist_path=tmp_path / "bm25_index.json")

    client = MagicMock()
    client.collection_exists = AsyncMock(return_value=True)
    client.get_collection = AsyncMock(return_value=MagicMock(points_count=dense))
    if scroll_error is not None:
        client.scroll = AsyncMock(side_effect=scroll_error)
    else:
        batches = pages or [[]]
        returns = [
            (page, (None if i == len(batches) - 1 else i + 1))
            for i, page in enumerate(batches)
        ]
        client.scroll = AsyncMock(side_effect=returns)

    shared = MagicMock()
    shared.qdrant_client = client
    shared.settings.retrieval = RetrievalConfig(sparse_sync_ttl_seconds=ttl)

    registry = NamespaceRegistry(shared)
    components = MagicMock()
    components.sparse_index = sparse
    components.synced_at = None
    components.sync_lock = asyncio.Lock()
    registry._cache["ns"] = components
    return registry, client, sparse


class TestTheVectorStoreIsTheTruth:
    async def test_a_document_this_container_never_saw_arrives(self, tmp_path: Path) -> None:
        """The defect itself: an upload served by the other instance."""
        registry, client, sparse = _registry(
            tmp_path, dense=2,
            pages=[[_point("c1", "alpha beta"), _point("c2", "gamma delta")]],
        )
        assert sparse.chunk_count() == 0

        sync = await registry.reconcile_sparse("ns")

        assert sync.rebuilt is True
        assert sync.sparse_chunks == 2
        assert sparse.chunk_count() == 2
        # Both rows are searchable. Not "gamma ranks first": with a two-row
        # corpus BM25's IDF for a term in one of two documents is exactly
        # zero, so ranking here would be a test of rank_bm25's small-corpus
        # behaviour rather than of the reconcile.
        found = {e["content"] for e, _ in sparse.search("alpha gamma", 5)}
        assert found == {"alpha beta", "gamma delta"}

    async def test_a_delete_in_qdrant_takes_the_text_with_it(self, tmp_path: Path) -> None:
        """
        The second consequence filed with the defect. `BM25SparseIndex` stores
        the chunk *text*, so deleting the points alone left the container
        serving the full content of a removed document until it recycled.
        """
        registry, _client, sparse = _registry(
            tmp_path, dense=1, pages=[[_point("c1", "alpha beta")]],
        )
        await sparse.replace_all([
            {"chunk_id": "c1", "content": "alpha beta", "content_hash": "h-c1",
             "metadata": _point("c1", "alpha beta").payload},
            {"chunk_id": "c2", "content": "secret removed text", "content_hash": "h-c2",
             "metadata": _point("c2", "secret removed text").payload},
        ])

        await registry.reconcile_sparse("ns")

        assert sparse.chunk_count() == 1
        assert all("secret" not in e["content"] for e, _ in sparse.search("secret", 5))

    async def test_a_payload_becomes_a_row_with_its_metadata(self, tmp_path: Path) -> None:
        registry, _client, sparse = _registry(
            tmp_path, dense=1,
            pages=[[_point("c1", "alpha", source="guide/intro.md", index=3)]],
        )
        await registry.reconcile_sparse("ns")
        assert sparse.sources() == [
            {"source": "guide/intro.md", "doc_type": "markdown", "chunks": 1}
        ]

    async def test_every_page_of_a_multi_page_scroll_is_read(self, tmp_path: Path) -> None:
        registry, client, sparse = _registry(
            tmp_path, dense=3,
            pages=[[_point("c1", "one"), _point("c2", "two")], [_point("c3", "three")]],
        )
        await registry.reconcile_sparse("ns")
        assert sparse.chunk_count() == 3
        assert client.scroll.await_count == 2


class TestItRefusesToDestroyAWorkingIndex:
    async def test_an_empty_collection_never_empties_a_populated_cache(
        self, tmp_path: Path
    ) -> None:
        """
        The baked FastAPI index cannot be rebuilt from a collection that no
        longer holds it, so a transient empty read must not be allowed to
        cost the container its corpus. The mismatch is reported by
        /namespaces/{ns}/sources; it is acted on nowhere.
        """
        registry, client, sparse = _registry(tmp_path, dense=0)
        await sparse.replace_all([
            {"chunk_id": "c1", "content": "baked", "content_hash": "h",
             "metadata": _point("c1", "baked").payload},
        ])

        sync = await registry.reconcile_sparse("ns")

        assert sync.rebuilt is False
        assert sparse.chunk_count() == 1
        client.scroll.assert_not_awaited()

    async def test_a_scroll_that_fails_halfway_is_not_adopted(self, tmp_path: Path) -> None:
        """A partial read looks exactly like a corpus that shrank."""
        registry, client, sparse = _registry(tmp_path, dense=9)
        await sparse.replace_all([
            {"chunk_id": f"c{i}", "content": f"row {i}", "content_hash": "h",
             "metadata": _point(f"c{i}", f"row {i}").payload}
            for i in range(4)
        ])
        client.scroll = AsyncMock(side_effect=[
            ([_point("c1", "one")], 1),
            ConnectionError("reset"),
        ])

        sync = await registry.reconcile_sparse("ns")

        assert sync.rebuilt is False
        assert sparse.chunk_count() == 4

    async def test_unreachable_qdrant_does_not_count_as_a_check(self, tmp_path: Path) -> None:
        """
        None is "nobody knows", not "zero". Stamping the clock on it would
        make the process trust an answer it never got for a whole TTL.
        """
        registry, client, sparse = _registry(tmp_path, dense=4)
        client.collection_exists = AsyncMock(side_effect=ConnectionError("no route"))

        sync = await registry.reconcile_sparse("ns")

        assert sync.dense_chunks is None
        assert sync.rebuilt is False
        assert registry.get("ns").synced_at is None
        client.scroll.assert_not_awaited()


class TestItCostsNothingWhenNothingChanged:
    async def test_counts_that_agree_do_not_scroll(self, tmp_path: Path) -> None:
        registry, client, sparse = _registry(tmp_path, dense=1)
        await sparse.replace_all([
            {"chunk_id": "c1", "content": "x", "content_hash": "h",
             "metadata": _point("c1", "x").payload},
        ])
        sync = await registry.reconcile_sparse("ns")
        assert sync.checked is True and sync.rebuilt is False
        client.scroll.assert_not_awaited()

    async def test_the_ttl_skips_the_second_check(self, tmp_path: Path) -> None:
        registry, client, _sparse = _registry(tmp_path, dense=0, ttl=60.0)
        await registry.reconcile_sparse("ns")
        await registry.reconcile_sparse("ns")
        assert client.get_collection.await_count == 1

    async def test_a_ttl_of_zero_checks_every_time(self, tmp_path: Path) -> None:
        """The setting exists so correctness can be bought with a round trip."""
        registry, client, _sparse = _registry(tmp_path, dense=0, ttl=0.0)
        await registry.reconcile_sparse("ns")
        await registry.reconcile_sparse("ns")
        assert client.get_collection.await_count == 2

    async def test_a_count_the_caller_already_read_is_not_read_again(
        self, tmp_path: Path
    ) -> None:
        """/namespaces/{ns}/sources pays for this number anyway."""
        registry, client, sparse = _registry(tmp_path, dense=99, pages=[[_point("c1", "x")]])
        sync = await registry.reconcile_sparse("ns", dense_chunks=1)
        assert sync.dense_chunks == 1
        assert sparse.chunk_count() == 1
        client.get_collection.assert_not_awaited()

    async def test_two_concurrent_requests_scroll_once(self, tmp_path: Path) -> None:
        """
        Without the lock both first requests pull the whole collection and the
        second overwrites the first with identical rows.

        The mocks must actually suspend. An `AsyncMock` completes without ever
        yielding to the loop, so two gathered coroutines run strictly one
        after the other and the lock is never contended -- this test passed
        against a version with the lock removed until the `asyncio.sleep(0)`
        below was added, which made it a test of nothing.
        """
        registry, client, _sparse = _registry(
            tmp_path, dense=1, pages=[[_point("c1", "x")]],
        )
        real_exists, real_scroll = client.collection_exists, client.scroll

        async def _yielding_exists(*a: object, **k: object) -> object:
            await asyncio.sleep(0)
            return await real_exists(*a, **k)

        async def _yielding_scroll(*a: object, **k: object) -> object:
            await asyncio.sleep(0)
            return await real_scroll(*a, **k)

        client.collection_exists = _yielding_exists
        client.scroll = _yielding_scroll

        await asyncio.gather(
            registry.reconcile_sparse("ns"), registry.reconcile_sparse("ns")
        )
        assert real_scroll.await_count == 1

    async def test_a_namespace_with_no_sparse_half_is_a_no_op(self, tmp_path: Path) -> None:
        registry, client, _sparse = _registry(tmp_path, dense=5)
        registry._cache["ns"].sparse_index = None
        sync = await registry.reconcile_sparse("ns")
        assert sync == type(sync)(False, False, 0, None)
        client.get_collection.assert_not_awaited()


class TestTheRoutesReconcileBeforeTheyRead:
    def test_sources_hands_over_the_count_it_already_read(self, client: object) -> None:
        from fastapi.testclient import TestClient

        assert isinstance(client, TestClient)
        registry = client.app.state.atlas.registry
        client.get("/namespaces/default/sources")
        registry.reconcile_sparse.assert_awaited_once_with("default", dense_chunks=19)

    def test_a_query_reconciles_before_the_pipeline_runs(self, client: object) -> None:
        from fastapi.testclient import TestClient

        assert isinstance(client, TestClient)
        registry = client.app.state.atlas.registry
        client.post("/query", json={"query": "what is atlas?"})
        registry.reconcile_sparse.assert_awaited_once_with("default")

    def test_a_streamed_query_reconciles_too(self, client: object) -> None:
        """
        Two call sites, so two tests. Asserting only on the standard path let
        a mutant that dropped the streaming reconcile survive -- and streaming
        is the path the console uses, so it is the one that matters most.
        """
        from fastapi.testclient import TestClient

        assert isinstance(client, TestClient)
        registry = client.app.state.atlas.registry
        with client.stream(
            "POST", "/query", json={"query": "what is atlas?", "stream": True}
        ) as response:
            response.read()
        registry.reconcile_sparse.assert_awaited_once_with("default")

    def test_an_upload_reconciles_before_it_indexes(self, client: object) -> None:
        from fastapi.testclient import TestClient

        assert isinstance(client, TestClient)
        registry = client.app.state.atlas.registry
        registry.get.return_value.indexer.index_directory = AsyncMock(
            return_value=MagicMock(
                documents_processed=1, documents_skipped=0, chunks_indexed=2,
                total_tokens=10,
            )
        )
        client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"hello", "text/markdown"))],
            data={"namespace": "my-notes"},
        )
        registry.reconcile_sparse.assert_awaited_once_with("my-notes")


@pytest.mark.parametrize("ttl", [0.0, 60.0])
def test_the_ttl_is_configurable(ttl: float) -> None:
    assert RetrievalConfig(sparse_sync_ttl_seconds=ttl).sparse_sync_ttl_seconds == ttl
