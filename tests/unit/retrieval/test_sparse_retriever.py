"""
Tests for BM25Retriever.

Uses a real BM25SparseIndex with a small in-memory corpus (no disk I/O needed
beyond tmp_path) to verify the retriever correctly wraps the index interface.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.ingestion.sparse import BM25SparseIndex
from atlas.interfaces.document import Chunk, ChunkMetadata, DocumentType
from atlas.retrieval.sparse import BM25Retriever


def _make_chunk(cid: str, content: str) -> Chunk:
    return Chunk(
        id=cid,
        content=content,
        metadata=ChunkMetadata(
            doc_id="doc1", source="t.txt", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=len(content),
            content_hash=f"h-{cid}",
        ),
    )


@pytest.fixture
async def retriever(tmp_path: Path) -> BM25Retriever:
    index = BM25SparseIndex(persist_path=tmp_path / "bm25.json")
    chunks = [
        _make_chunk("c1", "atlas rag retrieval platform"),
        _make_chunk("c2", "qdrant vector database similarity search"),
        _make_chunk("c3", "bm25 sparse keyword retrieval algorithm"),
    ]
    await index.upsert(chunks)
    return BM25Retriever(index)


class TestBM25Retriever:
    @pytest.mark.asyncio
    async def test_returns_retrieval_result(self, retriever: BM25Retriever) -> None:
        result = await retriever.retrieve("rag platform", top_k=2)
        assert result.retriever_name == "bm25_sparse"
        assert result.query == "rag platform"

    @pytest.mark.asyncio
    async def test_top_k_limit(self, retriever: BM25Retriever) -> None:
        result = await retriever.retrieve("retrieval", top_k=2)
        assert len(result.chunks) <= 2

    @pytest.mark.asyncio
    async def test_relevant_chunk_ranks_first(self, retriever: BM25Retriever) -> None:
        result = await retriever.retrieve("qdrant vector", top_k=3)
        assert result.chunks[0].chunk_id == "c2"

    @pytest.mark.asyncio
    async def test_metadata_populated(self, retriever: BM25Retriever) -> None:
        result = await retriever.retrieve("atlas", top_k=1)
        assert result.chunks[0].metadata.doc_id == "doc1"

    @pytest.mark.asyncio
    async def test_name_property(self, retriever: BM25Retriever) -> None:
        assert retriever.name == "bm25_sparse"
