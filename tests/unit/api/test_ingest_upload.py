"""
Building a corpus from a browser, and the file-read hole that made it possible.

`POST /ingest` names a path on the *server*. A console running on a laptop
cannot do that, so the criterion "a new corpus can be created, ingested and
queried entirely from the console" needed a route that takes bytes --
`/ingest/upload`.

The same endpoint had no confinement. Whatever is indexed can be retrieved
through `/query`, so an unconfined path argument turned the index into a
file-read channel for anything the process could open, for any caller holding
a key. Both halves are pinned here.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from atlas.config import IngestConfig
from atlas.ingestion.indexer import IndexResult


def _result(docs: int = 1, chunks: int = 3, tokens: int = 100) -> IndexResult:
    r = IndexResult()
    r.documents_processed = docs
    r.documents_skipped = 0
    r.chunks_indexed = chunks
    r.total_tokens = tokens
    return r


def _indexer(client: TestClient) -> AsyncMock:
    mock = AsyncMock(return_value=_result())
    client.app.state.atlas.registry.get.return_value.indexer.index_directory = mock
    return mock


def _confine(client: TestClient, root: str) -> None:
    client.app.state.atlas.ingest = IngestConfig(root=root)


class TestThePathEndpointIsConfined:
    def test_a_path_outside_the_root_is_refused(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        _confine(client, str(tmp_path / "corpus"))
        (tmp_path / "corpus").mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("an api key, or anything else the process can read")

        resp = client.post("/ingest", json={"path": str(secret)})

        assert resp.status_code == 403
        assert "outside the permitted ingest root" in resp.json()["detail"]

    def test_dot_dot_cannot_climb_out(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        root = tmp_path / "corpus"
        root.mkdir()
        _confine(client, str(root))
        (tmp_path / "secret.txt").write_text("x")

        resp = client.post("/ingest", json={"path": f"{root}/../secret.txt"})

        assert resp.status_code == 403

    def test_a_symlink_out_of_the_root_cannot_either(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        # The reason the check resolves before comparing: this path *starts*
        # with the root as a string, and a prefix test on the raw text passes.
        root = tmp_path / "corpus"
        root.mkdir()
        _confine(client, str(root))
        outside = tmp_path / "secret.txt"
        outside.write_text("x")
        os.symlink(outside, root / "innocent.txt")

        resp = client.post("/ingest", json={"path": str(root / "innocent.txt")})

        assert resp.status_code == 403

    def test_the_refusal_comes_before_the_existence_check(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        # Otherwise a 404-vs-403 difference answers "does this file exist on
        # the server?" for any path the caller cares to name.
        root = tmp_path / "corpus"
        root.mkdir()
        _confine(client, str(root))

        missing = client.post("/ingest", json={"path": "/etc/does-not-exist-xyz"})
        present = client.post("/ingest", json={"path": "/etc/hosts"})

        assert missing.status_code == 403
        assert present.status_code == 403

    def test_a_path_inside_the_root_is_allowed(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        _confine(client, str(tmp_path))
        f = tmp_path / "doc.txt"
        f.write_text("hello")
        client.app.state.atlas.registry.get.return_value.indexer.index_path = AsyncMock(
            return_value=_result()
        )

        resp = client.post("/ingest", json={"path": str(f)})

        assert resp.status_code == 200

    def test_an_empty_root_turns_the_check_off(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        # The documented escape hatch for a single-user API on a laptop, where
        # the caller and the filesystem owner are the same person.
        _confine(client, "")
        f = tmp_path / "doc.txt"
        f.write_text("hello")
        client.app.state.atlas.registry.get.return_value.indexer.index_path = AsyncMock(
            return_value=_result()
        )

        resp = client.post("/ingest", json={"path": str(f)})

        assert resp.status_code == 200

    def test_the_shipped_default_is_confined(self) -> None:
        # The value that matters: a deployment that sets nothing must not be
        # the unconfined one.
        assert IngestConfig().root == "data"


class TestUploadingACorpus:
    def test_files_are_indexed_into_the_named_namespace(
        self, client: TestClient
    ) -> None:
        index = _indexer(client)

        resp = client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"# Notes\n\nhello", "text/markdown"))],
            data={"namespace": "brand-new"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["namespace"] == "brand-new"
        assert body["accepted"] == ["notes.md"]
        assert body["chunks_indexed"] == 3
        # The corpus is created by being written to -- this is what "a new
        # corpus can be created from the console" rests on.
        client.app.state.atlas.registry.get.assert_called_with("brand-new")
        assert index.await_count == 1

    def test_the_source_root_is_the_temp_dir_not_the_machine(
        self, client: TestClient
    ) -> None:
        # Otherwise every chunk's context header carries /var/folders/T/tmpXXX
        # and the same file ingested any other way disagrees with it.
        index = _indexer(client)

        client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"hello", "text/markdown"))],
        )

        target = index.await_args.args[0]
        assert index.await_args.kwargs["source_root"] == target

    def test_the_stored_source_is_the_filename_not_the_temp_path(
        self, client: TestClient
    ) -> None:
        # source_root alone only governs the context header. Without this the
        # stored source stays absolute, and a citation in the console read
        # `/var/folders/nt/brcjvzln1.../T/atlas-upload-g154heox/field-notes.md`
        # on 2026-10-13 -- unusable to the reader, and a published map of the
        # server's filesystem.
        index = _indexer(client)

        client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"hello", "text/markdown"))],
        )

        assert index.await_args.kwargs["relative_sources"] is True

    def test_the_temp_dir_is_gone_afterwards(self, client: TestClient) -> None:
        index = _indexer(client)

        client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"hello", "text/markdown"))],
        )

        assert not Path(index.await_args.args[0]).exists()

    def test_the_temp_dir_is_gone_even_when_indexing_fails(
        self, client: TestClient
    ) -> None:
        calls: list[Path] = []

        async def boom(target: Path, **kwargs: object) -> None:
            calls.append(target)
            raise RuntimeError("qdrant went away")

        client.app.state.atlas.registry.get.return_value.indexer.index_directory = boom

        resp = client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"hello", "text/markdown"))],
        )

        assert resp.status_code == 500
        assert calls and not calls[0].exists(), "a failed upload must not leave bytes behind"


class TestWhatUploadRefuses:
    def test_an_unsupported_extension_is_named_not_dropped(
        self, client: TestClient
    ) -> None:
        _indexer(client)

        resp = client.post(
            "/ingest/upload",
            files=[
                ("files", ("notes.md", b"hello", "text/markdown")),
                ("files", ("binary.exe", b"MZ\x90\x00", "application/octet-stream")),
            ],
        )

        body = resp.json()
        assert body["accepted"] == ["notes.md"]
        [bad] = body["rejected"]
        assert bad["filename"] == "binary.exe"
        assert ".exe" in bad["reason"]

    def test_an_empty_file_is_refused(self, client: TestClient) -> None:
        _indexer(client)

        resp = client.post(
            "/ingest/upload",
            files=[
                ("files", ("notes.md", b"hello", "text/markdown")),
                ("files", ("empty.md", b"", "text/markdown")),
            ],
        )

        assert [r["filename"] for r in resp.json()["rejected"]] == ["empty.md"]

    def test_a_file_over_the_byte_limit_is_refused(self, client: TestClient) -> None:
        _indexer(client)
        client.app.state.atlas.ingest = IngestConfig(max_upload_bytes=10)

        resp = client.post(
            "/ingest/upload",
            files=[("files", ("big.md", b"x" * 11, "text/markdown"))],
        )

        assert resp.status_code == 422
        assert "over the 10-byte file limit" in str(resp.json()["detail"])

    def test_the_file_count_limit_is_enforced(self, client: TestClient) -> None:
        _indexer(client)
        client.app.state.atlas.ingest = IngestConfig(max_upload_files=2)

        resp = client.post(
            "/ingest/upload",
            files=[
                ("files", (f"n{i}.md", b"hello", "text/markdown")) for i in range(4)
            ],
        )

        body = resp.json()
        assert len(body["accepted"]) == 2
        assert len(body["rejected"]) == 2
        assert all("file limit" in r["reason"] for r in body["rejected"])

    def test_the_request_total_is_capped(self, client: TestClient) -> None:
        _indexer(client)
        client.app.state.atlas.ingest = IngestConfig(max_upload_total_bytes=12)

        resp = client.post(
            "/ingest/upload",
            files=[
                ("files", ("a.md", b"x" * 10, "text/markdown")),
                ("files", ("b.md", b"x" * 10, "text/markdown")),
            ],
        )

        body = resp.json()
        assert body["accepted"] == ["a.md"]
        assert "total" in body["rejected"][0]["reason"]

    def test_everything_refused_is_a_422_carrying_the_reasons(
        self, client: TestClient
    ) -> None:
        # Not a 200 with zeroes: the caller sent files and none were indexed.
        _indexer(client)

        resp = client.post(
            "/ingest/upload",
            files=[("files", ("binary.exe", b"MZ", "application/octet-stream"))],
        )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["rejected"][0]["filename"] == "binary.exe"

    def test_a_traversing_filename_is_reduced_to_its_basename(
        self, client: TestClient
    ) -> None:
        # `filename` comes from the client. Without the basename it chooses
        # where the bytes land, so this checks where they actually landed --
        # read inside the index call, because the directory is deleted after.
        seen: list[Path] = []

        async def record(target: Path, **kwargs: object) -> IndexResult:
            seen.extend(target.iterdir())
            return _result()

        client.app.state.atlas.registry.get.return_value.indexer.index_directory = record

        resp = client.post(
            "/ingest/upload",
            files=[("files", ("../../escaped.md", b"hello", "text/markdown"))],
        )

        assert resp.json()["accepted"] == ["escaped.md"]
        assert [p.name for p in seen] == ["escaped.md"]
        assert all(p.parent.name.startswith("atlas-upload-") for p in seen), (
            f"bytes landed outside the upload temp dir: {seen}"
        )

    def test_an_exhausted_budget_stops_the_upload(self, client: TestClient) -> None:
        # budget_usd=0 disables the meter rather than exhausting it, so the cap
        # is tripped the way the budget suite does it: a backend that already
        # holds today's spend.
        from atlas.api.budget import SpendMeter
        from tests.unit.api.test_budget import _SpentBackend
        _indexer(client)
        client.app.state.atlas.spend = SpendMeter(
            budget_usd=0.01, backend=_SpentBackend(0.01)
        )

        resp = client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"hello", "text/markdown"))],
        )

        assert resp.status_code == 429
        assert resp.headers["Retry-After"]
