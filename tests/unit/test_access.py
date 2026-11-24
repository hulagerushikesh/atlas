"""
E2.1: access lists on passages, filtered inside both searches.

docs/e2-permissions.md §2–3. A passage is readable when its access list
shares a token with the caller's; a passage with no list is readable by no
request; outside a request (scripts) nothing is filtered.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from qdrant_client.models import FieldCondition, Filter, MatchAny

from atlas.access import readable, reader_access, set_reader_access
from atlas.api.tenancy import ANONYMOUS, Principal, Role, legacy_key_principal
from atlas.ingestion.sparse import BM25SparseIndex
from atlas.interfaces.document import Chunk, ChunkMetadata, DocumentType
from atlas.retrieval.dense import QdrantDenseRetriever, _access_filter
from atlas.retrieval.sparse import BM25Retriever


def _chunk(doc: str, text: str, acl: list[str]) -> Chunk:
    return Chunk(content=text, metadata=ChunkMetadata(
        doc_id=doc, source=f"{doc}.md", doc_type=DocumentType.MARKDOWN, chunk_index=0,
        start_char=0, end_char=len(text), content_hash=doc, acl=acl))


@pytest.fixture
def index(tmp_path: Path) -> BM25SparseIndex:
    idx = BM25SparseIndex(tmp_path / "bm25.json")
    asyncio.run(idx.upsert([
        _chunk("open", "salary bands are public knowledge", ["all"]),
        _chunk("hr", "salary bands for each level, confidential", ["group:hr"]),
        _chunk("mine", "my own salary note", ["user:usr_1"]),
    ]))
    # A passage written before E2, as the keyword file holds it: no acl.
    idx._corpus.append({"chunk_id": "old", "content": "salary from before E2",
                        "content_hash": "old", "metadata": {
                            "doc_id": "old", "source": "old.md", "doc_type": "markdown",
                            "chunk_index": 0, "start_char": 0, "end_char": 1}})
    idx._rebuild()
    return idx


def _docs(idx: BM25SparseIndex, access: frozenset[str] | None) -> set[str]:
    return {e["metadata"]["doc_id"] for e, _ in idx.search("salary", 10, access)}


class TestReadable:
    def test_shared_token_reads(self) -> None:
        assert readable(["group:hr"], frozenset({"all", "group:hr"}))

    def test_no_shared_token_does_not(self) -> None:
        assert not readable(["group:hr"], frozenset({"all"}))

    def test_a_passage_without_a_list_is_readable_by_no_request(self) -> None:
        assert not readable(None, frozenset({"all"}))
        assert not readable([], frozenset({"all"}))

    def test_outside_a_request_nothing_is_filtered(self) -> None:
        assert readable(None, None)


class TestKeywordSearch:
    def test_everyone_on_the_sheet_reads_only_open_passages(self, index: BM25SparseIndex) -> None:
        assert _docs(index, frozenset({"all"})) == {"open"}

    def test_a_group_member_also_reads_the_groups(self, index: BM25SparseIndex) -> None:
        assert _docs(index, frozenset({"all", "group:hr"})) == {"open", "hr"}

    def test_a_person_reads_what_is_shared_with_them(self, index: BM25SparseIndex) -> None:
        assert _docs(index, frozenset({"all", "user:usr_1"})) == {"open", "mine"}

    def test_no_tokens_reads_nothing(self, index: BM25SparseIndex) -> None:
        assert _docs(index, frozenset()) == set()

    def test_a_scripts_search_is_unfiltered(self, index: BM25SparseIndex) -> None:
        assert _docs(index, None) == {"open", "hr", "mine", "old"}

    def test_forbidden_entries_do_not_take_top_k_places(self, index: BM25SparseIndex) -> None:
        # top_k=1: the forbidden "hr" passage scores well but must not be
        # the one place handed out, leaving the reader with nothing.
        hits = index.search("salary bands confidential level", 1, frozenset({"all"}))
        assert [e["metadata"]["doc_id"] for e, _ in hits] == ["open"]

    def test_the_access_list_survives_a_restart(self, index: BM25SparseIndex,
                                                 tmp_path: Path) -> None:
        saved = json.loads((tmp_path / "bm25.json").read_text())
        assert {e["metadata"]["doc_id"]: e["metadata"]["acl"] for e in saved} == {
            "open": ["all"], "hr": ["group:hr"], "mine": ["user:usr_1"]}

    def test_the_retriever_reads_the_requests_access(self, index: BM25SparseIndex) -> None:
        async def ask() -> set[str]:
            set_reader_access({"all"})
            result = await BM25Retriever(index).retrieve("salary", 10)
            return {c.metadata.doc_id for c in result.chunks}

        assert asyncio.run(ask()) == {"open"}


class TestDenseSearch:
    def test_the_filter_is_inside_the_search(self) -> None:
        f = _access_filter(frozenset({"group:hr", "all"}))
        assert f == Filter(must=[FieldCondition(key="acl",
                                                match=MatchAny(any=["all", "group:hr"]))])

    def test_an_empty_token_set_still_filters(self) -> None:
        f = _access_filter(frozenset())
        assert f is not None and f.must[0].match == MatchAny(any=[])  # type: ignore[index,union-attr]

    def test_outside_a_request_there_is_no_filter(self) -> None:
        assert _access_filter(None) is None

    def test_qdrant_is_asked_with_the_requests_filter(self) -> None:
        r = QdrantDenseRetriever.__new__(QdrantDenseRetriever)
        r._config = SimpleNamespace(collection_name="atlas_x")  # type: ignore[assignment]
        r._client = SimpleNamespace(query_points=AsyncMock(  # type: ignore[assignment]
            return_value=SimpleNamespace(points=[])))

        async def ask() -> None:
            set_reader_access({"all", "group:hr"})
            await r._query_points([0.1], 5)

        asyncio.run(ask())
        sent = r._client.query_points.call_args.kwargs["query_filter"]
        assert sent == _access_filter(frozenset({"all", "group:hr"}))


class TestNewPassages:
    def test_are_open_to_the_sheet_by_default(self) -> None:
        # D9 (b): a new upload is open to everyone on its sheet.
        assert _chunk("d", "x", ["all"]).metadata.model_dump()["acl"] == ["all"]
        meta = ChunkMetadata(doc_id="d", source="d.md", doc_type=DocumentType.TEXT,
                             chunk_index=0, start_char=0, end_char=1)
        assert meta.acl == ["all"]

    def test_the_access_list_is_a_top_level_payload_field(self) -> None:
        # QdrantDenseIndex writes {**metadata.model_dump()}, so `acl` is what
        # the dense filter's key="acl" matches.
        assert "acl" in _chunk("d", "x", ["all"]).metadata.model_dump()


class TestCallerTokens:
    def test_a_member_holds_all_itself_and_its_groups(self) -> None:
        p = Principal(kind="user", subject_id="usr_1", org_id="org_a",
                      roles={"ws": Role.READER}, groups=("grp_hr", "grp_eng"))
        assert p.access == {"all", "user:usr_1", "group:grp_hr", "group:grp_eng"}

    def test_an_organisation_admin_gets_no_bypass(self) -> None:
        # D9 (a): admin manages, but reads only what its own tokens allow.
        p = Principal(kind="user", subject_id="usr_2", org_id="org_a", org_admin=True)
        assert p.access == {"all", "user:usr_2"}

    def test_a_service_account_holds_its_own_token(self) -> None:
        p = Principal(kind="service", subject_id="7", org_id="org_a")
        assert p.access == {"all", "user:7"}

    def test_visitors_and_legacy_keys_hold_all_only(self) -> None:
        visitor = Principal(kind="visitor", subject_id="demo:1.2.3.4", org_id="org_public")
        assert visitor.access == {"all"}
        assert legacy_key_principal(3).access == {"all"}
        assert ANONYMOUS.access == {"all"}


def test_outside_a_request_access_is_unset() -> None:
    async def read() -> frozenset[str] | None:
        return reader_access()

    assert asyncio.run(read()) is None
