"""
dense_chunk_count — the Qdrant half of a namespace inventory.

/namespaces/{ns}/sources reads the BM25 corpus, which is persisted separately
from Qdrant: the Docker image bakes the sparse index while the dense half
lives in Qdrant Cloud. On 2026-10-13 a local Qdrant held only one collection
while the console reported 155 sources / 4,020 refs on another namespace. This
count is what lets the endpoint say so instead.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from atlas.api.namespaces import NamespaceRegistry


def _registry(client: MagicMock) -> NamespaceRegistry:
    shared = MagicMock()
    shared.qdrant_client = client
    return NamespaceRegistry(shared)


def _client(*, exists: bool = True, points: int | None = 0) -> MagicMock:
    client = MagicMock()
    client.collection_exists = AsyncMock(return_value=exists)
    client.get_collection = AsyncMock(return_value=MagicMock(points_count=points))
    return client


async def test_counts_points_in_the_namespaces_collection() -> None:
    client = _client(points=4020)
    assert await _registry(client).dense_chunk_count("default") == 4020
    client.collection_exists.assert_awaited_once_with("atlas_default")


async def test_absent_collection_counts_zero() -> None:
    """A namespace with a baked sparse index and no collection holds nothing."""
    client = _client(exists=False)
    assert await _registry(client).dense_chunk_count("orphan") == 0
    client.get_collection.assert_not_awaited()


async def test_missing_points_count_reads_as_zero() -> None:
    assert await _registry(_client(points=None)).dense_chunk_count("default") == 0


async def test_unreachable_qdrant_is_none_not_zero() -> None:
    """
    The failure that would reinstate the bug: reporting 0 for a count that
    could not be read turns "unknown" into "definitely empty", and a
    measurement whose own gaps are silenced reports whatever you expected.
    """
    client = MagicMock()
    client.collection_exists = AsyncMock(side_effect=ConnectionError("no route"))
    assert await _registry(client).dense_chunk_count("default") is None


async def test_get_collection_failure_is_also_none() -> None:
    client = _client(exists=True)
    client.get_collection = AsyncMock(side_effect=TimeoutError("slow"))
    assert await _registry(client).dense_chunk_count("default") is None
