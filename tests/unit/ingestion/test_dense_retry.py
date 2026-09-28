"""
Tests for the Qdrant write path's retry behaviour.

On 2026-09-28 an ingest of 155 files lost 37 of them to WriteTimeout,
ReadTimeout, ConnectTimeout and DNS failures. Nothing retried, so each fault
discarded a whole document — after its chunks had been embedded and paid for.
The run still exited having written 118 files, which is the worst shape a
failure can take: partial, plausible, and reported as warnings.

What these tests pin down is not "retry exists" but the two properties that
make it safe:

  - a retried upsert resends only the batch that failed, never the batches
    that already landed;
  - a status the server will repeat forever is not retried at all.

The wait is stripped per test rather than shortened in the source: the real
ladder is a deliberate choice about a live cluster and should not be tuned to
suit a test suite.
"""

from __future__ import annotations

from unittest.mock import create_autospec

import httpx
import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from atlas.config import QdrantConfig
from atlas.ingestion.dense import _UPSERT_BATCH, QdrantDenseIndex
from atlas.interfaces.document import Chunk, ChunkMetadata, DocumentType

DIMENSIONS = 4


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real ladder in the source; skip only the waiting."""
    from tenacity import wait_none

    for method in (
        QdrantDenseIndex._upsert_batch,
        QdrantDenseIndex._retrieve_hashes,
    ):
        monkeypatch.setattr(method.retry, "wait", wait_none())


def _index() -> tuple[QdrantDenseIndex, AsyncQdrantClient]:
    config = QdrantConfig(url="http://localhost:6333", collection_name="atlas_test")
    index = QdrantDenseIndex(config, DIMENSIONS)
    client = create_autospec(AsyncQdrantClient, instance=True)
    index._client = client
    # The collection check is a separate concern with its own round trips.
    index._collection_ready = True
    return index, client


def _chunks(count: int) -> list[Chunk]:
    return [
        Chunk(
            content=f"chunk {i}",
            embedding=[0.1] * DIMENSIONS,
            metadata=ChunkMetadata(
                doc_id="doc",
                source="doc.md",
                doc_type=DocumentType.MARKDOWN,
                chunk_index=i,
                start_char=i,
                end_char=i + 1,
                content_hash=f"hash{i}",
            ),
        )
        for i in range(count)
    ]


def _timeout() -> ResponseHandlingException:
    return ResponseHandlingException(source=httpx.WriteTimeout(""))


def _status(code: int) -> UnexpectedResponse:
    return UnexpectedResponse(
        status_code=code, reason_phrase="", content=b"", headers=httpx.Headers()
    )


@pytest.mark.asyncio
async def test_a_timed_out_batch_is_retried_and_the_write_completes() -> None:
    index, client = _index()
    client.retrieve.return_value = []
    client.upsert.side_effect = [_timeout(), None]

    written = await index.upsert(_chunks(1))

    assert written == 1
    assert client.upsert.await_count == 2


@pytest.mark.asyncio
async def test_only_the_failing_batch_is_resent() -> None:
    """The reason the retry sits on `_upsert_batch` and not on `upsert`."""
    index, client = _index()
    client.retrieve.return_value = []
    chunks = _chunks(_UPSERT_BATCH * 2 + 5)

    # First batch lands, second times out once, then everything proceeds.
    client.upsert.side_effect = [None, _timeout(), None, None]

    written = await index.upsert(chunks)

    assert written == len(chunks)
    sent = [
        [p.id for p in call.kwargs["points"]] for call in client.upsert.await_args_list
    ]
    assert [len(batch) for batch in sent] == [_UPSERT_BATCH, _UPSERT_BATCH, _UPSERT_BATCH, 5]
    # The retry of batch two is identical to batch two, and batch one is not
    # among the points sent again.
    assert sent[1] == sent[2]
    assert sent[0] != sent[1]
    # Every chunk reached Qdrant exactly once, ignoring the deliberate resend.
    delivered = {pid for batch in (sent[0], *sent[2:]) for pid in batch}
    assert delivered == {c.id for c in chunks}


@pytest.mark.asyncio
async def test_a_bad_request_is_not_retried() -> None:
    """400 means the request is wrong; the next four will be wrong too."""
    index, client = _index()
    client.retrieve.return_value = []
    client.upsert.side_effect = _status(400)

    with pytest.raises(UnexpectedResponse):
        await index.upsert(_chunks(1))

    assert client.upsert.await_count == 1


@pytest.mark.asyncio
async def test_the_hash_lookup_is_retried_too() -> None:
    """`unchanged_ids` runs before embedding. A fault here used to cost a
    whole document without a single token being spent — cheap, but it still
    dropped the file."""
    index, client = _index()
    client.retrieve.side_effect = [_timeout(), []]
    client.upsert.return_value = None

    written = await index.upsert(_chunks(1))

    assert written == 1
    assert client.retrieve.await_count == 2


def test_the_client_is_given_the_configured_timeout() -> None:
    """The fault underneath all of the above: qdrant-client passes no timeout
    to httpx unless it is given one, so the default was httpx's 5s."""
    config = QdrantConfig(url="http://localhost:6333", timeout_seconds=42)
    index = QdrantDenseIndex(config, DIMENSIONS)
    assert index._client._client._timeout == 42
