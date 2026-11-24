"""
E2.2: cached answers and the source list respect document permissions.

The exit test's cached half (docs/e2-permissions.md §3.4–3.5): a person who
asks after someone allowed more never gets that person's answer, a person
with the same access does, and a document the caller cannot open is never
listed, not even by title or by how many passages it has.
"""

# ruff: noqa: F811 -- the sign-in suite's fixtures are imported, then used as arguments

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from atlas.api.cache import QueryCache
from atlas.ingestion.sparse import BM25SparseIndex
from atlas.interfaces.document import Chunk, ChunkMetadata, DocumentType
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.pipeline import RetrievalPass
from tests.unit.api.test_sign_in import (  # noqa: F401 -- pytest fixtures
    CONSOLE,
    Site,
    google_key,
    other_key,
    site,
)


def _chunk(cid: str, acl: list[str]) -> RetrievedChunk:
    return RetrievedChunk(chunk_id=cid, content="salary bands", score=1.0,
                          metadata=ChunkMetadata(
                              doc_id=cid, source=f"{cid}.md", doc_type=DocumentType.MARKDOWN,
                              chunk_index=0, start_char=0, end_char=1, acl=acl))


class TestCacheKey:
    def test_different_access_is_a_different_entry(self) -> None:
        async def run() -> None:
            c = QueryCache()
            await c.set("q", {"a": 1}, "ws", frozenset({"all", "group:hr"}))
            assert await c.get("q", "ws", frozenset({"all"})) is None
            assert await c.get("q", "ws", frozenset({"group:hr", "all"})) == {"a": 1}

        asyncio.run(run())

    def test_an_upload_still_clears_every_access_levels_entries(self) -> None:
        async def run() -> None:
            c = QueryCache()
            await c.set("q", {"a": 1}, "ws", frozenset({"all"}))
            await c.set("q", {"a": 2}, "ws", frozenset({"all", "group:hr"}))
            assert await c.invalidate_namespace("ws") == 2

        asyncio.run(run())


# ── Through the API ──────────────────────────────────────────────────────────

def _uid(c: TestClient) -> str:
    return str(c.get("/auth/me").json()["user"]["id"])


class _Sheet:
    """Acme's `docs` sheet with one open and one HR-only passage."""

    def __init__(self, site: Site) -> None:
        self.site = site
        self.admin = site.sign_in("admin@acme.com")
        r = self.admin.post("/org/groups", headers=CONSOLE, json={"name": "HR"})
        self.hr = r.json()["id"]
        self.ns = site.app.state.atlas.registry.get.return_value
        self.ns.sparse_index.acl_tokens.return_value = frozenset({"all", f"group:{self.hr}"})
        self.pipeline = self.ns.pipeline
        self.runs = 0
        self.answer_from: list[RetrievedChunk] = []
        result = self.pipeline.run.return_value

        async def run(*_: Any, **__: Any) -> Any:
            self.runs += 1
            result.retrieved_chunks = list(self.answer_from)
            return result

        self.pipeline.run = run

        async def search(*_: Any, **__: Any) -> RetrievalPass:
            return RetrievalPass(chunks=list(self.answer_from), evidence=[])

        # What evidence reuse searches with, when it is on.
        self.pipeline._retrieve_all = AsyncMock(side_effect=search)

    def member(self, email: str, groups: list[str]) -> TestClient:
        r = self.admin.post("/org/invitations", headers=CONSOLE,
                            json={"email": email, "roles": {"docs": "reader"}})
        assert r.status_code == 201, r.text
        c = self.site.sign_in(email)
        self.admin.put(f"/org/members/{_uid(c)}", headers=CONSOLE,
                       json={"roles": {"docs": "reader"}, "groups": groups})
        return c

    def ask(self, c: TestClient, q: str = "What are the salary bands?") -> dict[str, Any]:
        r = c.post("/query", headers=CONSOLE, json={"query": q, "namespace": "docs"})
        assert r.status_code == 200, r.text
        body: dict[str, Any] = r.json()
        return body


@pytest.fixture(params=["reuse off", "reuse on, worst case"])
def sheet(site: Site, request: pytest.FixtureRequest) -> _Sheet:
    """Every test below runs twice. The second time evidence reuse (E2.5) is
    on and as gullible as it can be: one shared passage is enough, every
    question means the same, and the fit check always says yes. What still
    stops a leak then is the access check on the stored passages alone."""
    s = _Sheet(site)
    if request.param != "reuse off":
        from tests.unit.api.test_evidence_reuse import StubJudge, _reuse

        site.app.state.atlas.reuse = _reuse(StubJudge(fits=True), min_shared=1,
                                            min_similarity=0.0)
    return s


class TestCachedAnswers:
    def test_someone_allowed_less_never_gets_an_answer_built_for_someone_allowed_more(
        self, sheet: _Sheet
    ) -> None:
        hr = sheet.member("hr@acme.com", ["HR"])
        other = sheet.member("eng@acme.com", [])
        sheet.answer_from = [_chunk("open", ["all"]), _chunk("hr", [f"group:{sheet.hr}"])]
        assert sheet.ask(hr)["cached"] is False
        sheet.answer_from = [_chunk("open", ["all"])]
        assert sheet.ask(other)["cached"] is False
        assert sheet.runs == 2

    def test_people_with_the_same_access_share_answers(self, sheet: _Sheet) -> None:
        a = sheet.member("a@acme.com", [])
        b = sheet.member("b@acme.com", [])
        sheet.answer_from = [_chunk("open", ["all"])]
        sheet.ask(a)
        # `user:{id}` differs between them, but no passage on this sheet is
        # shared with either person, so it does not split the cache.
        assert sheet.ask(b)["cached"] is True
        assert sheet.runs == 1

    def test_a_reworded_question_is_a_fresh_run_not_a_leak(self, sheet: _Sheet) -> None:
        hr = sheet.member("hr@acme.com", ["HR"])
        other = sheet.member("eng@acme.com", [])
        sheet.answer_from = [_chunk("hr", [f"group:{sheet.hr}"])]
        sheet.ask(hr, "What are the salary bands?")
        sheet.answer_from = []
        assert sheet.ask(other, "salary bands, what are they")["cached"] is False

    def test_a_stale_index_cannot_leak_through_a_shared_key(self, sheet: _Sheet) -> None:
        # This server's keyword copy has not yet seen the HR-only document, so
        # both people's keys are {"all"}; the stored passage lists catch it.
        sheet.ns.sparse_index.acl_tokens.return_value = frozenset({"all"})
        hr = sheet.member("hr@acme.com", ["HR"])
        other = sheet.member("eng@acme.com", [])
        sheet.answer_from = [_chunk("hr", [f"group:{sheet.hr}"])]
        sheet.ask(hr)
        sheet.answer_from = [_chunk("open", ["all"])]
        assert sheet.ask(other)["cached"] is False
        assert sheet.runs == 2

    def test_an_entry_from_before_e2_is_never_served(self, sheet: _Sheet) -> None:
        other = sheet.member("eng@acme.com", [])
        ws = sheet.site.ws["a/docs"]
        cache = sheet.site.app.state.atlas.cache
        asyncio.run(cache.set("What are the salary bands?", {"answer": "old"}, ws,
                              frozenset({"all"})))
        assert sheet.ask(other)["cached"] is False

    def test_a_streamed_answer_is_held_to_the_same_rules(self, sheet: _Sheet) -> None:
        hr = sheet.member("hr@acme.com", ["HR"])
        other = sheet.member("eng@acme.com", [])
        sheet.pipeline._retrieve_all = AsyncMock(return_value=RetrievalPass(
            chunks=[_chunk("hr", [f"group:{sheet.hr}"])], evidence=[]))
        body = {"query": "What are the salary bands?", "namespace": "docs", "stream": True}
        first = hr.post("/query", headers=CONSOLE, json=body)
        assert first.headers["X-Cache"] == "miss"
        again = hr.post("/query", headers=CONSOLE, json=body)
        assert again.headers["X-Cache"] == "hit"          # it was stored
        sheet.pipeline._retrieve_all = AsyncMock(return_value=RetrievalPass(
            chunks=[_chunk("open", ["all"])], evidence=[]))
        assert other.post("/query", headers=CONSOLE, json=body).headers["X-Cache"] == "miss"


class TestSourceList:
    @pytest.fixture
    def listed(self, sheet: _Sheet, tmp_path: Path) -> _Sheet:
        idx = BM25SparseIndex(tmp_path / "bm25.json")

        def c(doc: str, i: int, acl: list[str]) -> Chunk:
            return Chunk(content=f"text {doc} {i}", metadata=ChunkMetadata(
                doc_id=doc, source=f"{doc}.md", doc_type=DocumentType.MARKDOWN,
                chunk_index=i, start_char=0, end_char=1, content_hash=f"{doc}{i}", acl=acl))

        asyncio.run(idx.upsert([c("handbook", 0, ["all"]), c("handbook", 1, ["all"]),
                                c("salaries-2026", 0, [f"group:{sheet.hr}"])]))
        sheet.ns.sparse_index = idx
        sheet.site.app.state.atlas.registry.dense_chunk_count = AsyncMock(return_value=3)
        return sheet

    def test_a_document_the_caller_cannot_open_is_not_listed(self, listed: _Sheet) -> None:
        other = listed.member("eng@acme.com", [])
        body = other.get("/namespaces/docs/sources").json()
        assert [s["source"] for s in body["sources"]] == ["handbook.md"]
        assert "salaries" not in str(body)
        # Nor is how much is hidden: its counts are its own.
        assert (body["total_chunks"], body["dense_chunks"], body["consistent"]) == (2, 2, True)
        assert body["warning"] is None

    def test_a_group_member_sees_it(self, listed: _Sheet) -> None:
        hr = listed.member("hr@acme.com", ["HR"])
        body = hr.get("/namespaces/docs/sources").json()
        assert {s["source"] for s in body["sources"]} == {"handbook.md", "salaries-2026.md"}
        assert body["dense_chunks"] == 3

    def test_a_mismatch_is_reported_without_numbers_to_someone_who_cannot_see_all(
        self, listed: _Sheet
    ) -> None:
        listed.site.app.state.atlas.registry.dense_chunk_count = AsyncMock(return_value=5)
        body = listed.member("eng@acme.com", []).get("/namespaces/docs/sources").json()
        assert body["consistent"] is False and body["dense_chunks"] is None
        assert not any(ch.isdigit() for ch in body["warning"])
