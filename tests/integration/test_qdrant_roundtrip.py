"""
Round-trip test of the dense write and read paths against a real Qdrant.

Why this exists:
    Every other test of these two classes mocks the Qdrant client. That is how
    a production-breaking bug survived a fully green suite: the retriever
    called `AsyncQdrantClient.search()`, which the installed client no longer
    has, and a permissive MagicMock answered the call happily.

    A mock can only confirm we call the method we think we call. It cannot
    confirm that method exists, that its arguments are accepted, that its
    return value has the shape we destructure, or that a payload written by
    the index survives a read by the retriever. Those are exactly the joints
    that broke, so this test drives the genuine qdrant-client code.

    It uses the client's local mode (":memory:"), which runs the real Python
    implementation without a server. No Docker, no network, no API key — so
    it stays in the normal `make test` run rather than rotting in a suite
    nobody executes.

    The embedder is a deterministic stub. The point is to test the Qdrant
    boundary, not OpenAI: a fake keeps the test hermetic and free, and the
    embedding call is already covered elsewhere.
"""

from __future__ import annotations

import math
import uuid

import pytest
from qdrant_client import AsyncQdrantClient

from atlas.config import QdrantConfig
from atlas.ingestion.dense import QdrantDenseIndex
from atlas.interfaces.document import Chunk, ChunkMetadata, DocumentType
from atlas.interfaces.embedder import BaseEmbedder, EmbeddingResult
from atlas.retrieval.dense import QdrantDenseRetriever

DIMENSIONS = 8


class StubEmbedder(BaseEmbedder):
    """Deterministic unit-norm vectors keyed off the text, no API calls."""

    @property
    def dimensions(self) -> int:
        return DIMENSIONS

    async def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[self._vector(t) for t in texts],
            model="stub",
            total_tokens=len(texts),
        )

    @staticmethod
    def _vector(text: str) -> list[float]:
        # Character-bucket histogram: similar strings land near each other, so
        # nearest-neighbour ordering is meaningful rather than arbitrary.
        raw = [0.0] * DIMENSIONS
        for ch in text.lower():
            raw[ord(ch) % DIMENSIONS] += 1.0
        norm = math.sqrt(sum(v * v for v in raw)) or 1.0
        return [v / norm for v in raw]


def _chunk(content: str, index: int, doc_id: str = "doc-1") -> Chunk:
    return Chunk(
        id=str(uuid.uuid4()),
        content=content,
        metadata=ChunkMetadata(
            doc_id=doc_id,
            source="guide.md",
            doc_type=DocumentType.MARKDOWN,
            chunk_index=index,
            start_char=index * 100,
            end_char=index * 100 + len(content),
            page_number=index + 1,
            content_hash=f"hash-{index}",
            extra={"section": f"s{index}"},
        ),
    )


@pytest.fixture
async def wired() -> tuple[QdrantDenseIndex, QdrantDenseRetriever, StubEmbedder]:
    """
    Index and retriever sharing one local Qdrant.

    Both classes construct their own client from config.url, so a shared
    in-memory store has to be injected. This is the only seam that is faked —
    the client itself is the real AsyncQdrantClient.
    """
    config = QdrantConfig(url="http://unused", collection_name="roundtrip")
    client = AsyncQdrantClient(":memory:")

    embedder = StubEmbedder()
    index = QdrantDenseIndex(config, dimensions=DIMENSIONS)
    retriever = QdrantDenseRetriever(config, embedder)
    index._client = client
    retriever._client = client

    return index, retriever, embedder


async def _seed(
    index: QdrantDenseIndex, embedder: StubEmbedder, chunks: list[Chunk]
) -> int:
    embedded = await embedder.embed_texts([c.content for c in chunks])
    for chunk, vector in zip(chunks, embedded.vectors, strict=True):
        chunk.embedding = vector
    return await index.upsert(chunks)


class TestDenseRoundTrip:
    async def test_written_chunks_are_retrievable(self, wired) -> None:
        """The end-to-end path that had never once executed before this test."""
        index, retriever, embedder = wired
        chunks = [
            _chunk("dependency injection in FastAPI", 0),
            _chunk("background tasks and workers", 1),
            _chunk("pydantic response models", 2),
        ]
        assert await _seed(index, embedder, chunks) == 3

        result = await retriever.retrieve("dependency injection in FastAPI", top_k=3)

        assert len(result.chunks) == 3
        assert result.retriever_name == "qdrant_dense"
        # Exact-match query must rank its own chunk first.
        assert result.chunks[0].content == "dependency injection in FastAPI"

    async def test_payload_survives_the_round_trip(self, wired) -> None:
        """
        The index writes ChunkMetadata and the retriever rebuilds it. A field
        dropped or renamed on either side would only show up here — the mocked
        tests hand back whatever payload they were told to.
        """
        index, retriever, embedder = wired
        chunk = _chunk("caching with dependencies", 7)
        await _seed(index, embedder, [chunk])

        [retrieved] = (await retriever.retrieve("caching with dependencies", 1)).chunks

        assert retrieved.chunk_id == chunk.id
        assert retrieved.content == chunk.content
        meta = retrieved.metadata
        assert meta.doc_id == "doc-1"
        assert meta.source == "guide.md"
        assert meta.doc_type is DocumentType.MARKDOWN
        assert meta.chunk_index == 7
        assert meta.start_char == 700
        assert meta.page_number == 8
        assert meta.content_hash == "hash-7"
        assert meta.extra == {"section": "s7"}

    async def test_top_k_is_honoured(self, wired) -> None:
        index, retriever, embedder = wired
        await _seed(index, embedder, [_chunk(f"chunk number {i}", i) for i in range(5)])

        assert len((await retriever.retrieve("chunk number 2", top_k=2)).chunks) == 2

    async def test_scores_are_descending_cosine(self, wired) -> None:
        """
        Ordering is the load-bearing property: RRF fuses on rank alone, so the
        raw score never reaches the caller.

        The bound is asserted with a tolerance deliberately. A real exact
        self-match here returns 1.0000000240112157 — Qdrant's cosine overshoots
        1.0 by float error. Harmless given RRF ignores magnitude, but anything
        that later switches to score-based fusion must clamp rather than trust
        the nominal [-1, 1] range.
        """
        index, retriever, embedder = wired
        await _seed(index, embedder, [_chunk(f"topic {i}", i) for i in range(4)])

        scores = [c.score for c in (await retriever.retrieve("topic 0", 4)).chunks]

        assert scores == sorted(scores, reverse=True)
        assert all(-1.0 - 1e-6 <= s <= 1.0 + 1e-6 for s in scores)

    async def test_reindexing_unchanged_chunks_writes_nothing(self, wired) -> None:
        """
        Idempotency is a real Qdrant behaviour: it depends on retrieve() by id
        returning the stored content_hash. A mock cannot prove that.
        """
        index, _, embedder = wired
        chunks = [_chunk("stable content", 0)]
        assert await _seed(index, embedder, chunks) == 1

        assert await _seed(index, embedder, chunks) == 0

    async def test_changed_content_hash_rewrites(self, wired) -> None:
        index, retriever, embedder = wired
        chunk = _chunk("original text", 0)
        await _seed(index, embedder, [chunk])

        chunk.content = "revised text"
        chunk.metadata.content_hash = "hash-revised"
        assert await _seed(index, embedder, [chunk]) == 1

        [retrieved] = (await retriever.retrieve("revised text", 1)).chunks
        assert retrieved.content == "revised text"

    async def test_empty_collection_returns_no_chunks(self, wired) -> None:
        """A query before any ingest must return empty, not raise."""
        index, retriever, _ = wired
        await index.ensure_collection()

        assert (await retriever.retrieve("anything", top_k=5)).chunks == []
