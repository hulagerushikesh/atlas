"""
Integration tests for the full RAGPipeline end-to-end.

These tests exercise the complete orchestration wiring (router → retrieval →
grading → generation → faithfulness) using a small in-memory fixture corpus
and fully mocked I/O boundaries (no network calls, no Qdrant, no OpenAI).

Why mock I/O but test the full pipeline?
    Unit tests already cover each component in isolation. These tests verify
    that the components compose correctly — the right data flows between stages,
    routing decisions trigger the right paths, and the final PipelineResult
    carries the expected provenance. They run in CI without any infra.

Three scenarios that cover the product's core value proposition:
  1. Simple factual query → grounded answer with at least one citation
  2. Out-of-scope query → clean refusal, no answer generated
  3. Complex query → decomposition fires, both sub-queries retrieved
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.retriever import RetrievedChunk, RetrievalResult
from atlas.orchestration.faithfulness import FaithfulnessResult
from atlas.orchestration.generator import CitationRef, GeneratorResult
from atlas.orchestration.pipeline import RAGPipeline


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _make_chunk(cid: str, content: str, source: str = "fastapi-docs.md") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        content=content,
        score=0.9,
        metadata=ChunkMetadata(
            doc_id="doc-1",
            source=source,
            doc_type=DocumentType.MARKDOWN,
            chunk_index=0,
            start_char=0,
            end_char=len(content),
        ),
    )


def _retrieval_result(chunks: list[RetrievedChunk]) -> RetrievalResult:
    result = MagicMock()
    result.chunks = chunks
    return result


def _build_pipeline(
    classification: str,
    chunks: list[RetrievedChunk],
    answer: str,
    citations: dict,
    is_faithful: bool = True,
    sub_queries: list[str] | None = None,
) -> RAGPipeline:
    """Construct a RAGPipeline where every LLM/network call is mocked."""
    router = MagicMock()
    router.classify = AsyncMock(return_value=classification)

    decomposer = MagicMock()
    decomposer.decompose = AsyncMock(return_value=sub_queries or [])

    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=_retrieval_result(chunks))

    grader = MagicMock()
    grader.grade = AsyncMock(return_value=(True, 0.9, ""))

    generator = MagicMock()
    generator.generate = AsyncMock(
        return_value=GeneratorResult(
            answer=answer,
            citations=citations,
            cited_chunks=[c for c in chunks if c.chunk_id in {r.chunk_id for r in citations.values()}]
            if citations else [],
            prompt_tokens=50,
            completion_tokens=80,
        )
    )

    faithfulness = MagicMock()
    faithfulness.check = AsyncMock(
        return_value=FaithfulnessResult(
            is_faithful=is_faithful,
            score=0.95 if is_faithful else 0.4,
            unsupported_claims=[],
        )
    )

    return RAGPipeline(
        retriever=retriever,
        router=router,
        decomposer=decomposer,
        grader=grader,
        generator=generator,
        faithfulness=faithfulness,
    )


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_simple_factual_query_returns_grounded_answer_with_citation():
    """A simple query flows through the full pipeline and returns a cited answer."""
    chunk = _make_chunk(
        "c-1",
        "FastAPI uses Python type hints to automatically generate OpenAPI docs.",
    )
    citation_ref = CitationRef(chunk_id="c-1", source="fastapi-docs.md", page_number=None)

    pipeline = _build_pipeline(
        classification="simple",
        chunks=[chunk],
        answer="FastAPI automatically generates OpenAPI documentation from Python type hints.[1]",
        citations={1: citation_ref},
    )

    result = await pipeline.run("How does FastAPI generate API docs?")

    assert result.classification == "simple"
    assert result.is_faithful is True
    assert result.generation is not None
    assert "[1]" in result.answer
    assert len(result.generation.citations) >= 1
    assert result.grader_retries == 0
    # Token counts are wired through from GeneratorResult
    assert result.generation.prompt_tokens == 50
    assert result.generation.completion_tokens == 80


@pytest.mark.asyncio
async def test_out_of_scope_query_is_refused_cleanly():
    """An out-of-scope query returns a refusal with no answer generation."""
    pipeline = _build_pipeline(
        classification="out_of_scope",
        chunks=[],
        answer="",
        citations={},
    )

    result = await pipeline.run("What is the best Django deployment strategy?")

    assert result.classification == "out_of_scope"
    assert result.generation is None
    assert result.faithfulness is None
    # Default is_faithful is True for refusals (no claims to check)
    assert result.is_faithful is True
    # The pipeline should not have called retrieve or generate
    pipeline._retriever.retrieve.assert_not_called()
    pipeline._generator.generate.assert_not_called()


@pytest.mark.asyncio
async def test_complex_query_triggers_decomposition():
    """A complex query triggers decomposition and retrieves for each sub-question."""
    sub_questions = [
        "What is dependency injection in FastAPI?",
        "How do you use Depends for database sessions?",
    ]
    chunk_a = _make_chunk("c-a", "FastAPI's Depends() injects dependencies into path operations.")
    chunk_b = _make_chunk("c-b", "Use yield in a dependency to manage database sessions.")
    citation_a = CitationRef(chunk_id="c-a", source="fastapi-docs.md", page_number=None)
    citation_b = CitationRef(chunk_id="c-b", source="fastapi-docs.md", page_number=None)

    pipeline = _build_pipeline(
        classification="complex",
        chunks=[chunk_a, chunk_b],
        answer=(
            "FastAPI's Depends() injects dependencies into path operations.[1] "
            "For database sessions, use yield inside the dependency.[2]"
        ),
        citations={1: citation_a, 2: citation_b},
        sub_queries=sub_questions,
    )

    result = await pipeline.run(
        "How does dependency injection work in FastAPI for database session management?"
    )

    assert result.classification == "complex"
    assert result.sub_queries == sub_questions
    # Decomposer was called once with the original query
    pipeline._decomposer.decompose.assert_awaited_once()
    # Retriever called once per sub-query
    assert pipeline._retriever.retrieve.await_count == len(sub_questions)
    assert len(result.generation.citations) == 2
    assert result.is_faithful is True
