#!/usr/bin/env python3
"""
ingest.py — index a file or directory into Atlas from the command line.

Builds the full ingestion pipeline from settings (same components as the API)
and calls DocumentIndexer.index_path(). Progress is streamed to stdout.

The source root printed at the top is what gets stripped from every
chunk's context header; see _resolve_source_root for why a single file
cannot work it out and what goes wrong when it guesses.

Usage:
    python scripts/ingest.py /path/to/docs
    python scripts/ingest.py /path/to/docs --glob "**/*.pdf"
    python scripts/ingest.py /path/to/report.pdf --chunker recursive
    python scripts/ingest.py docs/a/b.md --source-root docs   # match a corpus
    python scripts/ingest.py /path/to/docs --dry-run   # count files, don't index
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")


def _build_indexer(settings, chunker_type: str | None, namespace: str):
    from atlas.api.namespaces import namespace_to_collection, sparse_index_path
    from atlas.ingestion.chunkers import get_chunker
    from atlas.ingestion.dense import QdrantDenseIndex
    from atlas.ingestion.embedder import OpenAIEmbedder
    from atlas.ingestion.indexer import DocumentIndexer
    from atlas.ingestion.sparse import BM25SparseIndex

    embedder = OpenAIEmbedder(settings.openai)
    # Same collection + BM25 file the API's namespace registry will read.
    settings = settings.model_copy(
        update={"qdrant": settings.qdrant.model_copy(
            update={"collection_name": namespace_to_collection(namespace)})}
    )

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
        sparse_index=BM25SparseIndex(persist_path=sparse_index_path(namespace)),
        context_headers=settings.chunking.context_headers,
    )


def _resolve_source_root(target: Path, override: str | None) -> Path:
    """What gets stripped from the front of every chunk's context header.

    A directory ingest answers this itself — the directory is the corpus, and
    that is what `index_directory` has always used. A single file cannot:
    nothing in `data/corpus/fastapi/tutorial/body.md` says which leading
    segments are where the corpus lives and which are the document's own
    topic. The old answer was to pass nothing, which put all of it in the
    header: "data corpus fastapi tutorial body", three tokens of the ingest's
    working directory embedded into every chunk of that file.

    The damage is not the wasted tokens. Re-ingesting one file of a corpus
    that was ingested as a directory gives that file a header none of its
    neighbours have, which changes its content_hash, which re-embeds it into
    a corpus it now disagrees with — and nothing reports that, because from
    the ingest's side it looks like a file that changed.

    So the default is the file's own parent, which is right when the file
    stands alone and wrong when it sits deep in a tree that was indexed from
    above. Which of those it is, only the caller knows, so the choice is
    printed every run and --source-root overrides it.
    """
    if override:
        return Path(override)
    return target if target.is_dir() else target.parent


def _collect_files(path: Path, glob: str) -> list[Path]:
    if path.is_file():
        return [path]
    # Filter to files, matching DocumentIndexer.index_path. The default "**/*"
    # glob also matches directories, so without this the dry-run preview and
    # the file count both overstate what actually gets ingested.
    return sorted(p for p in path.glob(glob) if p.is_file())


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

    # Resolved before the dry-run branch: a dry run is exactly when someone
    # is checking what this is about to do, and the source root is the part
    # of that they cannot see any other way.
    source_root = _resolve_source_root(target, args.source_root)

    print(f"Atlas ingest — {len(files)} file(s) found under {target}")
    print(f"Source root: {source_root}  (stripped from context headers)")
    if target.is_file() and not args.source_root:
        print(
            "  note: adding to a corpus indexed from a higher directory? "
            "pass --source-root so the headers match."
        )
    if args.dry_run:
        for f in files:
            print(f"  {f}")
        print("Dry run complete. No data was indexed.")
        return 0

    print(f"Chunker : {args.chunker or 'default (from settings)'}")
    print(f"Namespace: {args.namespace}")
    print(f"Target  : {target}")
    print("─" * 50)

    indexer = _build_indexer(settings, args.chunker, args.namespace)

    t0 = time.perf_counter()
    # index_path loads a single file and takes no glob; directories must go
    # through index_directory. Passing glob= to index_path raised TypeError.
    if target.is_file():
        result = await indexer.index_path(target, source_root)
    else:
        result = await indexer.index_directory(
            target, glob=args.glob, source_root=source_root
        )
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
        "--namespace", default="default",
        help="Corpus namespace; must match the namespace queried via the API (default: default).",
    )
    parser.add_argument(
        "--glob",
        default="**/*",
        help="Glob pattern when path is a directory (default: **/*)",
    )
    parser.add_argument(
        "--source-root",
        help=(
            "Prefix stripped from each chunk's context header. Defaults to the "
            "directory itself, or a single file's parent. Set it when adding to "
            "a corpus that was ingested from a higher directory."
        ),
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
