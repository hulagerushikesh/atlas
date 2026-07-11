"""
Tests for CrossEncoderReranker.

The cross-encoder model is mocked so tests run without downloading weights.
We test that the reranker:
  - calls the model with the correct (query, content) pairs
  - returns chunks sorted by the model's scores (descending)
  - truncates to top_k
  - overwrites the original score with the cross-encoder score
  - handles empty candidate lists gracefully
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from atlas.config import RerankerConfig
from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.retriever import RetrievedChunk
from atlas.retrieval.reranker import CrossEncoderReranker


def _chunk(cid: str, content: str, score: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        content=content,
        score=score,
        metadata=ChunkMetadata(
            doc_id="doc1", source="t.md", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=len(content),
        ),
    )


@pytest.fixture
def reranker() -> CrossEncoderReranker:
    config = RerankerConfig(model="cross-encoder/ms-marco-MiniLM-L-6-v2", top_k=3)
    with patch("atlas.retrieval.reranker.CrossEncoder") as MockCE:
        mock_model = MagicMock()
        MockCE.return_value = mock_model
        r = CrossEncoderReranker(config)
        r._model = mock_model  # keep reference for test assertions
        return r


class TestCrossEncoderReranker:
    @pytest.mark.asyncio
    async def test_reranks_by_model_score(self, reranker: CrossEncoderReranker) -> None:
        candidates = [
            _chunk("c1", "Atlas is a RAG platform", score=0.9),
            _chunk("c2", "Qdrant is a vector database", score=0.8),
            _chunk("c3", "BM25 is a sparse method", score=0.7),
        ]
        # Model assigns c2 the highest score
        reranker._model.predict.return_value = [0.3, 0.9, 0.5]

        result = await reranker.rerank("vector database", candidates, top_k=3)

        assert result[0].chunk_id == "c2"
        assert result[1].chunk_id == "c3"
        assert result[2].chunk_id == "c1"

    @pytest.mark.asyncio
    async def test_top_k_truncates(self, reranker: CrossEncoderReranker) -> None:
        candidates = [_chunk(f"c{i}", f"content {i}") for i in range(5)]
        reranker._model.predict.return_value = [0.1, 0.5, 0.3, 0.9, 0.2]

        result = await reranker.rerank("query", candidates, top_k=2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_score_overwritten_with_cross_encoder_score(
        self, reranker: CrossEncoderReranker
    ) -> None:
        candidates = [_chunk("c1", "text", score=999.0)]
        reranker._model.predict.return_value = [0.42]

        result = await reranker.rerank("q", candidates, top_k=1)
        assert abs(result[0].score - 0.42) < 1e-6

    @pytest.mark.asyncio
    async def test_empty_candidates_returns_empty(self, reranker: CrossEncoderReranker) -> None:
        result = await reranker.rerank("q", [], top_k=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_predict_called_with_correct_pairs(self, reranker: CrossEncoderReranker) -> None:
        candidates = [_chunk("c1", "alpha"), _chunk("c2", "beta")]
        reranker._model.predict.return_value = [0.5, 0.7]

        await reranker.rerank("my query", candidates, top_k=2)

        call_args = reranker._model.predict.call_args[0][0]
        assert call_args == [("my query", "alpha"), ("my query", "beta")]

    @pytest.mark.asyncio
    async def test_original_chunks_not_mutated(self, reranker: CrossEncoderReranker) -> None:
        original_score = 0.99
        candidates = [_chunk("c1", "text", score=original_score)]
        reranker._model.predict.return_value = [0.1]

        await reranker.rerank("q", candidates, top_k=1)
        # The original candidate object should be unchanged
        assert candidates[0].score == original_score
