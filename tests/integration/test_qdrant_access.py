"""
E2 against a real (in-memory) Qdrant: the access filter and one document's
access change and removal, with the actual client rather than a mock.

The unit suite proves the filter is *sent*; this proves Qdrant applies it as
meant — `MatchAny` against a list-valued payload field, a missing field
matching nothing, `set_payload` and `delete` by a doc_id filter.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from qdrant_client import AsyncQdrantClient

from atlas.access import set_reader_access
from atlas.config import QdrantConfig
from atlas.ingestion.dense import QdrantDenseIndex
from atlas.interfaces.document import Chunk, ChunkMetadata, DocumentType
from atlas.retrieval.dense import QdrantDenseRetriever
from tests.integration.test_qdrant_roundtrip import DIMENSIONS, StubEmbedder


def _chunk(doc: str, i: int, text: str, acl: list[str]) -> Chunk:
    return Chunk(content=text, metadata=ChunkMetadata(
        doc_id=doc, source=f"{doc}.md", doc_type=DocumentType.MARKDOWN, chunk_index=i,
        start_char=0, end_char=len(text), content_hash=f"{doc}-{i}", acl=acl))


@pytest.fixture
async def sheet() -> tuple[QdrantDenseIndex, QdrantDenseRetriever]:
    config = QdrantConfig(url="http://unused", collection_name="access")
    client = AsyncQdrantClient(":memory:")
    embedder = StubEmbedder()
    index = QdrantDenseIndex(config, dimensions=DIMENSIONS)
    retriever = QdrantDenseRetriever(config, embedder)
    index._client = retriever._client = client
    await index.ensure_collection()
    chunks = [_chunk("handbook", 0, "salary bands overview", ["all"]),
              _chunk("salaries", 0, "salary bands by level", ["group:hr"]),
              _chunk("salaries", 1, "salary bands for directors", ["group:hr"])]
    vectors = (await embedder.embed_texts([c.content for c in chunks])).vectors
    for c, v in zip(chunks, vectors, strict=True):
        c.embedding = v
    await index.upsert(chunks)
    # A point written before E2: no acl field at all.
    from qdrant_client.models import PointStruct
    await client.upsert("access", [PointStruct(
        id="00000000-0000-0000-0000-000000000001", vector=vectors[0],
        payload={"content": "salary from before E2", "doc_id": "old", "source": "old.md",
                 "doc_type": "markdown", "chunk_index": 0, "start_char": 0, "end_char": 1})])
    return index, retriever


async def _docs(retriever: QdrantDenseRetriever, tokens: set[str] | None) -> set[str]:
    async def search() -> set[str]:
        if tokens is not None:
            set_reader_access(tokens)
        result = await retriever.retrieve("salary bands", top_k=10)
        return {c.metadata.doc_id for c in result.chunks}

    # A task of its own, as a request would be, so the token set does not
    # leak into the next call.
    return await asyncio.create_task(search())


class TestTheFilterInQdrant:
    async def test_everyone_on_the_sheet(self, sheet: Any) -> None:
        assert await _docs(sheet[1], {"all"}) == {"handbook"}

    async def test_a_group_member(self, sheet: Any) -> None:
        assert await _docs(sheet[1], {"all", "group:hr"}) == {"handbook", "salaries"}

    async def test_no_tokens_reads_nothing(self, sheet: Any) -> None:
        assert await _docs(sheet[1], set()) == set()

    async def test_a_script_outside_a_request_reads_everything(self, sheet: Any) -> None:
        assert await _docs(sheet[1], None) == {"handbook", "salaries", "old"}


class TestOneDocument:
    async def test_readable_passages_counts_only_what_the_caller_may_read(
        self, sheet: Any
    ) -> None:
        index = sheet[0]
        assert await index.readable_passages("salaries", frozenset({"all"})) == 0
        assert await index.readable_passages("salaries", frozenset({"group:hr"})) == 2

    async def test_narrowing_and_reopening(self, sheet: Any) -> None:
        index, retriever = sheet
        assert await index.set_document_acl("handbook", ["group:hr"]) == 1
        assert await index.document_acl("handbook") == ["group:hr"]
        assert await _docs(retriever, {"all"}) == set()
        await index.set_document_acl("salaries", ["all"])
        assert await _docs(retriever, {"all"}) == {"salaries"}

    async def test_removing_takes_every_passage(self, sheet: Any) -> None:
        index, retriever = sheet
        assert await index.delete_document("salaries") == 2
        assert await _docs(retriever, {"all", "group:hr"}) == {"handbook"}
        assert await index.document_acl("salaries") is None

    async def test_a_pre_e2_passage_has_no_list(self, sheet: Any) -> None:
        assert await sheet[0].document_acl("old") is None


class TestABrandNewSheet:
    """Found live in T26: a new sheet's first upload asked for a document's
    access list before its collection existed, so every file failed (404)."""

    @pytest.fixture
    def fresh(self) -> QdrantDenseIndex:
        index = QdrantDenseIndex(QdrantConfig(url="http://unused", collection_name="fresh"),
                                 dimensions=DIMENSIONS)
        index._client = AsyncQdrantClient(":memory:")
        return index

    async def test_the_first_upload_finds_no_access_list(self, fresh: QdrantDenseIndex) -> None:
        assert await fresh.document_acl("anything") is None

    async def test_document_controls_answer_instead_of_failing(
        self, fresh: QdrantDenseIndex
    ) -> None:
        assert await fresh.readable_passages("anything", frozenset({"all"})) == 0
        assert await fresh.set_document_acl("anything", ["all"]) == 0
        assert await fresh.delete_document("anything") == 0
