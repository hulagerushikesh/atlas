"""
Tests for the DocumentIndexer pipeline orchestrator.

All external dependencies (embedder, dense index, sparse index) are mocked.
This tests that the orchestrator wires them together correctly:
  - calls the embedder once per document
  - fans out to both indexes
  - counts written vs skipped correctly
  - handles per-document errors without aborting the whole run
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from atlas.ingestion.chunkers import FixedSizeChunker
from atlas.ingestion.indexer import DocumentIndexer
from atlas.interfaces.document import Chunk, Document, DocumentType
from atlas.interfaces.embedder import EmbeddingResult
from atlas.interfaces.index import IndexStats


def _make_doc(doc_id: str = "d1", content: str = "hello world " * 20) -> Document:
    return Document(
        id=doc_id,
        source="test.txt",
        doc_type=DocumentType.TEXT,
        content=content,
        content_hash="hash1",
    )


@pytest.fixture
def mock_embedder() -> MagicMock:
    embedder = MagicMock()

    # Returns exactly one vector per input text, as a real embedder does. An
    # earlier fixed-size stub returned a surplus of vectors, which masked
    # whether the indexer actually pairs chunks with their own embedding.
    async def _embed(texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[0.1, 0.2] for _ in texts],
            model="mock",
            total_tokens=100,
        )

    embedder.embed_texts = AsyncMock(side_effect=_embed)
    return embedder


@pytest.fixture
def mock_dense() -> MagicMock:
    idx = MagicMock()
    idx.upsert = AsyncMock(return_value=3)
    idx.unchanged_ids = AsyncMock(return_value=set())
    idx.stats = AsyncMock(
        return_value=IndexStats(total_chunks=3, collection_name="test", index_type="dense")
    )
    return idx


@pytest.fixture
def mock_sparse() -> MagicMock:
    idx = MagicMock()
    idx.upsert = AsyncMock(return_value=3)
    idx.stats = AsyncMock(
        return_value=IndexStats(
            total_chunks=3, collection_name="test.json", index_type="sparse"
        )
    )
    return idx


@pytest.fixture
def indexer(
    mock_embedder: MagicMock, mock_dense: MagicMock, mock_sparse: MagicMock
) -> DocumentIndexer:
    return DocumentIndexer(
        chunker=FixedSizeChunker(size=100, overlap=10),
        embedder=mock_embedder,
        dense_index=mock_dense,
        sparse_index=mock_sparse,
    )


class TestDocumentIndexer:
    @pytest.mark.asyncio
    async def test_index_documents_calls_embedder(
        self, indexer: DocumentIndexer, mock_embedder: MagicMock
    ) -> None:
        await indexer.index_documents([_make_doc()])
        mock_embedder.embed_texts.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_index_documents_calls_both_indexes(
        self, indexer: DocumentIndexer, mock_dense: MagicMock, mock_sparse: MagicMock
    ) -> None:
        await indexer.index_documents([_make_doc()])
        mock_dense.upsert.assert_awaited_once()
        mock_sparse.upsert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_result_counts_processed(
        self, indexer: DocumentIndexer
    ) -> None:
        result = await indexer.index_documents([_make_doc(), _make_doc("d2")])
        assert result.documents_processed == 2
        assert result.documents_skipped == 0

    @pytest.mark.asyncio
    async def test_skipped_when_both_indexes_return_zero(
        self, mock_embedder: MagicMock, mock_sparse: MagicMock
    ) -> None:
        dense = MagicMock()
        dense.upsert = AsyncMock(return_value=0)
        dense.unchanged_ids = AsyncMock(return_value=set())
        sparse = MagicMock()
        sparse.upsert = AsyncMock(return_value=0)

        indexer = DocumentIndexer(
            chunker=FixedSizeChunker(size=100, overlap=10),
            embedder=mock_embedder,
            dense_index=dense,
            sparse_index=sparse,
        )
        result = await indexer.index_documents([_make_doc()])
        assert result.documents_skipped == 1
        assert result.documents_processed == 0

    @pytest.mark.asyncio
    async def test_index_path_loads_and_indexes(
        self, tmp_path: Path, indexer: DocumentIndexer
    ) -> None:
        f = tmp_path / "sample.txt"
        f.write_text("hello world " * 20)
        result = await indexer.index_path(f)
        assert result.documents_processed + result.documents_skipped == 1

    @pytest.mark.asyncio
    async def test_index_directory(
        self, tmp_path: Path, indexer: DocumentIndexer
    ) -> None:
        (tmp_path / "a.txt").write_text("content alpha " * 20)
        (tmp_path / "b.md").write_text("content beta " * 20)
        result = await indexer.index_directory(tmp_path)
        assert result.documents_processed == 2

    async def test_index_directory_records_per_file_errors(
        self, tmp_path: Path, indexer: DocumentIndexer, mock_embedder: MagicMock
    ) -> None:
        """
        index_directory deliberately continues past a failing file. Before
        IndexResult carried an errors list, a run in which every file failed
        still reported success and exited 0.
        """
        (tmp_path / "a.txt").write_text("content alpha " * 20)
        (tmp_path / "b.md").write_text("content beta " * 20)
        mock_embedder.embed_texts = AsyncMock(side_effect=RuntimeError("quota exhausted"))

        result = await indexer.index_directory(tmp_path)

        assert result.documents_processed == 0
        assert len(result.errors) == 2
        assert all("quota exhausted" in e for e in result.errors)
        # Each entry names the file it came from, not just the message.
        assert {Path(e.split(":")[0]).name for e in result.errors} == {"a.txt", "b.md"}

    async def test_index_directory_has_no_errors_on_success(
        self, tmp_path: Path, indexer: DocumentIndexer
    ) -> None:
        (tmp_path / "a.txt").write_text("content alpha " * 20)
        result = await indexer.index_directory(tmp_path)
        assert result.errors == []


class TestIdempotency:
    """Found on the first live run: every ingest duplicated the corpus."""

    def test_document_and_chunk_ids_are_deterministic(self) -> None:
        from atlas.interfaces.document import ChunkMetadata
        a = Document(source="docs/x.md", doc_type=DocumentType.MARKDOWN, content="hi")
        b = Document(source="docs/x.md", doc_type=DocumentType.MARKDOWN, content="hi")
        assert a.id == b.id
        meta = ChunkMetadata(
            doc_id=a.id, source=a.source, doc_type=a.doc_type,
            chunk_index=2, start_char=0, end_char=2,
        )
        assert Chunk(content="hi", metadata=meta).id == Chunk(content="hi", metadata=meta).id
        assert Chunk(content="hi", metadata=meta).id != Chunk(
            content="hi", metadata=meta.model_copy(update={"chunk_index": 3})
        ).id

    @pytest.mark.asyncio
    async def test_unchanged_chunks_are_not_embedded(
        self, mock_embedder: MagicMock, mock_dense: MagicMock, mock_sparse: MagicMock
    ) -> None:
        # Dense index reports every chunk as already present and unchanged
        async def _all_unchanged(chunks):  # type: ignore[no-untyped-def]
            return {c.id for c in chunks}
        mock_dense.unchanged_ids = AsyncMock(side_effect=_all_unchanged)
        mock_dense.upsert = AsyncMock(return_value=0)
        mock_sparse.upsert = AsyncMock(return_value=0)

        indexer = DocumentIndexer(
            chunker=FixedSizeChunker(size=100, overlap=10),
            embedder=mock_embedder,
            dense_index=mock_dense,
            sparse_index=mock_sparse,
        )
        result = await indexer.index_documents([_make_doc()])

        mock_embedder.embed_texts.assert_not_called()
        assert result.documents_skipped == 1
        assert result.documents_processed == 0
        assert result.total_tokens == 0
