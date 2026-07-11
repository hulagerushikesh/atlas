"""
Abstract base class for document loaders.

Design rationale:
    The ABC enforces a single contract: load() takes a path and returns a list
    of Documents (plural because a PDF with 100 pages is still one logical
    document, but some loaders — e.g. a zip of files — naturally emit many).
    Concrete loaders live in atlas.ingestion.loaders and are selected by the
    ingestion pipeline based on file extension / MIME type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from atlas.interfaces.document import Document


class BaseDocumentLoader(ABC):
    """Load raw content from a file path into Document objects."""

    @abstractmethod
    async def load(self, path: Path) -> list[Document]:
        """
        Read *path* and return one or more Document instances.

        Implementations should:
          - Populate Document.source with str(path).
          - Set the correct DocumentType.
          - Populate Document.content_hash (xxhash of the raw bytes).
          - NOT chunk: chunking is a separate concern.
        """

    @property
    @abstractmethod
    def supported_extensions(self) -> frozenset[str]:
        """Return the set of file extensions this loader handles (e.g. {'.pdf'})."""
