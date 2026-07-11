#!/usr/bin/env python3
"""
ingest.py — index a file or directory into Atlas from the command line.

Builds the full ingestion pipeline from settings (same components as the API)
and calls DocumentIndexer.index_path(). Progress is streamed to stdout.

Usage:
    python scripts/ingest.py /path/to/docs
    python scripts/ingest.py /path/to/docs --glob "**/*.pdf"
    python scripts/ingest.py /path/to/report.pdf --chunker recursive
    python scripts/ingest.py /path/to/docs --dry-run   # count files, don't index
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")


def _build_indexer(settings, chunker_type: str | None):
    from atlas.ingestion.chunkers import get_chunker
    from atlas.ingestion.dense import QdrantDenseIndex
    from atlas.ingestion.embedder import OpenAIEmbedder
    from atlas.ingestion.indexer import DocumentIndexer
    from atlas.ingestion.sparse import BM25SparseIndex

    embedder = OpenAIEmbedder(settings.openai)

    if chunker_type:
        # Override chunker strategy via env-style monkey-patch on settings
        from atlas.config import ChunkingConfig
        settings = settings.model_copy(
            update={"chunking": ChunkingConfig(strategy=chunker_type)}
        )

    chunker = get_chunker(settings, embedder=embedder)

    return DocumentIndexer(
        chunker=chunker,
        embedder=embedder,
        dense_index=QdrantDenseIndex(settings.qdrant, embedder.dimensions),
        sparse_index=BM25SparseIndex(),
    )


def _collect_files(path: Path, glob: str) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.glob(glob))


async def main(args: argparse.Namespace) -> int:
    from atlas.config import get_settings
    from atlas.logging import configure_logging

    configure_logging(level="INFO" if args.verbose else "WARNING", json=False)
    settings = get_settings()

    target = Path(args.path)
    if not target.exists():
        print(f"Error: path does not exist: {target}", file=sys.stderr)
        return 1

    files = _collect_files(target, args.glob)
    if not files:
        print(f"No files matched glob '{args.glob}' under {target}")
        return 0

    print(f"Atlas ingest — {len(files)} file(s) found under {target}")
    if args.dry_run:
        for f in files:
            print(f"  {f}")
        print("Dry run complete. No data was indexed.")
        return 0

    print(f"Chunker : {args.chunker or 'default (from settings)'}")
    print(f"Target  : {target}")
    print("─" * 50)

    indexer = _build_indexer(settings, args.chunker)

    t0 = time.perf_counter()
    result = await indexer.index_path(target, glob=args.glob)
    elapsed = time.perf_counter() - t0

    print("─" * 50)
    print(f"Documents processed : {result.documents_processed}")
    print(f"Documents skipped   : {result.documents_skipped}  (unchanged content)")
    print(f"Chunks indexed      : {result.chunks_indexed}")
    print(f"Total tokens        : {result.total_tokens:,}")
    print(f"Elapsed             : {elapsed:.1f}s")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for err in result.errors:
            print(f"  ✗ {err}")
        return 1

    print("\nDone.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index documents into Atlas.")
    parser.add_argument("path", help="File or directory to index.")
    parser.add_argument(
        "--glob",
        default="**/*",
        help="Glob pattern when path is a directory (default: **/*)",
    )
    parser.add_argument(
        "--chunker",
        choices=["fixed", "recursive", "semantic"],
        help="Override chunker strategy (default: from settings).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matched files without indexing.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable INFO-level logging.",
    )
    sys.exit(asyncio.run(main(parser.parse_args())))
