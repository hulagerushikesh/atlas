"""
Chunker factory: construct the configured chunker from Settings.

Design rationale:
    The factory isolates the "which chunker?" decision from the indexing
    pipeline. The pipeline calls get_chunker(settings, embedder=...) and
    receives a ready-to-use BaseChunker without needing to import concrete
    classes. This is the standard Factory pattern applied to DI.

    SemanticChunker receives the embedder at construction time (not via a
    global import) so it can be tested with a mock embedder.
"""

from __future__ import annotations

from atlas.config import Settings
from atlas.interfaces.chunker import BaseChunker
from atlas.interfaces.embedder import BaseEmbedder


def get_chunker(settings: Settings, embedder: BaseEmbedder | None = None) -> BaseChunker:
    """
    Return the chunker specified in *settings.chunking.strategy*.

    Args:
        settings: Application settings (reads chunking sub-config).
        embedder: Required only when strategy == "semantic".
    """
    from atlas.ingestion.chunkers.fixed import FixedSizeChunker
    from atlas.ingestion.chunkers.recursive import RecursiveChunker
    from atlas.ingestion.chunkers.semantic import SemanticChunker

    cfg = settings.chunking
    strategy = cfg.strategy

    if strategy == "fixed":
        return FixedSizeChunker(size=cfg.size, overlap=cfg.overlap)

    if strategy == "recursive":
        return RecursiveChunker(size=cfg.size, overlap=cfg.overlap)

    if strategy == "semantic":
        if embedder is None:
            raise ValueError("SemanticChunker requires an embedder instance")
        return SemanticChunker(embedder=embedder)

    raise ValueError(f"Unknown chunking strategy: {strategy!r}")
