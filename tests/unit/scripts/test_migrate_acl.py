"""
scripts/migrate_acl.py: every passage written before E2 gets acl = ["all"],
in Qdrant and in the baked keyword files, without touching a passage that
already has a list; --check is the deploy's guard.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import qdrant_client

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "migrate_acl.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("atlas_migrate_acl", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeQdrant:
    """Two Atlas collections and one that is not Atlas's; counts follow writes."""

    def __init__(self, *_: Any, **__: Any) -> None:
        self.points = {"atlas_duckdb": [{}, {}, {"acl": ["group:hr"]}],
                       "atlas_org_a__docs": [{"acl": ["all"]}],
                       "someone_else": [{}]}
        self.indexed: list[str] = []
        _FakeQdrant.last = self

    last: _FakeQdrant

    async def get_collections(self) -> Any:
        return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in self.points])

    async def count(self, name: str, count_filter: Any = None, exact: bool = True) -> Any:
        pts = self.points[name]
        return SimpleNamespace(count=len([p for p in pts if count_filter is None
                                          or "acl" not in p]))

    async def create_payload_index(self, name: str, **_: Any) -> None:
        self.indexed.append(name)

    async def set_payload(self, name: str, payload: dict[str, Any], points: Any,
                          wait: bool) -> None:
        for p in self.points[name]:
            if "acl" not in p:
                p.update(payload)


@pytest.fixture
def mig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    mod = _load()
    (tmp_path / "duckdb").mkdir()
    (tmp_path / "duckdb" / "bm25_index.json").write_text(json.dumps([
        {"chunk_id": "1", "content": "a", "metadata": {"doc_id": "d"}},
        {"chunk_id": "2", "content": "b", "metadata": {"doc_id": "e", "acl": ["group:hr"]}},
    ]))
    monkeypatch.setattr(mod, "INDEX_DIR", tmp_path)
    monkeypatch.setattr(qdrant_client, "AsyncQdrantClient", _FakeQdrant)
    return mod


def _run(mig: Any, **flags: bool) -> int:
    args = argparse.Namespace(apply=flags.get("apply", False), check=flags.get("check", False))
    return int(asyncio.run(mig.main(args)))


def test_a_dry_run_writes_nothing(mig: Any, tmp_path: Path) -> None:
    before = (tmp_path / "duckdb" / "bm25_index.json").read_text()
    assert _run(mig) == 0
    assert _FakeQdrant.last.points["atlas_duckdb"][0] == {}
    assert _FakeQdrant.last.indexed == []
    assert (tmp_path / "duckdb" / "bm25_index.json").read_text() == before


def test_check_refuses_while_any_passage_has_no_list(mig: Any) -> None:
    assert _run(mig, check=True) == 1


def test_apply_opens_old_passages_to_the_sheet_and_leaves_narrowed_ones(
    mig: Any, tmp_path: Path
) -> None:
    assert _run(mig, apply=True) == 0
    q = _FakeQdrant.last
    assert q.points["atlas_duckdb"] == [{"acl": ["all"]}, {"acl": ["all"]},
                                        {"acl": ["group:hr"]}]
    assert q.points["someone_else"] == [{}]                 # not an Atlas collection
    assert q.indexed == ["atlas_duckdb", "atlas_org_a__docs"]
    saved = json.loads((tmp_path / "duckdb" / "bm25_index.json").read_text())
    assert [e["metadata"]["acl"] for e in saved] == [["all"], ["group:hr"]]


def test_rerunning_apply_finds_nothing_left_in_the_files(mig: Any) -> None:
    _run(mig, apply=True)
    assert [n for _, n in mig.patch_bm25_files(apply=False)] == [0]
