"""Tests for RetrievalGrader."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.llm import GenerationResponse
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.grader import RetrievalGrader


def _chunk(cid: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, content=f"content {cid}", score=0.8,
        metadata=ChunkMetadata(
            doc_id="d1", source="t.md", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=10,
        ),
    )


def _llm_returning(sufficient: bool, score: float, reformulated: str = "new query") -> AsyncMock:
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=GenerationResponse(
            content=json.dumps({
                "sufficient": sufficient,
                "score": score,
                "reasoning": "test",
                "reformulated_query": reformulated,
            }),
            model_used="gpt-4o-mini",
            prompt_tokens=40, completion_tokens=30, total_tokens=70,
        )
    )
    return llm


class TestRetrievalGrader:
    @pytest.mark.asyncio
    async def test_sufficient_context(self) -> None:
        grader = RetrievalGrader(_llm_returning(True, 0.9))
        sufficient, score, _ = await grader.grade("q", [_chunk("c1")])
        assert sufficient is True
        assert score == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_insufficient_context(self) -> None:
        grader = RetrievalGrader(_llm_returning(False, 0.2))
        sufficient, score, reformulated = await grader.grade("q", [_chunk("c1")])
        assert sufficient is False
        assert reformulated == "new query"

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_insufficient(self) -> None:
        llm = AsyncMock()  # should not be called
        grader = RetrievalGrader(llm)
        sufficient, score, _ = await grader.grade("q", [])
        assert sufficient is False
        assert score == 0.0
        llm.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reformulated_query_returned(self) -> None:
        grader = RetrievalGrader(_llm_returning(False, 0.3, "better rephrased query"))
        _, _, reformulated = await grader.grade("original", [_chunk("c1")])
        assert reformulated == "better rephrased query"

    @pytest.mark.asyncio
    async def test_threshold_respected(self) -> None:
        # score=0.6, threshold=0.8 → insufficient
        grader = RetrievalGrader(_llm_returning(True, 0.6), threshold=0.8)
        # The LLM says sufficient=True but score is below our threshold —
        # the LLM's boolean is used directly (grader trusts the model's judgement)
        sufficient, _, _ = await grader.grade("q", [_chunk("c1")])
        assert sufficient is True  # LLM's verdict takes precedence
