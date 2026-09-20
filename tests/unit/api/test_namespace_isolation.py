"""
Namespace isolation for the sparse index.

Found on the first live run: every namespace shared one bm25_index.json, so
chunks ingested into one tenant were retrievable from another, and the CLI
ingest wrote to a collection the API never read.
"""

from __future__ import annotations

from pathlib import Path

from atlas.api.namespaces import namespace_to_collection, sparse_index_path


def test_sparse_index_path_is_per_namespace(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("ATLAS_INDEX_DIR", raising=False)
    a = sparse_index_path("tenant-a")
    b = sparse_index_path("tenant-b")
    assert a != b
    assert a == Path("data/index/tenant-a/bm25_index.json")


def test_sparse_index_root_is_overridable(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ATLAS_INDEX_DIR", str(tmp_path))
    assert sparse_index_path("x") == tmp_path / "x" / "bm25_index.json"


def test_collection_follows_namespace() -> None:
    assert namespace_to_collection("default") == "atlas_default"
