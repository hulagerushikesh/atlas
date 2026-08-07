"""
Tests for QdrantDenseRetriever.

The important one here is test_uses_real_client_api_surface. Every other test in
the suite hands the retriever a permissive MagicMock, which happily answers to
any method name — that is exactly how a call to the long-removed
AsyncQdrantClient.search() survived undetected until mypy flagged it. Using
autospec against the installed client makes the mock reject calls the real
client would reject, so an API change in qdrant-client fails here rather than
in production.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from qdrant_client import AsyncQdrantClient

from atlas.config import QdrantConfig
from atlas.interfaces.document import DocumentType
from atlas.retrieval.dense import QdrantDenseRetriever


def _payload(chunk_index: int = 0) -> dict:
    return {
        "doc_id": "d1",
        "source": "guide.md",
        "doc_type": DocumentType.TEXT.value,
        "chunk_index": chunk_index,
        "start_char": 0,
        "end_char": 10,
        "content": f"chunk {chunk_index}",
        "page_number": None,
        "content_hash": "abc123",
        "extra": {},
    }


def _hit(chunk_index: int = 0, score: float = 0.9) -> MagicMock:
    hit = MagicMock()
    hit.id = f"c{chunk_index}"
    hit.score = score
    hit.payload = _payload(chunk_index)
    return hit


def _retriever(client) -> QdrantDenseRetriever:
    embedder = MagicMock()
    embedder.embed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])

    retriever = QdrantDenseRetriever(
        config=QdrantConfig(url="http://localhost:6333", collection_name="atlas_chunks"),
        embedder=embedder,
    )
    retriever._client = client
    return retriever


@pytest.mark.asyncio
async def test_uses_real_client_api_surface() -> None:
    """Guards against qdrant-client renaming or removing the query method."""
    client = create_autospec(AsyncQdrantClient, instance=True)
    response = MagicMock()
    response.points = [_hit(0), _hit(1)]
    client.query_points = AsyncMock(return_value=response)

    result = await _retriever(client).retrieve("how do I mount a router?", top_k=2)

    assert len(result.chunks) == 2
    client.query_points.assert_awaited_once()


@pytest.mark.asyncio
async def test_passes_embedded_query_and_top_k() -> None:
    client = MagicMock()
    response = MagicMock()
    response.points = [_hit(0)]
    client.query_points = AsyncMock(return_value=response)

    await _retriever(client).retrieve("some question", top_k=7)

    kwargs = client.query_points.await_args.kwargs
    assert kwargs["collection_name"] == "atlas_chunks"
    assert kwargs["query"] == [0.1, 0.2, 0.3]
    assert kwargs["limit"] == 7
    assert kwargs["with_payload"] is True


@pytest.mark.asyncio
async def test_maps_payload_into_chunk_metadata() -> None:
    client = MagicMock()
    response = MagicMock()
    response.points = [_hit(3, score=0.42)]
    client.query_points = AsyncMock(return_value=response)

    result = await _retriever(client).retrieve("q", top_k=1)

    chunk = result.chunks[0]
    assert chunk.score == 0.42
    assert chunk.metadata.doc_id == "d1"
    assert chunk.metadata.source == "guide.md"
    assert chunk.metadata.chunk_index == 3
    assert result.retriever_name == "qdrant_dense"


@pytest.mark.asyncio
async def test_empty_results_return_empty_chunks() -> None:
    client = MagicMock()
    response = MagicMock()
    response.points = []
    client.query_points = AsyncMock(return_value=response)

    result = await _retriever(client).retrieve("nothing matches", top_k=5)

    assert result.chunks == []
