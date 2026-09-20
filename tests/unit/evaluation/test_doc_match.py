from __future__ import annotations

from atlas.evaluation.doc_match import chunk_doc_keys, chunk_matches, recalled_ids
from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.retriever import RetrievedChunk


def _chunk(source: str, doc_id: str = "uuid-1") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c1",
        content="x",
        score=1.0,
        metadata=ChunkMetadata(
            doc_id=doc_id, source=source, doc_type=DocumentType.MARKDOWN,
            chunk_index=0, start_char=0, end_char=1,
        ),
    )


def test_keys_cover_id_relpath_and_stem() -> None:
    keys = chunk_doc_keys(_chunk("data/corpus/fastapi/tutorial/security/oauth2-jwt.md"))
    assert {"uuid-1", "tutorial/security/oauth2-jwt", "oauth2-jwt"} <= keys


def test_match_by_relpath_not_uuid() -> None:
    c = _chunk("data/corpus/fastapi/index.md")
    assert chunk_matches(c, {"index"})
    assert not chunk_matches(c, {"tutorial/index"})


def test_recalled_ids_collects_across_chunks() -> None:
    chunks = [
        _chunk("data/corpus/fastapi/tutorial/body.md"),
        _chunk("data/corpus/fastapi/async.md"),
    ]
    assert recalled_ids(chunks, {"tutorial/body", "async", "missing"}) == {"tutorial/body", "async"}
