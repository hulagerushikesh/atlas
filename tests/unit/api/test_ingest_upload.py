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

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from atlas.config import GENERIC_DOMAIN, IngestConfig, RouterConfig
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


def _describe(client: TestClient, domain: str, namespace: str = "default") -> None:
    """Make *namespace* the one ROUTER_DOMAIN describes, with *domain* as the claim."""
    client.app.state.atlas.registry.settings.router = RouterConfig(
        domain=domain, domain_namespace=namespace
    )


class TestADescribedCorpusRefusesWrites:
    """
    The hole in the 2026-10-13 fix, closed at the write instead of the query.

    `domain_namespace` was added so an uploaded corpus would not be judged
    against a sentence describing someone else's -- and it works for every
    namespace except the one it names, which is also where the console
    uploads by default. A PDF put there indexed cleanly and then answered
    nothing: `Routed out of scope`, 987 ms, no retrieval.

    These pin the refusal *and* its limit. A described corpus is refused; an
    undescribed one, which is every other namespace and also `default` on a
    machine with no ROUTER_DOMAIN set, is written to exactly as before.
    """

    def test_uploading_into_the_described_corpus_is_refused(
        self, client: TestClient
    ) -> None:
        _describe(client, "the FastAPI web framework documentation")

        resp = client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"my own notes", "text/markdown"))],
            data={"namespace": "default"},
        )

        assert resp.status_code == 409

    def test_the_refusal_names_the_claim_and_the_way_out(
        self, client: TestClient
    ) -> None:
        # A bare 409 moves the silence rather than removing it: the caller
        # still cannot tell why this corpus and not another.
        _describe(client, "the FastAPI web framework documentation")

        resp = client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"my own notes", "text/markdown"))],
            data={"namespace": "default"},
        )

        detail = resp.json()["detail"]
        assert "the FastAPI web framework documentation" in detail
        assert "another corpus" in detail

    def test_the_path_endpoint_is_refused_too(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        # Same corpus, same reason. /ingest is the operator's HTTP path, and
        # a described corpus it writes into is just as broken at query time.
        _describe(client, "the FastAPI web framework documentation")
        f = tmp_path / "notes.md"
        f.write_text("my own notes")

        resp = client.post("/ingest", json={"path": str(f), "namespace": "default"})

        assert resp.status_code == 409

    def test_another_namespace_is_written_to_normally(
        self, client: TestClient
    ) -> None:
        # The guard must not generalise into "uploads are off". Every
        # namespace but the described one is routed neutrally and writable.
        _describe(client, "the FastAPI web framework documentation")
        _indexer(client)

        resp = client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"my own notes", "text/markdown"))],
            data={"namespace": "my-notes"},
        )

        assert resp.status_code == 200
        assert resp.json()["namespace"] == "my-notes"

    def test_a_contentless_domain_describes_nothing_so_default_stays_writable(
        self, client: TestClient
    ) -> None:
        # `domain_namespace` defaults to "default" whether or not anyone set
        # a domain, so keying the refusal on the name alone would break every
        # laptop that never configured ROUTER_DOMAIN. GENERIC_DOMAIN claims
        # nothing and so cannot be contradicted.
        _describe(client, GENERIC_DOMAIN)
        _indexer(client)

        resp = client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"my own notes", "text/markdown"))],
            data={"namespace": "default"},
        )

        assert resp.status_code == 200

    def test_the_refusal_costs_nothing(self, client: TestClient) -> None:
        # Refused before the budget check and before the indexer is reached:
        # a write that cannot be accepted must not spend, and must not leave
        # a half-built corpus behind.
        _describe(client, "the FastAPI web framework documentation")
        indexer = _indexer(client)
        spend_before = client.app.state.atlas.spend

        client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"my own notes", "text/markdown"))],
            data={"namespace": "default"},
        )

        indexer.assert_not_awaited()
        assert client.app.state.atlas.spend is spend_before


class TestTheConsoleIsToldBeforeItTries:
    """
    A 409 the user only meets after choosing a file is a worse version of the
    same problem. `/namespaces/{ns}/sources` is refetched on every corpus
    change, so it is where the console learns that a drop zone should be off.
    """

    def test_a_described_corpus_reports_itself_read_only(
        self, client: TestClient
    ) -> None:
        _describe(client, "the FastAPI web framework documentation")

        j = client.get("/namespaces/default/sources").json()

        assert j["writable"] is False
        assert j["description"] == "the FastAPI web framework documentation"

    def test_an_ordinary_corpus_is_writable_and_claims_nothing(
        self, client: TestClient
    ) -> None:
        _describe(client, "the FastAPI web framework documentation")

        j = client.get("/namespaces/my-notes/sources").json()

        assert j["writable"] is True
        # Not the domain sentence: it is not true of this corpus, and showing
        # it here is how the original confusion started.
        assert j["description"] is None


class TestAnIngestDropsTheStaleAnswers:
    """The sequence a first-time user performs, in order.

    Upload a file, ask about it. Before 2026-10-29 the second step could be
    served from a cache populated before the first, so the corpus answered
    from the document set it held up to an hour earlier -- with citations and
    a faithfulness verdict, both honestly earned against the *old* corpus,
    which is what makes a stale cache hit indistinguishable from a correct
    answer. The first real user's first action is an upload, so this is not a
    tail case.
    """

    def test_an_upload_drops_that_namespaces_cached_answers(
        self, client: TestClient
    ) -> None:
        _indexer(client)
        cache = client.app.state.atlas.cache
        asyncio.run(cache.set("what is in my notes?", {"answer": "nothing yet"}, "notes"))

        client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"# Notes\n\nhello", "text/markdown"))],
            data={"namespace": "notes"},
        )

        assert asyncio.run(cache.get("what is in my notes?", "notes")) is None

    def test_an_upload_leaves_other_corpora_alone(self, client: TestClient) -> None:
        # Each surviving entry cost a full paid pipeline run. Writing to one
        # corpus is not a reason to re-buy another's answers.
        _indexer(client)
        cache = client.app.state.atlas.cache
        asyncio.run(cache.set("what is a dependency?", {"answer": "fastapi"}, "default"))

        client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"hello", "text/markdown"))],
            data={"namespace": "notes"},
        )

        kept = asyncio.run(cache.get("what is a dependency?", "default"))
        assert kept is not None and kept["answer"] == "fastapi"

    def test_the_path_endpoint_invalidates_too(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        _confine(client, str(tmp_path))
        f = tmp_path / "doc.txt"
        f.write_text("hello")
        client.app.state.atlas.registry.get.return_value.indexer.index_path = AsyncMock(
            return_value=_result()
        )
        cache = client.app.state.atlas.cache
        asyncio.run(cache.set("q", {"answer": "stale"}, "default"))

        resp = client.post("/ingest", json={"path": str(f)})

        assert resp.status_code == 200
        assert asyncio.run(cache.get("q", "default")) is None

    def test_an_ingest_that_wrote_nothing_keeps_the_cache(
        self, client: TestClient
    ) -> None:
        """Re-running an unchanged ingest is 0.3 s and 0 re-embeds by design.
        Throwing the cache away would make it cost a paid pipeline run per
        cached question instead -- the idempotency would be free in embeddings
        and expensive in generation."""
        client.app.state.atlas.registry.get.return_value.indexer.index_directory = (
            AsyncMock(return_value=_result(docs=0, chunks=0, tokens=0))
        )
        cache = client.app.state.atlas.cache
        asyncio.run(cache.set("q", {"answer": "still correct"}, "notes"))

        client.post(
            "/ingest/upload",
            files=[("files", ("notes.md", b"hello", "text/markdown"))],
            data={"namespace": "notes"},
        )

        kept = asyncio.run(cache.get("q", "notes"))
        assert kept is not None and kept["answer"] == "still correct"
