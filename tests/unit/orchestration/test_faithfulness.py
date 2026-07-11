"""Tests for FaithfulnessChecker."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.llm import GenerationResponse
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.faithfulness import FaithfulnessChecker


def _chunk(cid: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, content="Context content.", score=0.9,
        metadata=ChunkMetadata(
            doc_id="d1", source="t.md", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=15,
        ),
    )


def _llm(score: float, claims: list[dict]) -> AsyncMock:  # type: ignore[type-arg]
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=GenerationResponse(
            content=json.dumps({
                "claims": claims,
                "faithfulness_score": score,
                "summary": "test summary",
            }),
            model_used="gpt-4o-mini",
            prompt_tokens=60, completion_tokens=50, total_tokens=110,
        )
    )
    return llm


_SUPPORTED_CLAIMS = [
    {"claim": "X is true", "verdict": "supported", "evidence": "Context says X"},
]
_UNSUPPORTED_CLAIMS = [
    {"claim": "Y is true", "verdict": "unsupported", "evidence": ""},
]


class TestFaithfulnessChecker:
    @pytest.mark.asyncio
    async def test_faithful_high_score(self) -> None:
        checker = FaithfulnessChecker(_llm(0.9, _SUPPORTED_CLAIMS))
        result = await checker.check("answer text", [_chunk("c1")])
        assert result.is_faithful is True
        assert result.score == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_unfaithful_low_score(self) -> None:
        checker = FaithfulnessChecker(_llm(0.3, _UNSUPPORTED_CLAIMS))
        result = await checker.check("answer text", [_chunk("c1")])
        assert result.is_faithful is False

    @pytest.mark.asyncio
    async def test_unsupported_claims_populated(self) -> None:
        checker = FaithfulnessChecker(_llm(0.5, _UNSUPPORTED_CLAIMS))
        result = await checker.check("answer", [_chunk("c1")])
        assert "Y is true" in result.unsupported_claims

    @pytest.mark.asyncio
    async def test_disabled_skips_llm_call(self) -> None:
        llm = AsyncMock()
        checker = FaithfulnessChecker(llm, enabled=False)
        result = await checker.check("any answer", [_chunk("c1")])
        assert result.is_faithful is True
        assert result.score == 1.0
        llm.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_claims_parsed(self) -> None:
        checker = FaithfulnessChecker(_llm(0.8, _SUPPORTED_CLAIMS))
        result = await checker.check("answer", [_chunk("c1")])
        assert len(result.claims) == 1
        assert result.claims[0].verdict == "supported"

    @pytest.mark.asyncio
    async def test_summary_populated(self) -> None:
        checker = FaithfulnessChecker(_llm(0.9, _SUPPORTED_CLAIMS))
        result = await checker.check("answer", [_chunk("c1")])
        assert result.summary == "test summary"
