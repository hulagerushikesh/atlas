"""
Tests for HybridRetriever pipeline orchestration.

Both retrievers and the reranker are mocked so this purely tests the wiring:
  - retrievers called concurrently (both awaited)
  - RRF applied to combined results
  - reranker called on fused candidates
  - HybridRetrievalResult exposes per-retriever provenance
  - reranker=None path returns fused results truncated to reranker_top_k
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from atlas.config import RetrievalConfig
from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.retriever import RetrievalResult, RetrievedChunk
from atlas.retrieval.hybrid import HybridRetriever


def _chunk(cid: str, score: float = 1.0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        content=f"content {cid}",
        score=score,
        metadata=ChunkMetadata(
            doc_id="d1", source="t.md", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=10,
        ),
    )


def _mock_retriever(name: str, chunk_ids: list[str]) -> MagicMock:
    r = MagicMock()
    r.name = name
    r.retrieve = AsyncMock(
        return_value=RetrievalResult(
            query="q",
            chunks=[_chunk(cid, score=float(len(chunk_ids) - i)) for i, cid in enumerate(chunk_ids)],
            retriever_name=name,
        )
    )
    return r


def _mock_reranker(reordered_ids: list[str]) -> MagicMock:
    rr = MagicMock()
    rr.rerank = AsyncMock(
        side_effect=lambda q, candidates, top_k: [
            next(c for c in candidates if c.chunk_id == cid)
            for cid in reordered_ids
            if any(c.chunk_id == cid for c in candidates)
        ][:top_k]
    )
    return rr


@pytest.fixture
def config() -> RetrievalConfig:
    return RetrievalConfig(top_k=10)


class TestHybridRetriever:
    @pytest.mark.asyncio
    async def test_all_retrievers_called(self, config: RetrievalConfig) -> None:
        r1 = _mock_retriever("dense", ["A", "B"])
        r2 = _mock_retriever("sparse", ["B", "C"])
        hybrid = HybridRetriever([r1, r2], config, reranker=None, reranker_top_k=5)

        await hybrid.retrieve("test query")

        r1.retrieve.assert_awaited_once_with("test query", config.top_k)
        r2.retrieve.assert_awaited_once_with("test query", config.top_k)

    @pytest.mark.asyncio
    async def test_chunks_property_returns_final(self, config: RetrievalConfig) -> None:
        r1 = _mock_retriever("dense", ["A", "B", "C"])
        r2 = _mock_retriever("sparse", ["A", "C", "D"])
        reranker = _mock_reranker(["A", "C"])
        hybrid = HybridRetriever([r1, r2], config, reranker=reranker, reranker_top_k=2)

        result = await hybrid.retrieve("q")
        assert len(result.chunks) == 2

    @pytest.mark.asyncio
    async def test_per_retriever_provenance(self, config: RetrievalConfig) -> None:
        r1 = _mock_retriever("dense", ["A"])
        r2 = _mock_retriever("sparse", ["B"])
        hybrid = HybridRetriever([r1, r2], config, reranker=None, reranker_top_k=5)

        result = await hybrid.retrieve("q")
        names = {r.retriever_name for r in result.per_retriever}
        assert names == {"dense", "sparse"}

    @pytest.mark.asyncio
    async def test_no_reranker_returns_fused(self, config: RetrievalConfig) -> None:
        r1 = _mock_retriever("dense", ["A", "B", "C", "D", "E"])
        r2 = _mock_retriever("sparse", ["A", "C", "E", "B", "D"])
        hybrid = HybridRetriever([r1, r2], config, reranker=None, reranker_top_k=3)

        result = await hybrid.retrieve("q")
        # Without reranker, should truncate fused to reranker_top_k=3
        assert len(result.chunks) == 3

    @pytest.mark.asyncio
    async def test_reranker_called_with_fused_candidates(self, config: RetrievalConfig) -> None:
        r1 = _mock_retriever("dense", ["A", "B"])
        r2 = _mock_retriever("sparse", ["B", "C"])
        reranker = MagicMock()
        reranker.rerank = AsyncMock(return_value=[_chunk("A"), _chunk("B")])
        hybrid = HybridRetriever([r1, r2], config, reranker=reranker, reranker_top_k=2)

        await hybrid.retrieve("q")
        reranker.rerank.assert_awaited_once()
        call_kwargs = reranker.rerank.call_args
        # Should pass query, all fused candidates, and top_k
        assert call_kwargs[0][0] == "q"
        assert call_kwargs[0][2] == 2

    @pytest.mark.asyncio
    async def test_fused_list_populated(self, config: RetrievalConfig) -> None:
        r1 = _mock_retriever("dense", ["A", "B"])
        r2 = _mock_retriever("sparse", ["C", "D"])
        hybrid = HybridRetriever([r1, r2], config, reranker=None, reranker_top_k=10)

        result = await hybrid.retrieve("q")
        fused_ids = {c.chunk_id for c in result.fused}
        assert fused_ids == {"A", "B", "C", "D"}

    def test_empty_retrievers_raises(self, config: RetrievalConfig) -> None:
        with pytest.raises(ValueError, match="at least one retriever"):
            HybridRetriever([], config)
