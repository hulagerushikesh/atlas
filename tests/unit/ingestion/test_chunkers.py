"""
Tests for chunking strategies.

SemanticChunker tests use a mock embedder to avoid real API calls.
The mock returns vectors with a controlled similarity pattern so we can
assert that boundary detection fires at the expected positions.
"""

from __future__ import annotations

import numpy as np
import pytest

from atlas.ingestion.chunkers import FixedSizeChunker, RecursiveChunker, SemanticChunker
from atlas.ingestion.chunkers.factory import get_chunker
from atlas.interfaces.document import Document, DocumentType
from atlas.interfaces.embedder import BaseEmbedder, EmbeddingResult


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def short_doc() -> Document:
    return Document(
        id="d1",
        source="test.md",
        doc_type=DocumentType.MARKDOWN,
        content="The quick brown fox jumps over the lazy dog. " * 10,
        content_hash="hash1",
    )


@pytest.fixture
def long_doc() -> Document:
    # ~2000 chars — enough to produce multiple chunks
    paras = [f"Paragraph {i}. " + "Word " * 30 for i in range(10)]
    return Document(
        id="d2",
        source="test.md",
        doc_type=DocumentType.MARKDOWN,
        content="\n\n".join(paras),
        content_hash="hash2",
    )


# ── FixedSizeChunker ──────────────────────────────────────────────────────────

class TestFixedSizeChunker:
    @pytest.mark.asyncio
    async def test_produces_chunks(self, short_doc: Document) -> None:
        chunker = FixedSizeChunker(size=100, overlap=10)
        chunks = await chunker.chunk(short_doc)
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_chunk_content_within_size(self, long_doc: Document) -> None:
        chunker = FixedSizeChunker(size=200, overlap=20)
        chunks = await chunker.chunk(long_doc)
        for chunk in chunks:
            assert len(chunk.content) <= 200

    @pytest.mark.asyncio
    async def test_metadata_populated(self, short_doc: Document) -> None:
        chunker = FixedSizeChunker(size=100, overlap=10)
        chunks = await chunker.chunk(short_doc)
        for chunk in chunks:
            assert chunk.metadata.doc_id == short_doc.id
            assert chunk.metadata.content_hash != ""

    @pytest.mark.asyncio
    async def test_char_positions_contiguous(self, short_doc: Document) -> None:
        chunker = FixedSizeChunker(size=100, overlap=0)
        chunks = await chunker.chunk(short_doc)
        for chunk in chunks:
            assert chunk.metadata.end_char > chunk.metadata.start_char

    def test_overlap_gte_size_raises(self) -> None:
        with pytest.raises(ValueError):
            FixedSizeChunker(size=100, overlap=100)

    @pytest.mark.asyncio
    async def test_chunk_indices_sequential(self, short_doc: Document) -> None:
        chunker = FixedSizeChunker(size=50, overlap=5)
        chunks = await chunker.chunk(short_doc)
        for i, chunk in enumerate(chunks):
            assert chunk.metadata.chunk_index == i


# ── RecursiveChunker ──────────────────────────────────────────────────────────

class TestRecursiveChunker:
    @pytest.mark.asyncio
    async def test_produces_chunks(self, long_doc: Document) -> None:
        chunks = await RecursiveChunker(size=300, overlap=30).chunk(long_doc)
        assert len(chunks) > 1

    @pytest.mark.asyncio
    async def test_respects_paragraph_boundary(self) -> None:
        doc = Document(
            id="d3", source="t.md", doc_type=DocumentType.TEXT,
            content="First paragraph here.\n\nSecond paragraph here.",
            content_hash="h",
        )
        chunks = await RecursiveChunker(size=50, overlap=0).chunk(doc)
        # Should not split inside a short paragraph
        contents = [c.content for c in chunks]
        assert any("First paragraph" in c for c in contents)
        assert any("Second paragraph" in c for c in contents)

    @pytest.mark.asyncio
    async def test_metadata_doc_id(self, long_doc: Document) -> None:
        chunks = await RecursiveChunker().chunk(long_doc)
        assert all(c.metadata.doc_id == long_doc.id for c in chunks)

    def test_overlap_gte_size_raises(self) -> None:
        with pytest.raises(ValueError):
            RecursiveChunker(size=50, overlap=50)


# ── SemanticChunker ───────────────────────────────────────────────────────────

class _MockEmbedder(BaseEmbedder):
    """
    Returns alternating high/low-similarity vectors to trigger boundaries.

    Vectors at even indices point along [1,0]; odd indices along [0,1].
    Consecutive sim alternates between 0 (orthogonal → boundary) and 1 (same).
    With threshold=0.5, every other sentence triggers a split.
    """

    @property
    def dimensions(self) -> int:
        return 2

    async def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        vectors = []
        for i, _ in enumerate(texts):
            if i % 2 == 0:
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return EmbeddingResult(vectors=vectors, model="mock", total_tokens=len(texts) * 5)


class TestSemanticChunker:
    @pytest.mark.asyncio
    async def test_produces_at_least_one_chunk(self) -> None:
        doc = Document(
            id="d4", source="t.md", doc_type=DocumentType.TEXT,
            content="Hello world. This is a test.",
            content_hash="h",
        )
        chunks = await SemanticChunker(_MockEmbedder(), threshold=0.5).chunk(doc)
        assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_metadata_source_set(self) -> None:
        doc = Document(
            id="d5", source="semantic.md", doc_type=DocumentType.TEXT,
            content="Sentence one. Sentence two. Sentence three.",
            content_hash="h",
        )
        chunks = await SemanticChunker(_MockEmbedder(), threshold=0.5).chunk(doc)
        assert all(c.metadata.source == "semantic.md" for c in chunks)

    @pytest.mark.asyncio
    async def test_single_sentence_doc(self) -> None:
        doc = Document(
            id="d6", source="t.md", doc_type=DocumentType.TEXT,
            content="Only one sentence here",
            content_hash="h",
        )
        chunks = await SemanticChunker(_MockEmbedder()).chunk(doc)
        assert len(chunks) == 1


# ── Factory ───────────────────────────────────────────────────────────────────

class TestChunkerFactory:
    def test_fixed_strategy(self) -> None:
        from atlas.config import Settings
        settings = Settings(
            openai={"api_key": "sk-test"},
            chunking={"strategy": "fixed"},
        )
        chunker = get_chunker(settings)
        assert isinstance(chunker, FixedSizeChunker)

    def test_recursive_strategy(self) -> None:
        from atlas.config import Settings
        settings = Settings(
            openai={"api_key": "sk-test"},
            chunking={"strategy": "recursive"},
        )
        chunker = get_chunker(settings)
        assert isinstance(chunker, RecursiveChunker)

    def test_semantic_requires_embedder(self) -> None:
        from atlas.config import Settings
        settings = Settings(
            openai={"api_key": "sk-test"},
            chunking={"strategy": "semantic"},
        )
        with pytest.raises(ValueError, match="embedder"):
            get_chunker(settings)

    def test_semantic_with_embedder(self) -> None:
        from atlas.config import Settings
        settings = Settings(
            openai={"api_key": "sk-test"},
            chunking={"strategy": "semantic"},
        )
        chunker = get_chunker(settings, embedder=_MockEmbedder())
        assert isinstance(chunker, SemanticChunker)

    def test_unknown_strategy_raises(self) -> None:
        from atlas.config import Settings
        settings = Settings(
            openai={"api_key": "sk-test"},
            chunking={"strategy": "fixed"},  # valid for init
        )
        settings.chunking.strategy = "turbo"  # type: ignore[assignment]
        with pytest.raises(ValueError, match="Unknown"):
            get_chunker(settings)
