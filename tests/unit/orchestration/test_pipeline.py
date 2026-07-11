"""
Tests for RAGPipeline — the orchestration wiring.

All components are mocked. We test:
  - out_of_scope path: no retrieval, no generation
  - simple path: one retrieval, generate, check faithfulness
  - complex path: decompose → multi-retrieval → merge → generate
  - grader retry: insufficient context triggers re-query (capped at MAX_RETRIES)
  - deduplication: same chunk across sub-queries appears once
  - faithfulness flag propagates to PipelineResult
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.faithfulness import FaithfulnessResult
from atlas.orchestration.generator import CitationRef, GeneratorResult
from atlas.orchestration.pipeline import RAGPipeline


# ── Helpers ───────────────────────────────────────────────────────────────────

def _chunk(cid: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, content=f"content {cid}", score=0.8,
        metadata=ChunkMetadata(
            doc_id="d1", source="t.md", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=10,
        ),
    )


def _mock_retriever(chunks: list[RetrievedChunk]) -> MagicMock:
    r = MagicMock()
    result = MagicMock()
    result.chunks = chunks
    r.retrieve = AsyncMock(return_value=result)
    return r


def _mock_router(classification: str) -> MagicMock:
    r = MagicMock()
    r.classify = AsyncMock(return_value=classification)
    return r


def _mock_decomposer(sub_queries: list[str]) -> MagicMock:
    d = MagicMock()
    d.decompose = AsyncMock(return_value=sub_queries)
    return d


def _mock_grader(responses: list[tuple[bool, float, str]]) -> MagicMock:
    g = MagicMock()
    g.grade = AsyncMock(side_effect=responses)
    return g


def _mock_generator(answer: str = "The answer [1].") -> MagicMock:
    gen = MagicMock()
    gen.generate = AsyncMock(
        return_value=GeneratorResult(
            answer=answer,
            citations={1: CitationRef(chunk_id="c1", source="t.md", page_number=None)},
        )
    )
    return gen


def _mock_faithfulness(faithful: bool = True, score: float = 0.95) -> MagicMock:
    f = MagicMock()
    f.check = AsyncMock(
        return_value=FaithfulnessResult(
            score=score, is_faithful=faithful, summary="ok"
        )
    )
    return f


def _pipeline(
    retriever=None, router=None, decomposer=None,
    grader=None, generator=None, faithfulness=None,
    chunks=None,
) -> RAGPipeline:
    if chunks is None:
        chunks = [_chunk("c1")]
    return RAGPipeline(
        retriever=retriever or _mock_retriever(chunks),
        router=router or _mock_router("simple"),
        decomposer=decomposer or _mock_decomposer(["q1", "q2"]),
        grader=grader or _mock_grader([(True, 0.9, "q")]),
        generator=generator or _mock_generator(),
        faithfulness=faithfulness or _mock_faithfulness(),
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRAGPipeline:
    @pytest.mark.asyncio
    async def test_out_of_scope_returns_early(self) -> None:
        retriever = _mock_retriever([_chunk("c1")])
        p = _pipeline(router=_mock_router("out_of_scope"), retriever=retriever)
        result = await p.run("write a poem")
        assert result.classification == "out_of_scope"
        assert result.generation is None
        assert result.faithfulness is None
        retriever.retrieve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_simple_path_single_retrieval(self) -> None:
        retriever = _mock_retriever([_chunk("c1")])
        p = _pipeline(router=_mock_router("simple"), retriever=retriever)
        result = await p.run("simple question")
        assert result.classification == "simple"
        assert result.sub_queries == ["simple question"]
        retriever.retrieve.assert_awaited_once_with("simple question")

    @pytest.mark.asyncio
    async def test_complex_path_decomposes(self) -> None:
        retriever = _mock_retriever([_chunk("c1")])
        decomposer = _mock_decomposer(["sub1", "sub2"])
        p = _pipeline(
            router=_mock_router("complex"),
            decomposer=decomposer,
            retriever=retriever,
        )
        result = await p.run("complex multi-part question")
        assert result.sub_queries == ["sub1", "sub2"]
        assert retriever.retrieve.await_count == 2

    @pytest.mark.asyncio
    async def test_grader_retry_on_insufficient(self) -> None:
        retriever = _mock_retriever([_chunk("c1")])
        # First grade: insufficient → retry; second: sufficient → proceed
        grader = _mock_grader([
            (False, 0.3, "reformulated"),
            (True, 0.8, "reformulated"),
        ])
        p = _pipeline(retriever=retriever, grader=grader)
        result = await p.run("q")
        assert result.grader_retries == 1
        # Retriever called twice: once for original, once for reformulated
        assert retriever.retrieve.await_count == 2

    @pytest.mark.asyncio
    async def test_grader_retry_cap(self) -> None:
        retriever = _mock_retriever([_chunk("c1")])
        # Always insufficient — should cap at 2 retries
        grader = _mock_grader([
            (False, 0.1, "r1"),
            (False, 0.1, "r2"),
            (False, 0.1, "r3"),  # this would be a third retry if uncapped
        ])
        p = _pipeline(retriever=retriever, grader=grader)
        result = await p.run("q")
        assert result.grader_retries == 2
        # 3 total retrieves: original + 2 retries
        assert retriever.retrieve.await_count == 3

    @pytest.mark.asyncio
    async def test_deduplication_across_sub_queries(self) -> None:
        # Both sub-queries return the same chunk
        retriever = _mock_retriever([_chunk("c1")])
        decomposer = _mock_decomposer(["sub1", "sub2"])
        p = _pipeline(
            router=_mock_router("complex"),
            decomposer=decomposer,
            retriever=retriever,
        )
        result = await p.run("q")
        chunk_ids = [c.chunk_id for c in result.retrieved_chunks]
        assert chunk_ids.count("c1") == 1  # deduplicated

    @pytest.mark.asyncio
    async def test_faithfulness_flag_in_result(self) -> None:
        faithfulness = _mock_faithfulness(faithful=False, score=0.3)
        p = _pipeline(faithfulness=faithfulness)
        result = await p.run("q")
        assert result.is_faithful is False

    @pytest.mark.asyncio
    async def test_answer_accessible_on_result(self) -> None:
        generator = _mock_generator("My detailed answer [1].")
        p = _pipeline(generator=generator)
        result = await p.run("q")
        assert result.answer == "My detailed answer [1]."

    @pytest.mark.asyncio
    async def test_out_of_scope_answer_is_fixed_message(self) -> None:
        p = _pipeline(router=_mock_router("out_of_scope"))
        result = await p.run("q")
        assert "outside the scope" in result.answer
