"""
E2.5: evidence-based reuse (atlas.api.reuse).

A reworded question is served a stored answer only when the two searches
share passages, the questions are close in meaning, the asker may read every
passage the answer was built from, and the fit check agrees. The permission
half is also run in the worst case — every question "the same", every fit
check "yes" — in test_permission_cache.py, so access is the lock that holds.
"""

# ruff: noqa: F811 -- the sign-in suite's fixtures are imported, then used as arguments

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from atlas.api import tenancy
from atlas.api.reuse import EvidenceReuse, Probe
from atlas.config import ReuseConfig
from atlas.interfaces.llm import GenerationResponse
from tests.unit.api.test_permission_cache import _chunk, _Sheet
from tests.unit.api.test_sign_in import (  # noqa: F401 -- pytest fixtures
    CONSOLE,
    Site,
    google_key,
    site,
)


class StubEmbedder:
    """Questions in the same named family get the same vector."""

    def __init__(self, families: dict[str, list[float]] | None = None) -> None:
        self.families = families or {}

    async def embed_query(self, query: str) -> list[float]:
        for word, vector in self.families.items():
            if word in query.lower():
                return vector
        return [1.0, 0.0, 0.0]


class StubJudge:
    def __init__(self, fits: bool = True) -> None:
        self.fits = fits
        self.calls = 0

    async def generate(self, request: Any) -> GenerationResponse:
        self.calls += 1
        return GenerationResponse(content=json.dumps({"fits": self.fits, "reason": "stub"}),
                                  model_used="stub", prompt_tokens=10, completion_tokens=5,
                                  total_tokens=15)


def _reuse(judge: StubJudge | None = None, families: dict[str, list[float]] | None = None,
           **config: Any) -> EvidenceReuse:
    return EvidenceReuse(StubEmbedder(families), judge or StubJudge(),  # type: ignore[arg-type]
                         ReuseConfig(**config))


TOP5 = ["a", "b", "c", "d", "e"]
ALL = [["all"]] * 5


def _payload(answer: str = "stored answer") -> dict[str, Any]:
    return {"answer": answer, "is_faithful": True}


class TestFinding:
    def run(self, reuse: EvidenceReuse, top: list[str], question: str = "q2",
            access: frozenset[str] | None = frozenset({"all"}),
            version: str = "v1") -> dict[str, Any] | None:
        async def go() -> dict[str, Any] | None:
            probe = await reuse.probe(question, top)
            return await reuse.find("ws", version, question, probe, access)
        return asyncio.run(go())

    def stored(self, reuse: EvidenceReuse, acl: list[list[str]] = ALL) -> EvidenceReuse:
        reuse.remember("ws", "v1", "q1", Probe([1.0, 0.0, 0.0], TOP5), acl, _payload())
        return reuse

    def test_three_shared_passages_and_close_meaning_reuse(self) -> None:
        reuse = self.stored(_reuse())
        assert self.run(reuse, ["c", "a", "x", "b", "y"]) == _payload()

    def test_two_shared_passages_do_not(self) -> None:
        judge = StubJudge()
        reuse = self.stored(_reuse(judge))
        assert self.run(reuse, ["a", "b", "x", "y", "z"]) is None
        assert judge.calls == 0          # no fit check is paid for a non-candidate

    def test_distant_meaning_does_not(self) -> None:
        reuse = self.stored(_reuse(families={"vacation": [0.0, 1.0, 0.0]}))
        assert self.run(reuse, TOP5, question="vacation days?") is None

    def test_the_fit_check_has_the_last_word(self) -> None:
        reuse = self.stored(_reuse(StubJudge(fits=False)))
        assert self.run(reuse, TOP5) is None

    def test_a_fit_check_that_fails_is_a_miss(self) -> None:
        judge = StubJudge()
        judge.generate = AsyncMock(side_effect=RuntimeError("down"))  # type: ignore[method-assign]
        reuse = self.stored(_reuse(judge))
        assert self.run(reuse, TOP5) is None

    def test_one_passage_the_asker_cannot_read_withholds_it(self) -> None:
        reuse = self.stored(_reuse(), acl=[["all"], ["group:hr"]])
        assert self.run(reuse, TOP5, access=frozenset({"all"})) is None
        assert self.run(reuse, TOP5, access=frozenset({"all", "group:hr"})) == _payload()

    def test_another_sheet_version_finds_nothing(self) -> None:
        reuse = self.stored(_reuse())
        assert self.run(reuse, TOP5, version="v2") is None

    def test_a_new_version_drops_the_old_entries(self) -> None:
        reuse = self.stored(_reuse())
        reuse.remember("ws", "v2", "q3", Probe([1.0, 0.0, 0.0], TOP5), ALL, _payload("new"))
        assert len(reuse._entries) == 1

    def test_entries_are_bounded(self) -> None:
        reuse = _reuse(max_entries=2)
        for i in range(3):
            reuse.remember("ws", "v1", f"q{i}", Probe([1.0, 0.0, 0.0], TOP5), ALL, _payload())
        assert [k[2] for k in reuse._entries] == ["q1", "q2"]

    def test_an_answer_with_no_lists_is_never_stored(self) -> None:
        reuse = _reuse()
        reuse.remember("ws", "v1", "q1", Probe([1.0, 0.0, 0.0], TOP5), [], _payload())
        assert not reuse._entries


# ── Through the API ──────────────────────────────────────────────────────────

FIVE = ["p1", "p2", "p3", "p4", "p5"]


class _ReuseSheet(_Sheet):
    def __init__(self, site: Site, judge: StubJudge) -> None:
        super().__init__(site)
        site.app.state.atlas.reuse = _reuse(judge, families={"vacation": [0.0, 1.0, 0.0]})
        self.judge = judge

    def open_passages(self) -> None:
        self.answer_from = [_chunk(c, ["all"]) for c in FIVE]


@pytest.fixture
def judge() -> StubJudge:
    return StubJudge()


@pytest.fixture
def rsheet(site: Site, judge: StubJudge) -> _ReuseSheet:
    return _ReuseSheet(site, judge)


class TestThroughTheAPI:
    def test_a_reworded_question_is_served_the_stored_answer(self, rsheet: _ReuseSheet) -> None:
        a = rsheet.member("a@acme.com", [])
        rsheet.open_passages()
        assert rsheet.ask(a, "What are the salary bands?")["cached"] is False
        again = rsheet.ask(a, "salary bands, what are they")
        assert again["cached"] is True and again["query"] == "salary bands, what are they"
        assert rsheet.runs == 1
        # Kept under the new wording too: asking it again needs no fit check.
        calls = rsheet.judge.calls
        assert rsheet.ask(a, "salary bands, what are they")["cached"] is True
        assert rsheet.judge.calls == calls

    def test_people_with_different_access_share_what_both_may_read(
        self, rsheet: _ReuseSheet
    ) -> None:
        # The exact cache cannot do this: the HR member's key differs.
        hr = rsheet.member("hr@acme.com", ["HR"])
        other = rsheet.member("eng@acme.com", [])
        rsheet.open_passages()
        rsheet.ask(hr, "What are the salary bands?")
        assert rsheet.ask(other, "salary bands, what are they")["cached"] is True
        assert rsheet.runs == 1

    def test_not_when_the_answer_read_a_passage_the_asker_cannot(
        self, rsheet: _ReuseSheet
    ) -> None:
        hr = rsheet.member("hr@acme.com", ["HR"])
        other = rsheet.member("eng@acme.com", [])
        rsheet.answer_from = [_chunk(c, ["all"]) for c in FIVE[:4]] + [
            _chunk("p5", [f"group:{rsheet.hr}"])]
        rsheet.ask(hr, "What are the salary bands?")
        rsheet.open_passages()
        assert rsheet.ask(other, "salary bands, what are they")["cached"] is False
        assert rsheet.runs == 2

    def test_not_when_the_fit_check_says_no(self, rsheet: _ReuseSheet,
                                            judge: StubJudge) -> None:
        a = rsheet.member("a@acme.com", [])
        rsheet.open_passages()
        rsheet.ask(a, "What are the salary bands?")
        judge.fits = False
        assert rsheet.ask(a, "salary bands for directors only")["cached"] is False
        assert rsheet.runs == 2

    def test_not_for_a_different_question_on_the_same_passages(
        self, rsheet: _ReuseSheet, judge: StubJudge
    ) -> None:
        a = rsheet.member("a@acme.com", [])
        rsheet.open_passages()
        rsheet.ask(a, "What are the salary bands?")
        assert rsheet.ask(a, "How many vacation days?")["cached"] is False
        assert judge.calls == 0

    def test_not_after_the_sheet_changed(self, rsheet: _ReuseSheet) -> None:
        a = rsheet.member("a@acme.com", [])
        rsheet.open_passages()
        rsheet.ask(a, "What are the salary bands?")
        asyncio.run(tenancy.get_tenancy().bump_generation(rsheet.site.ws["a/docs"]))
        assert rsheet.ask(a, "salary bands, what are they")["cached"] is False

    def test_a_miss_does_not_search_twice(self, rsheet: _ReuseSheet) -> None:
        a = rsheet.member("a@acme.com", [])
        rsheet.open_passages()
        seen: list[Any] = []
        run = rsheet.pipeline.run

        async def spy(*args: Any, **kwargs: Any) -> Any:
            seen.append(kwargs.get("probe"))
            return await run(*args, **kwargs)

        rsheet.pipeline.run = spy
        rsheet.ask(a, "What are the salary bands?")
        assert seen and seen[0] is not None
        assert rsheet.pipeline._retrieve_all.await_count == 1

    def test_streamed_rewordings_reuse_too(self, rsheet: _ReuseSheet) -> None:
        a = rsheet.member("a@acme.com", [])
        rsheet.open_passages()
        body = {"query": "What are the salary bands?", "namespace": "docs", "stream": True}
        assert a.post("/query", headers=CONSOLE, json=body).headers["X-Cache"] == "miss"
        body["query"] = "salary bands, what are they"
        r = a.post("/query", headers=CONSOLE, json=body)
        assert r.headers["X-Cache"] == "reuse"
        assert '"cached": true' in r.text

    def test_off_by_default_nothing_extra_runs(self, site: Site) -> None:
        sheet = _Sheet(site)
        assert site.app.state.atlas.reuse is None
        a = sheet.member("a@acme.com", [])
        sheet.answer_from = [_chunk(c, ["all"]) for c in FIVE]
        sheet.ask(a)
        assert sheet.pipeline._retrieve_all.await_count == 0
