#!/usr/bin/env python3
"""
verify_index.py — what is actually in each namespace's two indexes.

Reads only. No embeddings, no LLM calls, no writes: running this costs Rs.0,
which is the whole point — it answers "did that ingest land?" without a meter.

Written after an ingest reported success and changed nothing. The run had gone
to the wrong namespace, so every content hash matched, both indexes skipped
every chunk, and the deploy that followed baked the old corpus into the image.
Nothing in the ingest output said so; the only evidence was a file mtime.

Three questions, in the order that catches that failure:

  1. How many chunks does each half hold? A namespace whose dense and sparse
     counts differ is a half-finished ingest.
  2. Do they hold the *same* chunks? Ids and content hashes are compared
     pairwise. Between `ingest.py` and `deploy_gcp.sh` production runs the new
     dense vectors against the pre-header BM25 file still baked into the live
     image — a mismatched hybrid that answers queries and scores badly rather
     than erroring, and this is the check that names it.
  3. Do the chunks carry the context headers the current config asks for?
     Recomputed from the corpus with the same `context_header()` the ingest
     calls, so "the headers are live" stops being something inferred from a
     timestamp. `chunking.context_headers` decides what passing means, in both
     directions: headers missing when it is on, and headers left behind when it
     is off, are the same kind of drift.

The corpus root is inferred from the common prefix of the indexed sources,
because that is what `index_directory` strips from a header. Pass --corpus when
the sources do not resolve on this machine or the inference is wrong; without
readable corpus files check 3 falls back to the header's first line, which
catches a missing header but not a stale one.

Usage:
    python scripts/verify_index.py                       # every namespace
    python scripts/verify_index.py --namespace default
    python scripts/verify_index.py --corpus data/corpus/fastapi
    python scripts/verify_index.py --no-dense            # local BM25 file only

Exit 0 when every namespace checked is consistent, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, "src")

# Qdrant's scroll page size. Large enough that 4k points is eight round trips,
# small enough that a payload-bearing page stays well inside the HTTP limits.
_SCROLL_BATCH = 512

# How many mismatching chunks to name before the list stops being useful.
_SAMPLE = 5

# chunk id -> (content, content_hash, source, start_char)
ChunkRow = tuple[str, str, str, int]


@dataclass
class Half:
    """One side of a namespace's hybrid index."""

    present: bool = False
    detail: str = ""
    chunks: dict[str, ChunkRow] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.chunks)


# ── Reading ───────────────────────────────────────────────────────────────────


def read_sparse(path: Path) -> Half:
    """The BM25 corpus as persisted. This file is what the image bakes."""
    if not path.exists():
        return Half(present=False, detail=f"{path} — missing")
    stat = path.stat()
    when = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
    try:
        entries = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return Half(present=False, detail=f"{path} — unreadable: {exc}")

    chunks: dict[str, ChunkRow] = {}
    for entry in entries:
        meta = entry.get("metadata", {})
        chunks[entry["chunk_id"]] = (
            entry.get("content", ""),
            entry.get("content_hash", ""),
            meta.get("source", ""),
            int(meta.get("start_char") or 0),
        )
    detail = f"{path}  {stat.st_size:,} bytes  mtime {when}"
    return Half(present=True, detail=detail, chunks=chunks)


async def read_dense(client: Any, collection: str) -> Half:
    """Every point in the collection, payload only — no vectors pulled."""
    try:
        await client.get_collection(collection)
    except Exception as exc:  # noqa: BLE001 — any failure means "cannot check"
        return Half(present=False, detail=f"{collection} — {exc}")

    chunks: dict[str, ChunkRow] = {}
    offset = None
    while True:
        points, offset = await client.scroll(
            collection_name=collection,
            limit=_SCROLL_BATCH,
            offset=offset,
            with_payload=["content", "content_hash", "source", "start_char"],
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            chunks[str(point.id)] = (
                payload.get("content", ""),
                payload.get("content_hash", ""),
                payload.get("source", ""),
                int(payload.get("start_char") or 0),
            )
        if offset is None:
            break
    return Half(present=True, detail=collection, chunks=chunks)


# ── Header verification ───────────────────────────────────────────────────────


def infer_source_root(sources: set[str]) -> Path | None:
    """The prefix `index_directory` would have stripped, read back off the index.

    Guessing is safe here because the guess is only ever used to *predict* a
    header and compare it against the stored one — a wrong root fails the
    check loudly rather than passing a wrong index.
    """
    real = sorted(s for s in sources if s)
    if not real:
        return None
    try:
        common = Path(os.path.commonpath(real))
    except ValueError:
        # Mixed absolute and relative sources, or different drives.
        return None
    # A single-document namespace commonpaths to the document itself.
    return common.parent if common.suffix else common


async def load_corpus_texts(
    sources: set[str], stored_root: Path | None, corpus: Path | None
) -> dict[str, str]:
    """source -> loader output, which is what `heading_trail` was given at ingest.

    Read through the loaders rather than off disk: the markdown loader is what
    decides where `start_char` counts from, and a raw `read_text()` here would
    disagree with it on any document the loader rewrites.

    A stored source is a path relative to whatever directory the ingest ran in,
    so it only resolves when this runs from there too. --corpus re-roots it,
    keeping the sub-path below *stored_root* — the corpus layout is what the
    header encodes, so flattening to a basename would check the wrong file.
    """
    from atlas.ingestion.loaders.registry import get_loader, is_supported

    texts: dict[str, str] = {}
    for source in sorted(sources):
        path = Path(source)
        if corpus is not None:
            relative = path
            if stored_root is not None:
                with contextlib.suppress(ValueError):
                    relative = path.relative_to(stored_root)
            path = corpus / relative
        if not path.is_file() or not is_supported(path):
            continue
        try:
            documents = await get_loader(path).load(path)
        except Exception:  # noqa: BLE001 — an unreadable file is just unchecked
            continue
        if documents:
            texts[source] = documents[0].content
    return texts


@dataclass
class HeaderReport:
    total: int = 0
    first_line: int = 0  # content opens with the humanised source path
    exact: int = 0  # content opens with the header this code would write
    checkable: int = 0  # chunks whose document text was readable
    misses: list[str] = field(default_factory=list)


def check_headers(half: Half, root: Path | None, texts: dict[str, str]) -> HeaderReport:
    from atlas.ingestion.headers import context_header, humanise_source

    root_str = str(root) if root else None
    report = HeaderReport(total=half.count)
    for chunk_id, (content, _hash, source, start_char) in half.chunks.items():
        where = humanise_source(source, root_str)
        if where and content.startswith(where + "\n"):
            report.first_line += 1

        text = texts.get(source)
        if text is None:
            continue
        report.checkable += 1
        expected = context_header(source, text, start_char, root_str)
        if expected and content.startswith(expected):
            report.exact += 1
        elif len(report.misses) < _SAMPLE:
            report.misses.append(f"{chunk_id}  {source}")
    return report


# ── Reporting ─────────────────────────────────────────────────────────────────


class Report:
    """Accumulates lines and remembers whether anything failed."""

    def __init__(self) -> None:
        self.ok = True
        self._lines: list[str] = []

    def line(self, text: str = "") -> None:
        self._lines.append(text)

    def check(self, passed: bool, text: str) -> None:
        self._lines.append(f"  {'OK  ' if passed else 'FAIL'}  {text}")
        self.ok = self.ok and passed

    def note(self, text: str) -> None:
        self._lines.append(f"  --    {text}")

    def flush(self) -> None:
        print("\n".join(self._lines))
        self._lines.clear()


def compare_halves(report: Report, dense: Half, sparse: Half) -> None:
    """The mismatched-hybrid check: same ids, same text, on both sides."""
    report.check(
        dense.count == sparse.count,
        f"counts agree — dense {dense.count}, sparse {sparse.count}",
    )

    only_dense = set(dense.chunks) - set(sparse.chunks)
    only_sparse = set(sparse.chunks) - set(dense.chunks)
    report.check(
        not only_dense and not only_sparse,
        f"same chunk ids — {len(only_dense)} dense-only, {len(only_sparse)} sparse-only",
    )

    shared = set(dense.chunks) & set(sparse.chunks)
    # The hash is over `content`, headers included, so this is the check that
    # fires in the window between a finished ingest and a landed deploy.
    differing = [cid for cid in shared if dense.chunks[cid][1] != sparse.chunks[cid][1]]
    report.check(
        not differing,
        f"content hashes agree on {len(shared)} shared chunks — {len(differing)} differ",
    )
    for cid in sorted(differing)[:_SAMPLE]:
        report.note(f"differs: {cid}  {dense.chunks[cid][2]}")


def report_headers(report: Report, label: str, hdr: HeaderReport, expected: bool) -> None:
    if hdr.total == 0:
        return
    if hdr.checkable:
        passed = hdr.exact == hdr.checkable if expected else hdr.exact == 0
        report.check(
            passed,
            f"{label} headers — {hdr.exact}/{hdr.checkable} chunks match the header "
            f"this code writes (config says {'on' if expected else 'off'})",
        )
        for miss in hdr.misses:
            report.note(f"no header: {miss}")
    else:
        # Corpus not readable here: a present first line proves a header exists,
        # a stale one that no longer matches the corpus still slips through.
        passed = (hdr.first_line == hdr.total) if expected else (hdr.first_line == 0)
        report.check(
            passed,
            f"{label} headers — {hdr.first_line}/{hdr.total} chunks open with their "
            f"source path (config says {'on' if expected else 'off'}; corpus not "
            f"readable, so this is the weak check)",
        )


# ── Orchestration ─────────────────────────────────────────────────────────────


async def discover_namespaces(client: Any, index_root: Path) -> list[str]:
    """Anything with a collection or a BM25 file — a namespace with only one
    of the two is exactly the state worth reporting, so union, not intersect."""
    from atlas.api.namespaces import collection_to_namespace

    found: set[str] = set()
    if index_root.is_dir():
        for child in index_root.iterdir():
            if (child / "bm25_index.json").exists():
                found.add(child.name)
    if client is not None:
        try:
            collections = await client.get_collections()
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: could not list collections — {exc}", file=sys.stderr)
        else:
            for collection in collections.collections:
                namespace = collection_to_namespace(collection.name)
                if namespace is not None:
                    found.add(namespace)
    return sorted(found)


async def verify_namespace(
    namespace: str, client: Any, corpus: Path | None, expect_headers: bool
) -> bool:
    from atlas.api.namespaces import namespace_to_collection, sparse_index_path

    report = Report()
    report.line(namespace)

    sparse = read_sparse(sparse_index_path(namespace))
    report.line(f"  sparse  {sparse.detail}")
    if sparse.present:
        report.line(f"          {sparse.count} chunks")

    dense = Half(present=False, detail="not checked (--no-dense)")
    if client is not None:
        dense = await read_dense(client, namespace_to_collection(namespace))
    report.line(f"  dense   {dense.detail}")
    if dense.present:
        report.line(f"          {dense.count} points")
    report.line()

    if not sparse.present and not dense.present:
        report.check(False, "namespace has neither a BM25 file nor a collection")
        report.flush()
        return False

    if dense.present and sparse.present:
        compare_halves(report, dense, sparse)
    elif client is not None:
        report.check(False, "only one half of the hybrid index exists")

    sources = {row[2] for half in (dense, sparse) for row in half.chunks.values()}
    # The root the ingest stripped, which is a property of the stored sources —
    # not of where the corpus happens to sit now, which is what --corpus says.
    stored_root = infer_source_root(sources)
    texts = await load_corpus_texts(sources, stored_root, corpus)
    if stored_root is not None:
        where = f" via {corpus}" if corpus else ""
        report.note(
            f"corpus root {stored_root}{where} "
            f"({len(texts)}/{len(sources)} documents readable)"
        )

    for label, half in (("dense ", dense), ("sparse", sparse)):
        if half.present:
            hdr = check_headers(half, stored_root, texts)
            report_headers(report, label, hdr, expect_headers)

    report.flush()
    print()
    return report.ok


async def main(args: argparse.Namespace) -> int:
    from atlas.config import get_settings
    from atlas.logging import configure_logging

    configure_logging(level="WARNING", json=False)
    settings = get_settings()
    expect_headers = settings.chunking.context_headers

    client = None
    if not args.no_dense:
        from qdrant_client import AsyncQdrantClient

        api_key = (
            settings.qdrant.api_key.get_secret_value() if settings.qdrant.api_key else None
        )
        client = AsyncQdrantClient(
            url=settings.qdrant.url,
            api_key=api_key,
            timeout=settings.qdrant.timeout_seconds,
        )

    index_root = Path(os.environ.get("ATLAS_INDEX_DIR", "data/index"))
    corpus = Path(args.corpus) if args.corpus else None

    try:
        namespaces = args.namespace or await discover_namespaces(client, index_root)
        if not namespaces:
            print("No namespaces found. Nothing to verify.")
            return 0

        print("Atlas index verification — read-only, no API spend")
        print(f"index dir: {index_root}   context_headers: {expect_headers}")
        print("-" * 78)

        results = [
            await verify_namespace(ns, client, corpus, expect_headers) for ns in namespaces
        ]
    finally:
        if client is not None:
            await client.close()

    print("-" * 78)
    failed = [ns for ns, ok in zip(namespaces, results, strict=True) if not ok]
    if failed:
        print(f"Inconsistent: {', '.join(failed)}")
        return 1
    print(f"All consistent: {', '.join(namespaces)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Verify what is in each namespace's dense and sparse index.",
    )
    parser.add_argument(
        "--namespace",
        action="append",
        help="Namespace to check; repeatable. Default: every one found.",
    )
    parser.add_argument(
        "--corpus",
        help="Corpus root the sources are relative to. Inferred when omitted.",
    )
    parser.add_argument(
        "--no-dense",
        action="store_true",
        help="Skip Qdrant and check the local BM25 file only.",
    )
    sys.exit(asyncio.run(main(parser.parse_args())))
