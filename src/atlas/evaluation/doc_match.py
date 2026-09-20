"""
Matching a dataset's relevant_doc_ids against retrieved chunks.

Design rationale:
    Datasets name documents the way a human would — "tutorial/path-params",
    "index" — not by the uuid5 the ingester assigns. A chunk therefore
    exposes several keys and a relevant id matches if it equals any of them:

      - metadata.doc_id                      (the uuid5)
      - metadata.source                      (full path as ingested)
      - source relative to the corpus root,  e.g. "tutorial/security/oauth2-jwt"
        without extension
      - the file stem,                       e.g. "oauth2-jwt"

    The relative form is the one datasets should use; the stem is a
    convenience that is ambiguous for names like "index".
"""

from __future__ import annotations

from pathlib import PurePosixPath

from atlas.interfaces.retriever import RetrievedChunk

_CORPUS_MARKER = "corpus"


def chunk_doc_keys(chunk: RetrievedChunk) -> set[str]:
    meta = chunk.metadata
    keys = {meta.doc_id, meta.source}
    path = PurePosixPath(meta.source)
    no_ext = path.with_suffix("") if path.suffix else path
    keys.add(no_ext.name)
    parts = no_ext.parts
    # data/corpus/<name>/a/b.md -> a/b ; anything without the marker keeps
    # its own relative path
    if _CORPUS_MARKER in parts:
        idx = parts.index(_CORPUS_MARKER)
        rel = parts[idx + 2 :] if len(parts) > idx + 2 else parts[idx + 1 :]
        if rel:
            keys.add("/".join(rel))
    keys.add(str(no_ext))
    return keys


def chunk_matches(chunk: RetrievedChunk, relevant: set[str]) -> bool:
    return not relevant.isdisjoint(chunk_doc_keys(chunk))


def recalled_ids(chunks: list[RetrievedChunk], relevant: set[str]) -> set[str]:
    """Subset of `relevant` that at least one chunk matches."""
    found: set[str] = set()
    for c in chunks:
        found |= relevant & chunk_doc_keys(c)
    return found
