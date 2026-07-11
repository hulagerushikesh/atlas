"""
Shared pytest fixtures.

Fixtures are ordered from most-primitive (raw data) to most-composed
(full pipeline mocks) so each fixture only depends on things above it.
"""

from __future__ import annotations

import pytest

from atlas.interfaces.document import Chunk, ChunkMetadata, Document, DocumentType
from atlas.interfaces.retriever import RetrievedChunk, RetrievalResult


# ── Sample data ──────────────────────────────────────────────────────────────

@pytest.fixture
def sample_document() -> Document:
    return Document(
        id="doc-001",
        source="tests/fixtures/sample.md",
        doc_type=DocumentType.MARKDOWN,
        content="# Atlas\n\nAtlas is a production-grade RAG platform.\n\n"
                "It supports hybrid retrieval with dense and sparse indexes.",
        content_hash="abc123",
    )


@pytest.fixture
def sample_chunk(sample_document: Document) -> Chunk:
    return Chunk(
        id="chunk-001",
        content="Atlas is a production-grade RAG platform.",
        metadata=ChunkMetadata(
            doc_id=sample_document.id,
            source=sample_document.source,
            doc_type=DocumentType.MARKDOWN,
            chunk_index=0,
            start_char=9,
            end_char=51,
            content_hash="def456",
        ),
    )


@pytest.fixture
def sample_retrieved_chunk(sample_chunk: Chunk) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=sample_chunk.id,
        content=sample_chunk.content,
        score=0.92,
        metadata=sample_chunk.metadata,
    )


@pytest.fixture
def sample_retrieval_result(sample_retrieved_chunk: RetrievedChunk) -> RetrievalResult:
    return RetrievalResult(
        query="What is Atlas?",
        chunks=[sample_retrieved_chunk],
        retriever_name="test_retriever",
    )
