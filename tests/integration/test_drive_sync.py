"""
E3.1 and E3.2 end to end without Google: a fake Drive folder synced by the real
indexer into a real (in-memory) Qdrant and BM25 index, then searched by both
retrievers as different people. Proves the claim the connector exists for:
a person Drive does not share a file with gets nothing from it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from qdrant_client import AsyncQdrantClient

from atlas.access import set_reader_access
from atlas.api.tenancy import Principal
from atlas.config import QdrantConfig
from atlas.connectors.drive import (
    GOOGLE_DOC,
    DriveFile,
    DrivePermission,
    drive_doc_id,
    sync_folder,
)
from atlas.ingestion.chunkers.fixed import FixedSizeChunker
from atlas.ingestion.dense import QdrantDenseIndex
from atlas.ingestion.indexer import DocumentIndexer
from atlas.ingestion.sparse import BM25SparseIndex
from atlas.retrieval.dense import QdrantDenseRetriever
from atlas.retrieval.sparse import BM25Retriever
from tests.integration.test_qdrant_roundtrip import DIMENSIONS, StubEmbedder


class FakeDrive:
    """A folder: file -> (text, sharing). Sharing None = hidden from the connector."""

    def __init__(self) -> None:
        self.files: dict[str, tuple[DriveFile, str, list[DrivePermission] | None]] = {}
        self.downloads = 0

    def add(self, fid: str, path: str, text: str, perms: list[DrivePermission] | None,
            version: str = "1", mime: str = GOOGLE_DOC) -> None:
        self.files[fid] = (DriveFile(id=fid, name=path.rsplit("/", 1)[-1], mime_type=mime,
                                     path=path, version=version, size=len(text)), text, perms)

    async def walk(self, folder_id: str) -> list[DriveFile]:
        return [f for f, _, _ in self.files.values()]

    async def permissions(self, file_id: str) -> list[DrivePermission] | None:
        return self.files[file_id][2]

    async def download(self, file: DriveFile) -> bytes:
        self.downloads += 1
        return self.files[file.id][1].encode()


def user(email: str) -> DrivePermission:
    return DrivePermission(type="user", email=email)


@pytest.fixture
def world(tmp_path: Path) -> Any:
    config = QdrantConfig(url="http://unused", collection_name="drive")
    client = AsyncQdrantClient(":memory:")
    embedder = StubEmbedder()
    dense = QdrantDenseIndex(config, dimensions=DIMENSIONS)
    dense._client = client
    asyncio.run(dense.ensure_collection())
    sparse = BM25SparseIndex(tmp_path / "bm25.json")
    indexer = DocumentIndexer(chunker=FixedSizeChunker(size=400, overlap=20),
                              embedder=embedder, dense_index=dense, sparse_index=sparse)
    retriever = QdrantDenseRetriever(config, embedder)
    retriever._client = client
    return indexer, retriever, BM25Retriever(sparse)


async def _found(world: Any, who: Principal, query: str) -> set[str]:
    _, dense, sparse = world

    async def search() -> set[str]:
        set_reader_access(who.access)
        found = set()
        for r in (dense, sparse):
            found |= {c.metadata.doc_id for c in (await r.retrieve(query, top_k=10)).chunks}
        return found

    return await asyncio.create_task(search())


def _versions(held: dict[str, str]) -> dict[str, str]:
    return {k: v.partition("|")[0] for k, v in held.items()}


ALICE = Principal(kind="user", subject_id="u1", org_id="o", email="alice@acme.com",
                  hosted_domain="acme.com")
BOB = Principal(kind="user", subject_id="u2", org_id="o", email="bob@gmail.com")
KEY = Principal(kind="service", subject_id="k1", org_id="o")


class TestSharingReachesSearch:
    def test_each_person_finds_only_what_drive_shares_with_them(self, world: Any) -> None:
        drive = FakeDrive()
        drive.add("f1", "Salary bands.md", "salary bands for engineers", [user("alice@acme.com")])
        drive.add("f2", "Handbook.md", "salary bands handbook overview",
                  [DrivePermission(type="anyone")])
        drive.add("f3", "Domain.md", "salary bands across acme",
                  [DrivePermission(type="domain", domain="acme.com")])

        async def go() -> None:
            report, held = await sync_folder(drive, world[0], "root", {}, {})
            assert report.indexed == 3 and set(held) == {"f1", "f2", "f3"}
            q = "salary bands"
            assert await _found(world, ALICE, q) == {drive_doc_id(f) for f in ("f1", "f2", "f3")}
            assert await _found(world, BOB, q) == {drive_doc_id("f2")}
            assert await _found(world, KEY, q) == {drive_doc_id("f2")}   # keys hold no email

        asyncio.run(go())

    def test_unsharing_in_drive_takes_it_away_on_the_next_sync(self, world: Any) -> None:
        drive = FakeDrive()
        drive.add("f1", "Plan.md", "quarterly plan budget", [user("bob@gmail.com")])

        async def go() -> None:
            _, held = await sync_folder(drive, world[0], "root", {}, {})
            assert await _found(world, BOB, "quarterly plan") == {drive_doc_id("f1")}
            drive.add("f1", "Plan.md", "quarterly plan budget", [user("alice@acme.com")])
            report, held = await sync_folder(drive, world[0], "root", held, {})
            assert report.access_changed == 1 and drive.downloads == 1   # no re-download
            assert await _found(world, BOB, "quarterly plan") == set()
            assert await _found(world, ALICE, "quarterly plan") == {drive_doc_id("f1")}

        asyncio.run(go())

    def test_an_unshare_that_moves_the_version_embeds_nothing(self, world: Any) -> None:
        # Real Drive moves a file's version on a sharing change too.
        drive = FakeDrive()
        drive.add("f1", "Plan.md", "quarterly plan budget", [user("bob@gmail.com")])

        async def go() -> None:
            _, held = await sync_folder(drive, world[0], "root", {}, {})
            indexed: list[Any] = []
            real = world[0].index_documents

            async def spy(docs: list[Any]) -> Any:
                indexed.append(docs)
                return await real(docs)

            world[0].index_documents = spy
            drive.add("f1", "Plan.md", "quarterly plan budget", [user("alice@acme.com")],
                      version="2")
            report, held = await sync_folder(drive, world[0], "root", held, {})
            assert (report.indexed, report.access_changed) == (0, 1)
            assert indexed == [] and drive.downloads == 2    # read, compared, kept
            assert await _found(world, BOB, "quarterly plan") == set()
            assert await _found(world, ALICE, "quarterly plan") == {drive_doc_id("f1")}

        asyncio.run(go())

    def test_deleting_in_drive_removes_every_passage(self, world: Any) -> None:
        drive = FakeDrive()
        drive.add("f1", "Plan.md", "quarterly plan budget", [DrivePermission(type="anyone")])

        async def go() -> None:
            _, held = await sync_folder(drive, world[0], "root", {}, {})
            del drive.files["f1"]
            report, held = await sync_folder(drive, world[0], "root", held, {})
            assert report.removed == 1 and held == {}
            assert await _found(world, ALICE, "quarterly plan") == set()
            assert await world[0].document_acl(drive_doc_id("f1")) is None

        asyncio.run(go())

    def test_sharing_the_connector_cannot_see_is_never_indexed(self, world: Any) -> None:
        drive = FakeDrive()
        drive.add("f1", "Hidden.md", "secret merger notes", None)

        async def go() -> None:
            report, held = await sync_folder(drive, world[0], "root", {}, {})
            assert report.closed == ["Hidden.md"] and held == {} and drive.downloads == 0
            assert await _found(world, ALICE, "merger") == set()

        asyncio.run(go())

    def test_an_edit_is_re_read_and_a_rename_is_the_same_document(self, world: Any) -> None:
        drive = FakeDrive()
        drive.add("f1", "Old name.md", "original wording", [DrivePermission(type="anyone")])

        async def go() -> None:
            _, held = await sync_folder(drive, world[0], "root", {}, {})
            drive.add("f1", "New name.md", "revised wording entirely",
                      [DrivePermission(type="anyone")], version="2")
            report, held = await sync_folder(drive, world[0], "root", held, {})
            assert report.indexed == 1 and report.removed == 0 and _versions(held) == {"f1": "2"}
            hits = await _found(world, ALICE, "revised wording")
            assert hits == {drive_doc_id("f1")}

        asyncio.run(go())

    def test_re_sharing_brings_it_back(self, world: Any) -> None:
        drive = FakeDrive()
        drive.add("f1", "Plan.md", "quarterly plan budget", [user("bob@gmail.com")])

        async def go() -> None:
            _, held = await sync_folder(drive, world[0], "root", {}, {})
            drive.add("f1", "Plan.md", "quarterly plan budget", [])      # unshared: nobody
            _, held = await sync_folder(drive, world[0], "root", held, {})
            assert await _found(world, BOB, "quarterly plan") == set()
            drive.add("f1", "Plan.md", "quarterly plan budget", [user("bob@gmail.com")])
            report, held = await sync_folder(drive, world[0], "root", held, {})
            assert report.indexed == 1 and _versions(held) == {"f1": "1"}
            assert await _found(world, BOB, "quarterly plan") == {drive_doc_id("f1")}

        asyncio.run(go())

    def test_a_re_run_changes_nothing_and_the_list_marks_it_synced(self, world: Any) -> None:
        drive = FakeDrive()
        drive.add("f1", "Plan.md", "quarterly plan budget", [DrivePermission(type="anyone")])

        async def go() -> None:
            _, held = await sync_folder(drive, world[0], "root", {}, {})
            report, again = await sync_folder(drive, world[0], "root", held, {})
            assert (report.indexed, report.access_changed, report.removed) == (0, 0, 0)
            assert again == held and drive.downloads == 1
            rows = world[0]._sparse.sources(synced=frozenset({drive_doc_id("f1")}))
            assert rows == [{"source": "Plan.md", "doc_type": "markdown", "chunks": 1,
                             "synced": True}]

        asyncio.run(go())
