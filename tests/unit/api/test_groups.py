"""
E2.1 through the API: groups on the organisation page, and every request's
searches scoped to the caller's access tokens (docs/e2-permissions.md).
"""

# ruff: noqa: F811 -- the sign-in suite's fixtures are imported, then used as arguments

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from atlas.access import reader_access
from atlas.api import auth

# Fixtures shared with the sign-in suite: two organisations, invitations,
# Google tokens signed by a fake key.
from tests.unit.api.test_sign_in import (  # noqa: F401 -- pytest fixtures
    CONSOLE,
    Site,
    google_key,
    other_key,
    site,
)


def _uid(c: TestClient) -> str:
    return str(c.get("/auth/me").json()["user"]["id"])


def _make_group(admin: TestClient, name: str) -> str:
    r = admin.post("/org/groups", headers=CONSOLE, json={"name": name})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


class TestGroups:
    def test_an_admin_makes_a_group_and_puts_a_member_in_it(self, site: Site) -> None:
        admin = site.sign_in("admin@acme.com")
        reader = site.sign_in("reader@gmail.com")
        _make_group(admin, "HR team")
        r = admin.put(f"/org/members/{_uid(reader)}", headers=CONSOLE,
                      json={"roles": {"docs": "reader"}, "groups": ["HR team"]})
        assert r.status_code == 200 and r.json()["groups"] == ["HR team"]
        body = admin.get("/org").json()
        assert [g["name"] for g in body["groups"]] == ["HR team"]
        by_email = {m["email"]: m["groups"] for m in body["members"]}
        assert by_email == {"admin@acme.com": [], "reader@gmail.com": ["HR team"]}

    def test_an_update_that_does_not_mention_groups_keeps_them(self, site: Site) -> None:
        # The console before groups sends only roles; it must not wipe them.
        admin = site.sign_in("admin@acme.com")
        reader = site.sign_in("reader@gmail.com")
        _make_group(admin, "HR")
        uid = _uid(reader)
        admin.put(f"/org/members/{uid}", headers=CONSOLE,
                  json={"roles": {"docs": "reader"}, "groups": ["HR"]})
        r = admin.put(f"/org/members/{uid}", headers=CONSOLE,
                      json={"roles": {"docs": "editor"}})
        assert r.json()["groups"] == ["HR"]

    @pytest.mark.parametrize(("payload", "status", "code"), [
        ({"name": "HR"}, 409, "group_exists"),
        ({"name": "  "}, 422, "bad_group_name"),
        ({"name": "-leading"}, 422, "bad_group_name"),
    ])
    def test_bad_group_names(self, site: Site, payload: dict[str, Any], status: int,
                             code: str) -> None:
        admin = site.sign_in("admin@acme.com")
        _make_group(admin, "HR")
        r = admin.post("/org/groups", headers=CONSOLE, json=payload)
        assert r.status_code == status and r.json()["detail"]["code"] == code

    def test_an_unknown_group_is_refused(self, site: Site) -> None:
        admin = site.sign_in("admin@acme.com")
        reader = site.sign_in("reader@gmail.com")
        r = admin.put(f"/org/members/{_uid(reader)}", headers=CONSOLE,
                      json={"roles": {}, "groups": ["Finance"]})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_group"

    def test_another_organisations_group_cannot_be_used_or_deleted(self, site: Site) -> None:
        a = site.sign_in("admin@acme.com")
        b = site.sign_in("admin@bolt.io")
        bolt_hr = _make_group(b, "HR")
        reader = site.sign_in("reader@gmail.com")
        r = a.put(f"/org/members/{_uid(reader)}", headers=CONSOLE,
                  json={"roles": {}, "groups": ["HR"]})        # Bolt's name, not Acme's
        assert r.status_code == 422
        assert a.delete(f"/org/groups/{bolt_hr}", headers=CONSOLE).status_code == 404
        assert [g["name"] for g in b.get("/org").json()["groups"]] == ["HR"]

    def test_deleting_a_group_takes_it_off_its_members(self, site: Site) -> None:
        admin = site.sign_in("admin@acme.com")
        reader = site.sign_in("reader@gmail.com")
        gid = _make_group(admin, "HR")
        admin.put(f"/org/members/{_uid(reader)}", headers=CONSOLE,
                  json={"roles": {"docs": "reader"}, "groups": ["HR"]})
        assert admin.delete(f"/org/groups/{gid}", headers=CONSOLE).status_code == 204
        by_email = {m["email"]: m["groups"] for m in admin.get("/org").json()["members"]}
        assert by_email["reader@gmail.com"] == []

    def test_only_an_organisation_admin_manages_groups(self, site: Site) -> None:
        reader = site.sign_in("reader@gmail.com")
        assert reader.post("/org/groups", headers=CONSOLE,
                           json={"name": "HR"}).status_code == 403


class TestEverySearchIsScopedToTheCaller:
    """The middleware sets the access tokens; the pipeline's searches see them."""

    @pytest.fixture
    def seen(self, site: Site) -> list[frozenset[str] | None]:
        seen: list[frozenset[str] | None] = []
        pipeline = site.app.state.atlas.registry.get.return_value.pipeline
        run, retrieve_all = pipeline.run, pipeline._retrieve_all

        async def run_and_record(*args: Any, **kwargs: Any) -> Any:
            seen.append(reader_access())
            return await run(*args, **kwargs)

        async def retrieve_and_record(*args: Any, **kwargs: Any) -> Any:
            seen.append(reader_access())
            return await retrieve_all(*args, **kwargs)

        pipeline.run = run_and_record
        pipeline._retrieve_all = retrieve_and_record
        return seen

    def test_a_member_searches_with_its_own_and_its_groups_tokens(
        self, site: Site, seen: list[frozenset[str] | None]
    ) -> None:
        admin = site.sign_in("admin@acme.com")
        reader = site.sign_in("reader@gmail.com")
        gid = _make_group(admin, "HR")
        uid = _uid(reader)
        admin.put(f"/org/members/{uid}", headers=CONSOLE,
                  json={"roles": {"docs": "reader"}, "groups": ["HR"]})
        r = reader.post("/query", headers=CONSOLE, json={"query": "q", "namespace": "docs"})
        assert r.status_code == 200, r.text
        assert seen == [frozenset({"all", f"user:{uid}", f"group:{gid}",
                                    "email:reader@gmail.com"})]

    def test_a_streamed_question_is_scoped_too(
        self, site: Site, seen: list[frozenset[str] | None]
    ) -> None:
        reader = site.sign_in("reader@gmail.com")
        uid = _uid(reader)
        r = reader.post("/query", headers=CONSOLE,
                        json={"query": "q", "namespace": "docs", "stream": True})
        assert r.status_code == 200
        assert seen and set(seen) == {frozenset({"all", f"user:{uid}", "email:reader@gmail.com"})}

    def test_the_admin_has_no_bypass(
        self, site: Site, seen: list[frozenset[str] | None]
    ) -> None:
        admin = site.sign_in("admin@acme.com")
        _make_group(admin, "HR")       # managing a group is not being in it
        uid = _uid(admin)
        admin.post("/query", headers=CONSOLE, json={"query": "q", "namespace": "docs"})
        assert seen == [frozenset({"all", f"user:{uid}", "email:admin@acme.com"})]

    def test_a_service_account_searches_as_itself(
        self, site: Site, seen: list[frozenset[str] | None]
    ) -> None:
        admin = site.sign_in("admin@acme.com")
        r = admin.post("/org/service-accounts", headers=CONSOLE,
                       json={"name": "sync", "roles": {"docs": "reader"}})
        key, key_id = r.json()["key"], r.json()["key_id"]
        q = site.browser().post("/query", json={"query": "q", "namespace": "docs"},
                                headers={"Authorization": f"Bearer {key}"})
        assert q.status_code == 200, q.text
        assert seen == [frozenset({"all", f"user:{key_id}"})]

    def test_a_legacy_key_searches_as_everyone_on_the_sheet(
        self, site: Site, seen: list[frozenset[str] | None]
    ) -> None:
        raw, _ = asyncio.run(auth.create_key("unmigrated"))
        site.browser().post("/query", json={"query": "q", "namespace": "default"},
                            headers={"Authorization": f"Bearer {raw}"})
        assert seen == [frozenset({"all"})]
