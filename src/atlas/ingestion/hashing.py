"""
Content hashing utilities for idempotent indexing.

Design rationale:
    xxhash (specifically xxh3_64) is used instead of SHA-256 because we need
    change detection, not collision resistance. xxh3_64 runs at ~30 GB/s on
    modern hardware vs ~0.5 GB/s for SHA-256 — meaningful when hashing many
    large PDFs at startup. The 64-bit hash space (1.8 × 10^19 values) gives
    negligible collision probability for typical document corpora.

    We hash the raw bytes of the source file, not the extracted text, so that
    a re-extraction (e.g. after upgrading the PDF parser) also triggers
    re-indexing. This avoids stale chunks from old parse results.
"""

from __future__ import annotations

import xxhash


def hash_bytes(data: bytes) -> str:
    """Return hex digest of raw bytes using xxh3_64."""
    return xxhash.xxh3_64(data).hexdigest()


def hash_text(text: str) -> str:
    """Return hex digest of a UTF-8 string."""
    return hash_bytes(text.encode("utf-8"))
