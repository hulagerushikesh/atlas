"""
Tests for the BM25 sparse index.

We test against the in-memory index directly; no Qdrant or network required.
The persist_path is pointed at tmp_path so tests don't pollute the working dir.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.ingestion.sparse import BM25SparseIndex, _tokenize
from atlas.interfaces.document import Chunk, ChunkMetadata, DocumentType


def _make_chunk(chunk_id: str, content: str, doc_id: str = "doc-1") -> Chunk:
    return Chunk(
        id=chunk_id,
        content=content,
        metadata=ChunkMetadata(
            doc_id=doc_id,
            source="test.md",
            doc_type=DocumentType.TEXT,
            chunk_index=0,
            start_char=0,
            end_char=len(content),
            content_hash=f"hash-{chunk_id}",
        ),
    )


@pytest.fixture
def index(tmp_path: Path) -> BM25SparseIndex:
    return BM25SparseIndex(persist_path=tmp_path / "bm25.json")


class TestBM25SparseIndex:
    @pytest.mark.asyncio
    async def test_upsert_and_search(self, index: BM25SparseIndex) -> None:
        chunks = [
            _make_chunk("c1", "Atlas is a RAG platform for enterprises"),
            _make_chunk("c2", "Qdrant is a vector database for similarity search"),
            _make_chunk("c3", "BM25 is a sparse retrieval algorithm"),
        ]
        written = await index.upsert(chunks)
        assert written == 3

        results = index.search("RAG retrieval platform", top_k=2)
        assert len(results) == 2
        top_ids = [r[0]["chunk_id"] for r in results]
        assert "c1" in top_ids  # "RAG" and "platform" match chunk c1

    @pytest.mark.asyncio
    async def test_idempotent_upsert(self, index: BM25SparseIndex) -> None:
        chunk = _make_chunk("c1", "same content")
        await index.upsert([chunk])
        written_second = await index.upsert([chunk])
        assert written_second == 0  # unchanged hash → skip

    @pytest.mark.asyncio
    async def test_updated_content_reindexed(self, index: BM25SparseIndex) -> None:
        chunk_v1 = _make_chunk("c1", "old content")
        await index.upsert([chunk_v1])

        chunk_v2 = Chunk(
            id="c1",
            content="new content entirely different",
            metadata=ChunkMetadata(
                doc_id="doc-1",
                source="test.md",
                doc_type=DocumentType.TEXT,
                chunk_index=0,
                start_char=0,
                end_char=30,
                content_hash="new-hash",  # different hash triggers re-index
            ),
        )
        written = await index.upsert([chunk_v2])
        assert written == 1
        # Only one version should be in the corpus
        assert len(index._corpus) == 1

    @pytest.mark.asyncio
    async def test_delete(self, index: BM25SparseIndex) -> None:
        chunks = [_make_chunk("c1", "foo"), _make_chunk("c2", "bar")]
        await index.upsert(chunks)
        removed = await index.delete(["c1"])
        assert removed == 1
        assert len(index._corpus) == 1

    @pytest.mark.asyncio
    async def test_stats(self, index: BM25SparseIndex) -> None:
        chunks = [_make_chunk("c1", "foo"), _make_chunk("c2", "bar")]
        await index.upsert(chunks)
        stats = await index.stats()
        assert stats.total_chunks == 2
        assert stats.index_type == "sparse"

    @pytest.mark.asyncio
    async def test_search_empty_index(self, index: BM25SparseIndex) -> None:
        results = index.search("anything", top_k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_persists_and_reloads(self, tmp_path: Path) -> None:
        persist_path = tmp_path / "bm25.json"
        idx1 = BM25SparseIndex(persist_path=persist_path)
        await idx1.upsert([_make_chunk("c1", "hello world")])

        idx2 = BM25SparseIndex(persist_path=persist_path)
        assert len(idx2._corpus) == 1
        results = idx2.search("hello", top_k=1)
        assert results[0][0]["chunk_id"] == "c1"


class TestSources:
    async def test_groups_chunks_by_source_in_first_seen_order(
        self, index: BM25SparseIndex
    ) -> None:
        a1 = _make_chunk("a1", "alpha one")
        a1.metadata.source = "guide/a.md"
        a2 = _make_chunk("a2", "alpha two")
        a2.metadata.source = "guide/a.md"
        b1 = _make_chunk("b1", "beta one")
        b1.metadata.source = "ref/b.md"
        b1.metadata.doc_type = DocumentType.MARKDOWN

        await index.upsert([a1, b1, a2])

        assert index.sources() == [
            {"source": "guide/a.md", "doc_type": "text", "chunks": 2},
            {"source": "ref/b.md", "doc_type": "markdown", "chunks": 1},
        ]

    def test_empty_index_has_no_sources(self, index: BM25SparseIndex) -> None:
        assert index.sources() == []

    async def test_survives_reload_from_disk(self, tmp_path: Path) -> None:
        """The console reads this after a restart; it must come from the persisted corpus."""
        path = tmp_path / "bm25.json"
        first = BM25SparseIndex(persist_path=path)
        await first.upsert([_make_chunk("c1", "persisted")])

        reloaded = BM25SparseIndex(persist_path=path)
        assert reloaded.sources() == [{"source": "test.md", "doc_type": "text", "chunks": 1}]


class TestPruneDocument:
    """A re-ingested document that shrank must not keep its old tail chunks."""

    @pytest.mark.asyncio
    async def test_prunes_tail_only_for_that_document(self, index: BM25SparseIndex) -> None:
        chunks = []
        for i in range(4):
            c = _make_chunk(f"a{i}", f"doc a chunk {i}", doc_id="doc-a")
            c.metadata.chunk_index = i
            chunks.append(c)
        other = _make_chunk("b3", "doc b chunk 3", doc_id="doc-b")
        other.metadata.chunk_index = 3
        await index.upsert([*chunks, other])

        removed = await index.prune_document("doc-a", chunk_count=2)

        assert removed == 2
        remaining = {e["chunk_id"] for e in index._corpus}
        assert remaining == {"a0", "a1", "b3"}

    @pytest.mark.asyncio
    async def test_nothing_to_prune(self, index: BM25SparseIndex) -> None:
        await index.upsert([_make_chunk("a0", "only chunk", doc_id="doc-a")])
        assert await index.prune_document("doc-a", chunk_count=1) == 0
        assert await index.prune_document("doc-missing", chunk_count=0) == 0


class TestTokenizer:
    """
    The tokeniser decides what BM25 can ever match. Whitespace splitting tied
    tokens to the punctuation around them and hid every compound identifier
    behind its exact spelling.
    """

    def test_punctuation_no_longer_sticks_to_words(self) -> None:
        assert _tokenize("Use `response_model`, then stop.")[:4] == [
            "use", "response_model", "response", "model",
        ]

    @pytest.mark.parametrize(
        ("identifier", "expected_pieces"),
        [
            ("get_current_user", ["get", "current", "user"]),
            ("HTTPException", ["http", "exception"]),
            ("JSONResponse", ["json", "response"]),
            ("OAuth2PasswordBearer", ["auth2", "password", "bearer"]),
        ],
    )
    def test_identifier_pieces_are_indexed(
        self, identifier: str, expected_pieces: list[str]
    ) -> None:
        tokens = _tokenize(identifier)
        assert tokens[0] == identifier.lower()  # the whole name still wins
        assert all(piece in tokens for piece in expected_pieces)

    def test_single_letters_are_dropped(self) -> None:
        """"O" from OAuth2… matches nothing useful and dilutes every score."""
        assert "o" not in _tokenize("OAuth2PasswordBearer")

    def test_plain_prose_is_unchanged_apart_from_case(self) -> None:
        assert _tokenize("The quick brown fox") == ["the", "quick", "brown", "fox"]

    async def test_query_finds_a_chunk_by_an_identifier_piece(
        self, index: BM25SparseIndex
    ) -> None:
        """The point of the change: prose wording reaches code identifiers."""
        await index.upsert([
            _make_chunk("c1", "Use HTTPException to return an error response."),
            _make_chunk("c2", "Pydantic models describe the request body."),
        ])
        [(top, _score)] = index.search("http exception", top_k=1)
        assert top["chunk_id"] == "c1"
