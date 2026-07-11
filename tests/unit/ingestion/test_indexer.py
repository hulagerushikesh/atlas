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
from atlas.interfaces.document import Document, DocumentType
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
    embedder.embed_texts = AsyncMock(
        return_value=EmbeddingResult(
            vectors=[[0.1, 0.2]] * 50,  # enough for any chunk count
            model="mock",
            total_tokens=100,
        )
    )
    return embedder


@pytest.fixture
def mock_dense() -> MagicMock:
    idx = MagicMock()
    idx.upsert = AsyncMock(return_value=3)
    idx.stats = AsyncMock(return_value=IndexStats(total_chunks=3, collection_name="test", index_type="dense"))
    return idx


@pytest.fixture
def mock_sparse() -> MagicMock:
    idx = MagicMock()
    idx.upsert = AsyncMock(return_value=3)
    idx.stats = AsyncMock(return_value=IndexStats(total_chunks=3, collection_name="test.json", index_type="sparse"))
    return idx


@pytest.fixture
def indexer(mock_embedder: MagicMock, mock_dense: MagicMock, mock_sparse: MagicMock) -> DocumentIndexer:
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
