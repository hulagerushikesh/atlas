"""
E4.1 the audit record and E4.2 questions out of the general logs.
"""

# ruff: noqa: F811 -- the sign-in suite's fixtures are imported, then used as arguments

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from typing import Any

import pytest
from starlette.middleware import Middleware

from atlas.api import audit, tenancy
from atlas.logging import redact_questions
from tests.unit.api.test_sign_in import (  # noqa: F401 -- pytest fixtures
    CONSOLE,
    Site,
    google_key,
    site,
)


@pytest.fixture
def audited(site: Site, monkeypatch: pytest.MonkeyPatch) -> Iterator[Site]:
    # Innermost, as in create_app: inside the key middleware.
    site.app.user_middleware.append(Middleware(audit.AuditMiddleware))
    site.app.middleware_stack = None
    pending: list[Any] = []
    monkeypatch.setattr(audit, "spawn", lambda coro, name: pending.append(coro))
    site.app.state.audit_pending = pending
    audit._retention.clear()
    yield site
    for coro in pending:
        coro.close()


def _entries(site: Site, org: str = "org_a") -> list[dict[str, Any]]:
    pending = site.app.state.audit_pending
    while pending:
        asyncio.run(pending.pop(0))
    return asyncio.run(tenancy.get_tenancy().list_audit(org))


class TestWhatIsRecorded:
    def test_a_question_is_recorded_with_who_asked_it(self, audited: Site) -> None:
        admin = audited.sign_in("admin@acme.com")
        r = admin.post("/query", headers=CONSOLE, json={"query": "How much leave?",
                                                       "namespace": "docs"})
        assert r.status_code == 200, r.text
        q = next(e for e in _entries(audited) if e["action"] == "query")
        assert q["detail"]["question"] == "How much leave?" and q["sheet"] == "docs"
        assert q["actor"]["email"] == "admin@acme.com" and q["status"] == 200

    def test_a_refused_question_is_recorded_too(self, audited: Site) -> None:
        reader = audited.sign_in("reader@gmail.com")
        r = reader.post("/query", headers=CONSOLE, json={"query": "salaries", "namespace": "hr"})
        assert r.status_code == 404
        q = next(e for e in _entries(audited) if e["action"] == "query")
        assert q["status"] == 404 and q["detail"]["question"] == "salaries"

    def test_a_change_is_recorded_by_its_route(self, audited: Site) -> None:
        admin = audited.sign_in("admin@acme.com")
        admin.post("/org/groups", headers=CONSOLE, json={"name": "HR"})
        assert "POST /org/groups" in [e["action"] for e in _entries(audited)]

    def test_sign_in_is_recorded_and_reading_is_not(self, audited: Site) -> None:
        admin = audited.sign_in("admin@acme.com")
        admin.get("/namespaces")
        actions = [e["action"] for e in _entries(audited)]
        assert actions == ["sign_in"]

    def test_a_very_long_question_is_cut(self, audited: Site) -> None:
        admin = audited.sign_in("admin@acme.com")
        admin.post("/query", headers=CONSOLE, json={"query": "x" * 3000, "namespace": "docs"})
        q = next(e for e in _entries(audited) if e["action"] == "query")
        assert len(q["detail"]["question"]) == audit.QUESTION_CHARS


class TestWhoReadsIt:
    def test_only_an_admin_and_only_their_organisation(self, audited: Site) -> None:
        audited.sign_in("admin@bolt.io")
        admin = audited.sign_in("admin@acme.com")
        r = admin.get("/org/audit")
        assert r.status_code == 200
        assert {e["org_id"] for e in r.json()["entries"]} <= {"org_a"}
        assert audited.sign_in("reader@gmail.com").get("/org/audit").status_code == 403


class TestRetention:
    def test_entries_carry_the_setting_and_expire(self, audited: Site) -> None:
        admin = audited.sign_in("admin@acme.com")
        r = admin.put("/org/audit/settings", headers=CONSOLE, json={"retention_days": 7})
        assert r.status_code == 200
        admin.post("/org/groups", headers=CONSOLE, json={"name": "HR"})
        entries = _entries(audited)
        group = next(e for e in entries if e["action"] == "POST /org/groups")
        assert group["expires_at"] - group["ts"] == pytest.approx(7 * 86400)
        store = tenancy.get_tenancy()
        assert asyncio.run(store.prune_audit(time.time() + 8 * 86400)) == len(entries)
        assert asyncio.run(store.list_audit("org_a")) == []

    def test_retention_has_bounds(self, audited: Site) -> None:
        admin = audited.sign_in("admin@acme.com")
        r = admin.put("/org/audit/settings", headers=CONSOLE, json={"retention_days": 1})
        assert r.status_code == 422


class TestGeneralLogs:
    def test_question_text_is_withheld(self) -> None:
        event = {"event": "query_classified", "query": "How much is the CEO paid?",
                 "reasoning": "salary lookup", "sub_queries": ["a", "b"], "ms": 12}
        out = redact_questions(None, "info", event)
        assert out["query"] == "[withheld, 25 chars]"
        assert out["sub_queries"] == "[withheld, 2 items]"
        assert "CEO" not in str(out) and out["ms"] == 12
