"""
Tests for the BM25 sparse index.

We test against the in-memory index directly; no Qdrant or network required.
The persist_path is pointed at tmp_path so tests don't pollute the working dir.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.ingestion.sparse import BM25SparseIndex
from atlas.interfaces.document import Chunk, ChunkMetadata, DocumentType


def _make_chunk(chunk_id: str, content: str, doc_id: str = "doc-1") -> Chunk:
    return Chunk(
        id=chunk_id,
        content=content,
        metadata=ChunkMetadata(
            doc_id=doc_id,
            source="test.md",
            doc_type=DocumentType.TEXT,
            chunk_index=0,
            start_char=0,
            end_char=len(content),
            content_hash=f"hash-{chunk_id}",
        ),
    )


@pytest.fixture
def index(tmp_path: Path) -> BM25SparseIndex:
    return BM25SparseIndex(persist_path=tmp_path / "bm25.json")


class TestBM25SparseIndex:
    @pytest.mark.asyncio
    async def test_upsert_and_search(self, index: BM25SparseIndex) -> None:
        chunks = [
            _make_chunk("c1", "Atlas is a RAG platform for enterprises"),
            _make_chunk("c2", "Qdrant is a vector database for similarity search"),
            _make_chunk("c3", "BM25 is a sparse retrieval algorithm"),
        ]
        written = await index.upsert(chunks)
        assert written == 3

        results = index.search("RAG retrieval platform", top_k=2)
        assert len(results) == 2
        top_ids = [r[0]["chunk_id"] for r in results]
        assert "c1" in top_ids  # "RAG" and "platform" match chunk c1

    @pytest.mark.asyncio
    async def test_idempotent_upsert(self, index: BM25SparseIndex) -> None:
        chunk = _make_chunk("c1", "same content")
        await index.upsert([chunk])
        written_second = await index.upsert([chunk])
        assert written_second == 0  # unchanged hash → skip

    @pytest.mark.asyncio
    async def test_updated_content_reindexed(self, index: BM25SparseIndex) -> None:
        chunk_v1 = _make_chunk("c1", "old content")
        await index.upsert([chunk_v1])

        chunk_v2 = Chunk(
            id="c1",
            content="new content entirely different",
            metadata=ChunkMetadata(
                doc_id="doc-1",
                source="test.md",
                doc_type=DocumentType.TEXT,
                chunk_index=0,
                start_char=0,
                end_char=30,
                content_hash="new-hash",  # different hash triggers re-index
            ),
        )
        written = await index.upsert([chunk_v2])
        assert written == 1
        # Only one version should be in the corpus
        assert len(index._corpus) == 1

    @pytest.mark.asyncio
    async def test_delete(self, index: BM25SparseIndex) -> None:
        chunks = [_make_chunk("c1", "foo"), _make_chunk("c2", "bar")]
        await index.upsert(chunks)
        removed = await index.delete(["c1"])
        assert removed == 1
        assert len(index._corpus) == 1

    @pytest.mark.asyncio
    async def test_stats(self, index: BM25SparseIndex) -> None:
        chunks = [_make_chunk("c1", "foo"), _make_chunk("c2", "bar")]
        await index.upsert(chunks)
        stats = await index.stats()
        assert stats.total_chunks == 2
        assert stats.index_type == "sparse"

    @pytest.mark.asyncio
    async def test_search_empty_index(self, index: BM25SparseIndex) -> None:
        results = index.search("anything", top_k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_persists_and_reloads(self, tmp_path: Path) -> None:
        persist_path = tmp_path / "bm25.json"
        idx1 = BM25SparseIndex(persist_path=persist_path)
        await idx1.upsert([_make_chunk("c1", "hello world")])

        idx2 = BM25SparseIndex(persist_path=persist_path)
        assert len(idx2._corpus) == 1
        results = idx2.search("hello", top_k=1)
        assert results[0][0]["chunk_id"] == "c1"
