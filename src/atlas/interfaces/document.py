"""
Core document and chunk data models.

Design rationale:
    These are the lingua franca of Atlas — every module speaks in Documents and
    Chunks. Keeping them in interfaces/ means no module imports from another.

    ChunkMetadata is intentionally rich: storing position, page, and
    content_hash enables idempotent re-indexing (Module A), accurate citation
    rendering (Module C), and provenance tracking in eval (Module D).

    content_hash uses xxhash (non-cryptographic, ~5 GB/s) rather than sha256
    because collision resistance is irrelevant here — we just want fast change
    detection. See ingestion/indexer.py for the hashing call.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

# Deterministic ids: the same source always maps to the same document id and
# the same (document, chunk_index) to the same chunk id. Without this every
# ingest run mints fresh uuid4s, the content_hash dedupe never matches, and
# re-ingesting duplicates the whole corpus (found on the first live run).
# uuid5 keeps the ids valid Qdrant point ids.
_ID_NAMESPACE = uuid.UUID("6a1f0c2e-3b4d-4e5f-8a9b-0c1d2e3f4a5b")


def document_id(source: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, source))


def chunk_id(doc_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, f"{doc_id}:{chunk_index}"))


class DocumentType(StrEnum):
    PDF = "pdf"
    MARKDOWN = "markdown"
    TEXT = "text"
    HTML = "html"


class Document(BaseModel):
    """Raw document before chunking."""

    id: str = ""  # derived from source when not given
    source: str  # file path, URL, or logical name
    doc_type: DocumentType
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    # xxhash of content — used for idempotent indexing
    content_hash: str = ""

    @model_validator(mode="after")
    def _default_id(self) -> Document:
        if not self.id:
            self.id = document_id(self.source)
        return self


class ChunkMetadata(BaseModel):
    """
    Provenance data attached to every chunk.

    chunk_index is the 0-based position within the parent document, used to
    reconstruct reading order when assembling citations.
    """

    doc_id: str
    source: str
    doc_type: DocumentType
    chunk_index: int
    start_char: int
    end_char: int
    page_number: int | None = None
    content_hash: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    """A single indexable text unit derived from a Document."""

    id: str = ""  # derived from (doc_id, chunk_index) when not given
    content: str
    embedding: list[float] | None = None
    metadata: ChunkMetadata

    @model_validator(mode="after")
    def _default_id(self) -> Chunk:
        if not self.id:
            self.id = chunk_id(self.metadata.doc_id, self.metadata.chunk_index)
        return self
