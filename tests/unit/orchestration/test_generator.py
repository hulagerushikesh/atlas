"""Tests for AnswerGenerator — citation parsing and result structure."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.llm import GenerationResponse
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.generator import AnswerGenerator


def _chunk(cid: str, source: str = "doc.pdf", page: int | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        content=f"Content of chunk {cid}.",
        score=0.9,
        metadata=ChunkMetadata(
            doc_id="d1", source=source, doc_type=DocumentType.PDF,
            chunk_index=0, start_char=0, end_char=20,
            page_number=page,
        ),
    )


def _llm_returning(answer: str) -> AsyncMock:
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=GenerationResponse(
            content=answer,
            model_used="gpt-4o-mini",
            prompt_tokens=50, completion_tokens=40, total_tokens=90,
        )
    )
    return llm


class TestAnswerGenerator:
    @pytest.mark.asyncio
    async def test_answer_in_result(self) -> None:
        gen = AnswerGenerator(_llm_returning("The answer is [1]."))
        result = await gen.generate("q", [_chunk("c1")])
        assert result.answer == "The answer is [1]."

    @pytest.mark.asyncio
    async def test_citation_resolved(self) -> None:
        gen = AnswerGenerator(_llm_returning("Fact from [1] and [2]."))
        result = await gen.generate("q", [_chunk("c1"), _chunk("c2")])
        assert 1 in result.citations
        assert 2 in result.citations
        assert result.citations[1].chunk_id == "c1"
        assert result.citations[2].chunk_id == "c2"

    @pytest.mark.asyncio
    async def test_out_of_range_citation_ignored(self) -> None:
        gen = AnswerGenerator(_llm_returning("See [5] for details."))
        result = await gen.generate("q", [_chunk("c1")])  # only 1 chunk
        assert 5 not in result.citations

    @pytest.mark.asyncio
    async def test_cited_chunks_populated(self) -> None:
        gen = AnswerGenerator(_llm_returning("From [1]: something true."))
        result = await gen.generate("q", [_chunk("c1"), _chunk("c2")])
        assert len(result.cited_chunks) == 1
        assert result.cited_chunks[0].chunk_id == "c1"

    @pytest.mark.asyncio
    async def test_no_citations_in_answer(self) -> None:
        gen = AnswerGenerator(_llm_returning("A claim without any citation."))
        result = await gen.generate("q", [_chunk("c1")])
        assert result.citations == {}
        assert result.cited_chunks == []

    @pytest.mark.asyncio
    async def test_page_number_in_citation_ref(self) -> None:
        gen = AnswerGenerator(_llm_returning("Fact [1]."))
        result = await gen.generate("q", [_chunk("c1", page=7)])
        assert result.citations[1].page_number == 7

    @pytest.mark.asyncio
    async def test_duplicate_citations_not_duplicated_in_cited_chunks(self) -> None:
        gen = AnswerGenerator(_llm_returning("[1] is important. Also [1]."))
        result = await gen.generate("q", [_chunk("c1")])
        assert len(result.cited_chunks) == 1
