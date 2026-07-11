"""
Loader registry — maps file extensions to the appropriate loader instance.

Design rationale:
    A registry pattern rather than a long if/elif chain means adding a new
    loader is one line: register it here. The registry is a singleton so we
    don't reconstruct loaders (some may hold state) on every ingest call.

    get_loader() raises a clear ValueError instead of returning None so callers
    don't need to guard against a None before awaiting .load() — fail fast
    before any I/O happens.
"""

from __future__ import annotations

from pathlib import Path

from atlas.ingestion.loaders.html import HTMLLoader
from atlas.ingestion.loaders.markdown import MarkdownLoader
from atlas.ingestion.loaders.pdf import PDFLoader
from atlas.ingestion.loaders.text import TextLoader
from atlas.interfaces.loader import BaseDocumentLoader


class LoaderRegistry:
    """Maps file extensions to concrete loader instances."""

    def __init__(self) -> None:
        self._loaders: dict[str, BaseDocumentLoader] = {}
        # Register built-in loaders
        for loader in [PDFLoader(), MarkdownLoader(), TextLoader(), HTMLLoader()]:
            for ext in loader.supported_extensions:
                self._loaders[ext] = loader

    def register(self, loader: BaseDocumentLoader) -> None:
        """Add or override a loader for its declared extensions."""
        for ext in loader.supported_extensions:
            self._loaders[ext] = loader

    def get(self, path: Path) -> BaseDocumentLoader:
        ext = path.suffix.lower()
        if ext not in self._loaders:
            supported = ", ".join(sorted(self._loaders))
            raise ValueError(
                f"No loader registered for '{ext}'. Supported: {supported}"
            )
        return self._loaders[ext]


# Module-level singleton — importable directly by the indexer
_registry = LoaderRegistry()


def get_loader(path: Path) -> BaseDocumentLoader:
    """Return the registered loader for *path*'s file extension."""
    return _registry.get(path)
