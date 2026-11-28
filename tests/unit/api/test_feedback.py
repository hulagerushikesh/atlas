"""
E6.1 feedback on an answer, E6.2 what sheets could not answer.
"""

# ruff: noqa: F811 -- fixtures are imported, then used as arguments

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

from atlas.orchestration.generator import REFUSAL
from tests.unit.api.conftest import _make_pipeline_result
from tests.unit.api.test_audit import _entries, audited  # noqa: F401 -- fixture
from tests.unit.api.test_sign_in import (  # noqa: F401 -- pytest fixtures
    CONSOLE,
    Site,
    google_key,
    site,
)


def _pipeline(site: Site) -> Any:
    return site.app.state.atlas.registry.get.return_value.pipeline


def _refuse(site: Site, classification: str = "simple") -> None:
    result = _make_pipeline_result(answer=REFUSAL)
    result.classification = classification
    _pipeline(site).run = AsyncMock(return_value=result)


def _ask(client: Any, question: str, sheet: str = "docs", stream: bool = False) -> Any:
    return client.post("/query", headers=CONSOLE,
                       json={"query": question, "namespace": sheet, "stream": stream})


class TestFeedback:
    def test_a_thumbs_down_with_its_reason_is_recorded(self, audited: Site) -> None:
        reader = audited.sign_in("reader@gmail.com")
        r = reader.post("/feedback", headers=CONSOLE, json={
            "sheet": "docs", "question": "How much leave?", "rating": "down",
            "reason": "wrong_source", "comment": "That memo is from 2019",
            "sources": ["Old memo.md"]})
        assert r.status_code == 204, r.text
        [fb] = [e for e in _entries(audited) if e["action"] == "feedback"]
        assert fb["detail"]["rating"] == "down" and fb["detail"]["reason"] == "wrong_source"
        assert fb["detail"]["sources"] == ["Old memo.md"] and fb["sheet"] == "docs"
        assert fb["actor"]["email"] == "reader@gmail.com"

    def test_only_on_a_sheet_you_can_read(self, audited: Site) -> None:
        reader = audited.sign_in("reader@gmail.com")
        r = reader.post("/feedback", headers=CONSOLE,
                        json={"sheet": "hr", "question": "q", "rating": "up"})
        assert r.status_code == 404

    def test_a_made_up_reason_is_refused(self, audited: Site) -> None:
        reader = audited.sign_in("reader@gmail.com")
        r = reader.post("/feedback", headers=CONSOLE, json={
            "sheet": "docs", "question": "q", "rating": "down", "reason": "boring"})
        assert r.status_code == 422


class TestUnanswered:
    def test_a_question_the_sheet_could_not_answer_is_noted(self, audited: Site) -> None:
        _refuse(audited)
        admin = audited.sign_in("admin@acme.com")
        assert _ask(admin, "What is the parental leave policy?").status_code == 200
        [u] = [e for e in _entries(audited) if e["action"] == "unanswered"]
        assert u["detail"] == {"question": "What is the parental leave policy?",
                               "reason": "not_covered"}
        assert u["sheet"] == "docs" and u["actor"]["email"] == "admin@acme.com"

    def test_an_answered_question_is_not(self, audited: Site) -> None:
        admin = audited.sign_in("admin@acme.com")
        _ask(admin, "How much leave?")
        assert not [e for e in _entries(audited) if e["action"] == "unanswered"]

    def test_out_of_scope_says_so(self, audited: Site) -> None:
        _refuse(audited, "out_of_scope")
        _ask(audited.sign_in("admin@acme.com"), "Weather today?")
        [u] = [e for e in _entries(audited) if e["action"] == "unanswered"]
        assert u["detail"]["reason"] == "out_of_scope"

    def test_a_streamed_non_answer_is_noted_too(self, audited: Site) -> None:
        async def refuse(*_: Any, **__: Any) -> Any:
            yield REFUSAL

        _pipeline(audited)._generator.stream = refuse
        r = _ask(audited.sign_in("admin@acme.com"), "Dental cover?", stream=True)
        assert r.status_code == 200 and "done" in r.text
        [u] = [e for e in _entries(audited) if e["action"] == "unanswered"]
        assert u["detail"]["question"] == "Dental cover?"


class TestReport:
    def test_most_asked_first_with_people_and_reasons(self, audited: Site) -> None:
        _refuse(audited)
        admin = audited.sign_in("admin@acme.com")
        reader = audited.sign_in("reader@gmail.com")
        _ask(admin, "What is the parental leave policy?")
        _ask(reader, "what is the PARENTAL leave policy")
        reader.post("/feedback", headers=CONSOLE, json={
            "sheet": "docs", "question": "What is the parental leave policy?",
            "rating": "down", "reason": "no_answer", "comment": "We need this"})
        _ask(admin, "Dental cover?")
        _entries(audited)   # let the writes land
        r = admin.get("/org/unanswered")
        assert r.status_code == 200
        top, second = r.json()["questions"][:2]
        assert top["times"] == 3 and top["people"] == 2 and top["sheet"] == "docs"
        assert top["why"] == {"not_covered": 2, "no_answer": 1}
        assert top["comments"] == ["We need this"]
        assert second["question"] == "Dental cover?" and second["times"] == 1

    def test_admins_only(self, audited: Site) -> None:
        r = audited.sign_in("reader@gmail.com").get("/org/unanswered")
        assert r.status_code == 403
        asyncio.run(asyncio.sleep(0))
