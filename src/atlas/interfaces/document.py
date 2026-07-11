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

from pydantic import BaseModel, Field


class DocumentType(StrEnum):
    PDF = "pdf"
    MARKDOWN = "markdown"
    TEXT = "text"
    HTML = "html"


class Document(BaseModel):
    """Raw document before chunking."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str  # file path, URL, or logical name
    doc_type: DocumentType
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    # xxhash of content — used for idempotent indexing
    content_hash: str = ""


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

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    embedding: list[float] | None = None
    metadata: ChunkMetadata
