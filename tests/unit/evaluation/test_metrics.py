"""
Tests for all four evaluation metrics.

Programmatic metrics (precision, recall) need no mocks — pure computation.
LLM-as-judge metrics (faithfulness, answer_relevance) mock the LLM and embedder.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.evaluator import MetricScore
from atlas.interfaces.llm import GenerationResponse
from atlas.interfaces.retriever import RetrievedChunk
from atlas.interfaces.embedder import EmbeddingResult
from atlas.evaluation.metrics import (
    AnswerRelevanceMetric,
    ContextPrecisionMetric,
    ContextRecallMetric,
    FaithfulnessMetric,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _chunk(cid: str, doc_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, content=f"Content from {doc_id}.", score=0.8,
        metadata=ChunkMetadata(
            doc_id=doc_id, source=f"{doc_id}.md", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=20,
        ),
    )


def _llm(content: str) -> AsyncMock:
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=GenerationResponse(
            content=content, model_used="gpt-4o-mini",
            prompt_tokens=30, completion_tokens=20, total_tokens=50,
        )
    )
    return llm


# ── ContextPrecisionMetric ────────────────────────────────────────────────────

class TestContextPrecision:
    @pytest.mark.asyncio
    async def test_all_relevant(self) -> None:
        chunks = [_chunk("c1", "d1"), _chunk("c2", "d2")]
        metric = ContextPrecisionMetric()
        ms = await metric.score("q", "a", "gen", chunks, ["d1", "d2"])
        assert ms.score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_half_relevant(self) -> None:
        chunks = [_chunk("c1", "d1"), _chunk("c2", "d_noise")]
        metric = ContextPrecisionMetric()
        ms = await metric.score("q", "a", "gen", chunks, ["d1"])
        assert ms.score == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_none_relevant(self) -> None:
        chunks = [_chunk("c1", "d_noise")]
        metric = ContextPrecisionMetric()
        ms = await metric.score("q", "a", "gen", chunks, ["d1"])
        assert ms.score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_empty_chunks(self) -> None:
        metric = ContextPrecisionMetric()
        ms = await metric.score("q", "a", "gen", [], ["d1"])
        assert ms.score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_reasoning_populated(self) -> None:
        metric = ContextPrecisionMetric()
        ms = await metric.score("q", "a", "gen", [_chunk("c1", "d1")], ["d1"])
        assert ms.reasoning != ""

    def test_metric_name(self) -> None:
        assert ContextPrecisionMetric().name == "context_precision"


# ── ContextRecallMetric ───────────────────────────────────────────────────────

class TestContextRecall:
    @pytest.mark.asyncio
    async def test_full_recall(self) -> None:
        chunks = [_chunk("c1", "d1"), _chunk("c2", "d2")]
        metric = ContextRecallMetric()
        ms = await metric.score("q", "a", "gen", chunks, ["d1", "d2"])
        assert ms.score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_partial_recall(self) -> None:
        chunks = [_chunk("c1", "d1")]
        metric = ContextRecallMetric()
        ms = await metric.score("q", "a", "gen", chunks, ["d1", "d2"])
        assert ms.score == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_zero_recall(self) -> None:
        chunks = [_chunk("c1", "d_noise")]
        metric = ContextRecallMetric()
        ms = await metric.score("q", "a", "gen", chunks, ["d1"])
        assert ms.score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_no_relevant_docs_vacuously_perfect(self) -> None:
        metric = ContextRecallMetric()
        ms = await metric.score("q", "a", "gen", [], [])
        assert ms.score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_missing_doc_in_reasoning(self) -> None:
        metric = ContextRecallMetric()
        ms = await metric.score("q", "a", "gen", [_chunk("c1", "d1")], ["d1", "d2"])
        assert "d2" in ms.reasoning

    def test_metric_name(self) -> None:
        assert ContextRecallMetric().name == "context_recall"


# ── FaithfulnessMetric ────────────────────────────────────────────────────────

class TestFaithfulnessMetric:
    @pytest.mark.asyncio
    async def test_high_faithfulness(self) -> None:
        payload = json.dumps({
            "claims": [{"claim": "X", "verdict": "supported"}],
            "faithfulness_score": 1.0,
        })
        metric = FaithfulnessMetric(_llm(payload))
        ms = await metric.score("q", "a", "generated answer", [_chunk("c1", "d1")], [])
        assert ms.score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_low_faithfulness(self) -> None:
        payload = json.dumps({
            "claims": [
                {"claim": "X", "verdict": "supported"},
                {"claim": "Y", "verdict": "unsupported"},
            ],
            "faithfulness_score": 0.5,
        })
        metric = FaithfulnessMetric(_llm(payload))
        ms = await metric.score("q", "a", "answer", [_chunk("c1", "d1")], [])
        assert ms.score == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_unsupported_in_reasoning(self) -> None:
        payload = json.dumps({
            "claims": [{"claim": "Fake claim", "verdict": "unsupported"}],
            "faithfulness_score": 0.0,
        })
        metric = FaithfulnessMetric(_llm(payload))
        ms = await metric.score("q", "a", "answer", [_chunk("c1", "d1")], [])
        assert "Fake claim" in ms.reasoning

    def test_metric_name(self) -> None:
        llm = AsyncMock()
        assert FaithfulnessMetric(llm).name == "faithfulness"


# ── AnswerRelevanceMetric ─────────────────────────────────────────────────────

class TestAnswerRelevanceMetric:
    def _mock_embedder(self, vectors: list[list[float]]) -> AsyncMock:
        emb = AsyncMock()
        emb.embed_texts = AsyncMock(
            return_value=EmbeddingResult(vectors=vectors, model="mock", total_tokens=10)
        )
        return emb

    @pytest.mark.asyncio
    async def test_perfect_relevance(self) -> None:
        # Synthetic questions identical to original → cosine sim = 1.0
        payload = json.dumps({"questions": ["q", "q", "q"]})
        # All vectors identical → sim = 1.0
        vecs = [[1.0, 0.0]] * 4  # orig + 3 synthetic
        metric = AnswerRelevanceMetric(_llm(payload), self._mock_embedder(vecs))
        ms = await metric.score("q", "a", "answer", [], [])
        assert ms.score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_zero_relevance(self) -> None:
        payload = json.dumps({"questions": ["unrelated 1", "unrelated 2", "unrelated 3"]})
        # Orthogonal vectors → sim = 0.0
        vecs = [[1.0, 0.0], [0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]
        metric = AnswerRelevanceMetric(_llm(payload), self._mock_embedder(vecs))
        ms = await metric.score("q", "a", "answer", [], [])
        assert ms.score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_empty_synthetic_questions(self) -> None:
        payload = json.dumps({"questions": []})
        metric = AnswerRelevanceMetric(_llm(payload), self._mock_embedder([]))
        ms = await metric.score("q", "a", "answer", [], [])
        assert ms.score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_score_clamped_to_unit_interval(self) -> None:
        payload = json.dumps({"questions": ["q1"]})
        # Vectors that produce sim slightly > 1.0 due to float arithmetic
        vecs = [[1.0, 0.0], [1.0, 0.0]]
        metric = AnswerRelevanceMetric(_llm(payload), self._mock_embedder(vecs))
        ms = await metric.score("q", "a", "answer", [], [])
        assert 0.0 <= ms.score <= 1.0

    def test_metric_name(self) -> None:
        assert AnswerRelevanceMetric(AsyncMock(), AsyncMock()).name == "answer_relevance"
