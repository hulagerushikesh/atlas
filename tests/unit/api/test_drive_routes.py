"""
E3.1 and E3.2 routes: connecting Drive to a sheet, choosing a folder,
syncing, disconnecting, linking Google Groups, and the scheduler's 5-minute
pass. Google itself is replaced by a fake code exchange, a fake Drive and a
fake token check.
"""

# ruff: noqa: F811 -- the sign-in suite's fixtures are imported, then used as arguments

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from atlas.api import sessions, sheet_budget, tenancy
from atlas.api.routes import connectors as routes
from atlas.api.routes import namespaces
from atlas.config import DriveConfig
from atlas.connectors import connections
from atlas.connectors.drive import (
    GOOGLE_DOC,
    DriveChange,
    DriveFile,
    DrivePermission,
    drive_doc_id,
)
from tests.unit.api.test_sign_in import (  # noqa: F401 -- pytest fixtures
    CONSOLE,
    Site,
    google_key,
    site,
)

KEY = Fernet.generate_key().decode()


class FakeDrive:
    """One file, f1, in the folder; *world* is shared by every instance so a
    test can count walks and set what the change feed says."""

    def __init__(self, token: str, world: dict[str, Any]) -> None:
        self.token, self.world = token, world

    async def walk(self, folder_id: str) -> list[DriveFile]:
        self.world["walks"] += 1
        return [DriveFile(id="f1", name="Leave", mime_type=GOOGLE_DOC, path="Leave",
                          version="1")]

    async def start_cursor(self) -> str:
        return "c0"

    async def changes(self, cursor: str) -> tuple[list[DriveChange], str]:
        if self.world.get("broken_feed"):
            raise RuntimeError("cursor expired")
        self.world["asked"].append(cursor)
        return self.world["changes"], f"after-{cursor}"

    async def permissions(self, file_id: str) -> list[DrivePermission]:
        return [DrivePermission(type="user", email="admin@acme.com")]

    async def download(self, file: DriveFile) -> bytes:
        return b"# Leave\n\nTwenty days a year."


@pytest.fixture
def drive_site(site: Site, monkeypatch: pytest.MonkeyPatch) -> Site:
    state = site.app.state.atlas
    state.drive = DriveConfig(client_secret=SecretStr("cs"), token_key=SecretStr(KEY),
                              public_url="https://atlas.test",
                              scheduler_email="cron@atlas.iam.gserviceaccount.com")
    tokens: list[str] = []
    world: dict[str, Any] = {"walks": 0, "changes": [], "asked": []}
    site.app.state.drive_world = world

    def source(token: str) -> FakeDrive:
        tokens.append(token)
        return FakeDrive(token, world)

    site.app.state.drive_source = source
    site.app.state.drive_tokens = tokens
    indexer = state.registry.get.return_value.indexer
    indexer.index_documents = AsyncMock()
    indexer.document_acl = AsyncMock(return_value=None)

    async def exchange(code: str, *_: Any) -> str | None:
        return "refresh-from-google" if code == "good" else None

    monkeypatch.setattr(routes, "exchange_code", exchange)
    return site


def _connect(c: TestClient, sheet: str = "docs") -> str:
    r = c.get("/connectors/drive/connect", params={"namespace": sheet}, follow_redirects=False)
    assert r.status_code == 303, r.text
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["scope"] == ["https://www.googleapis.com/auth/drive.readonly"]
    assert q["access_type"] == ["offline"]
    assert q["redirect_uri"] == ["https://atlas.test/connectors/drive/callback"]
    return q["state"][0]


def _back(c: TestClient, state: str, code: str = "good") -> Any:
    return c.get("/connectors/drive/callback", params={"state": state, "code": code},
                 follow_redirects=False)


class TestConnecting:
    def test_an_editor_connects_and_the_token_is_stored_sealed(self, drive_site: Site) -> None:
        admin = drive_site.sign_in("admin@acme.com")
        r = _back(admin, _connect(admin))
        assert r.status_code == 303 and r.headers["location"].endswith("drive=connected")
        ws = drive_site.ws["a/docs"]
        record = asyncio.run(connections.get(ws))
        assert record is not None and "refresh-from-google" not in str(record)
        assert connections.unseal(record["token"], KEY) == "refresh-from-google"
        status = admin.get("/namespaces/docs/connectors/drive").json()
        assert status["connected"] is True and "token" not in status
        assert status["connected_by"] == "admin@acme.com"

    def test_someone_elses_consent_link_does_not_work(self, drive_site: Site) -> None:
        admin = drive_site.sign_in("admin@acme.com")
        state = _connect(admin)
        reader = drive_site.sign_in("reader@gmail.com")
        assert _back(reader, state).status_code == 400

    def test_a_reader_cannot_connect(self, drive_site: Site) -> None:
        reader = drive_site.sign_in("reader@gmail.com")
        r = reader.get("/connectors/drive/connect", params={"namespace": "docs"},
                       follow_redirects=False)
        assert r.status_code == 403

    def test_a_key_cannot_connect_its_own_drive(self, drive_site: Site) -> None:
        r = TestClient(drive_site.app).get("/connectors/drive/connect",
                                           params={"namespace": "docs"},
                                           headers={"Authorization": "Bearer nope"})
        assert r.status_code in (401, 403)

    def test_a_declined_consent_stores_nothing(self, drive_site: Site) -> None:
        admin = drive_site.sign_in("admin@acme.com")
        r = admin.get("/connectors/drive/callback",
                      params={"state": _connect(admin), "error": "access_denied"},
                      follow_redirects=False)
        assert r.headers["location"].endswith("drive=declined")
        assert asyncio.run(connections.get(drive_site.ws["a/docs"])) is None

    def test_off_until_configured(self, site: Site) -> None:
        admin = site.sign_in("admin@acme.com")
        r = admin.get("/connectors/drive/connect", params={"namespace": "docs"},
                      follow_redirects=False)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "drive_off"


class TestFolderAndSync:
    def connected(self, site: Site) -> TestClient:
        admin = site.sign_in("admin@acme.com")
        _back(admin, _connect(admin))
        return admin

    def test_choosing_a_folder_syncs_it_as_the_person_who_connected(
        self, drive_site: Site
    ) -> None:
        admin = self.connected(drive_site)
        r = admin.put("/namespaces/docs/connectors/drive", headers=CONSOLE,
                      json={"folder": "https://drive.google.com/drive/folders/1AbCdEfGhIjKl?x=1"})
        assert r.status_code == 200, r.text
        # Done inside the request: the reply is the finished pass.
        assert r.json()["syncing"] is False and r.json()["report"]["indexed"] == 1
        status = admin.get("/namespaces/docs/connectors/drive").json()
        assert status["folder_id"] == "1AbCdEfGhIjKl"
        assert status["files"] == 1 and status["report"]["indexed"] == 1, status
        assert drive_site.app.state.drive_tokens == ["refresh-from-google"]
        indexer = drive_site.app.state.atlas.registry.get.return_value.indexer
        doc = indexer.index_documents.await_args.args[0][0]
        assert doc.id == drive_doc_id("f1") and doc.acl == ["email:admin@acme.com"]
        # The source list marks it, so the console offers no per-document access.
        ws = asyncio.run(tenancy.get_tenancy().get_workspace(drive_site.ws["a/docs"]))
        assert ws is not None
        assert asyncio.run(namespaces._synced(ws)) == {drive_doc_id("f1")}

    def test_a_link_that_is_not_a_folder_is_refused(self, drive_site: Site) -> None:
        admin = self.connected(drive_site)
        r = admin.put("/namespaces/docs/connectors/drive", headers=CONSOLE,
                      json={"folder": "not a link"})
        assert r.status_code == 422

    def test_a_folder_needs_a_connection_first(self, drive_site: Site) -> None:
        admin = drive_site.sign_in("admin@acme.com")
        r = admin.put("/namespaces/docs/connectors/drive", headers=CONSOLE,
                      json={"folder": "1AbCdEfGhIjKl"})
        assert r.status_code == 409

    def test_disconnecting_removes_what_it_brought_in(self, drive_site: Site) -> None:
        admin = self.connected(drive_site)
        admin.put("/namespaces/docs/connectors/drive", headers=CONSOLE,
                  json={"folder": "1AbCdEfGhIjKl"})
        r = admin.delete("/namespaces/docs/connectors/drive", headers=CONSOLE)
        assert r.json() == {"connected": False, "removed": 1}
        indexer = drive_site.app.state.atlas.registry.get.return_value.indexer
        indexer.delete_document.assert_awaited_with(drive_doc_id("f1"))
        assert asyncio.run(connections.get(drive_site.ws["a/docs"])) is None

    def test_a_sheet_over_its_limit_brings_in_nothing_new(self, drive_site: Site) -> None:
        admin = self.connected(drive_site)
        admin.put("/org/spending/docs", headers=CONSOLE, json={"daily_inr": 1})
        ws = asyncio.run(tenancy.get_tenancy().get_workspace(drive_site.ws["a/docs"]))
        assert ws is not None
        meter = asyncio.run(sheet_budget.meter_for(ws, drive_site.app.state.atlas.spend))
        asyncio.run(meter.add(1.0))
        r = admin.put("/namespaces/docs/connectors/drive", headers=CONSOLE,
                      json={"folder": "1AbCdEfGhIjKl"})
        assert r.json()["report"]["over_limit"] == 1 and r.json()["files"] == 0
        indexer = drive_site.app.state.atlas.registry.get.return_value.indexer
        indexer.index_documents.assert_not_awaited()
        assert asyncio.run(connections.get(drive_site.ws["a/docs"]))["walk_after"] > 0

    def test_a_lost_key_is_reported_not_raised(self, drive_site: Site) -> None:
        admin = self.connected(drive_site)
        drive_site.app.state.atlas.drive = DriveConfig(
            client_secret=SecretStr("cs"), token_key=SecretStr(Fernet.generate_key().decode()),
            public_url="https://atlas.test")
        admin.put("/namespaces/docs/connectors/drive", headers=CONSOLE,
                  json={"folder": "1AbCdEfGhIjKl"})
        status = admin.get("/namespaces/docs/connectors/drive").json()
        assert "reconnect" in status["error"].lower() and status["files"] == 0


class TestGoogleGroups:
    def test_an_admin_links_a_google_group_to_an_atlas_group(self, drive_site: Site) -> None:
        admin = drive_site.sign_in("admin@acme.com")
        gid = admin.post("/org/groups", headers=CONSOLE, json={"name": "HR"}).json()["id"]
        r = admin.put("/connectors/google-groups", headers=CONSOLE,
                      json={"google_group": "HR-Team@acme.com", "group": "HR"})
        assert r.status_code == 200
        assert asyncio.run(connections.group_links("org_a")) == {"hr-team@acme.com": gid}
        listed = admin.get("/connectors/google-groups").json()["links"]
        assert listed == [{"google_group": "hr-team@acme.com", "group": "HR"}]

    def test_a_reader_cannot(self, drive_site: Site) -> None:
        reader = drive_site.sign_in("reader@gmail.com")
        r = reader.put("/connectors/google-groups", headers=CONSOLE,
                       json={"google_group": "x@acme.com", "group": "HR"})
        assert r.status_code == 403

    def test_links_stay_inside_their_organisation(self, drive_site: Site) -> None:
        asyncio.run(connections.link_group("org_b", "hr@bolt.io", "grp_b"))
        assert asyncio.run(connections.group_links("org_a")) == {}
        assert asyncio.run(tenancy.get_tenancy().list_records("google_group", "org_b"))


# ── E3.2: Cloud Scheduler's 5-minute pass ────────────────────────────────────

class FakeScheduler:
    """Google's token check: the token is the email it was signed for."""

    client_id = "https://atlas.test"

    async def verify(self, token: str) -> sessions.GoogleIdentity:
        if token == "forged":
            raise sessions.InvalidToken("bad signature")
        return sessions.GoogleIdentity(subject="1", email=token, name="", hosted_domain="")


CRON = {"Authorization": "Bearer cron@atlas.iam.gserviceaccount.com"}


class TestScheduledPass:
    @pytest.fixture
    def synced(self, drive_site: Site) -> Site:
        drive_site.app.state.drive_tick_verifier = FakeScheduler()
        admin = drive_site.sign_in("admin@acme.com")
        _back(admin, _connect(admin))
        admin.put("/namespaces/docs/connectors/drive", headers=CONSOLE,
                  json={"folder": "1AbCdEfGhIjKl"})
        assert drive_site.app.state.drive_world["walks"] == 1
        return drive_site

    def tick(self, site: Site, headers: dict[str, str] = CRON) -> Any:
        return TestClient(site.app).post("/connectors/drive/tick", headers=headers)

    def record(self, site: Site) -> dict[str, Any]:
        found = asyncio.run(connections.get(site.ws["a/docs"]))
        assert found is not None
        return found

    def test_only_the_scheduler_may_call_it(self, synced: Site) -> None:
        assert self.tick(synced, {}).status_code == 401
        assert self.tick(synced, {"Authorization": "Bearer forged"}).status_code == 401
        other = {"Authorization": "Bearer someone@acme.com"}
        assert self.tick(synced, other).status_code == 401
        assert synced.app.state.drive_world["walks"] == 1

    def test_off_until_a_scheduler_is_named(self, drive_site: Site) -> None:
        drive_site.app.state.atlas.drive = DriveConfig(public_url="https://atlas.test")
        assert self.tick(drive_site).status_code == 503

    def test_a_quiet_feed_walks_nothing(self, synced: Site) -> None:
        r = self.tick(synced)
        assert r.json() == {"sheets": 1, "failed": 0}
        world = synced.app.state.drive_world
        assert world["walks"] == 1 and world["asked"] == ["c0"]
        assert self.record(synced)["cursor"] == "after-c0"
        self.tick(synced)
        assert world["asked"] == ["c0", "after-c0"]       # the cursor moves on

    def test_a_change_to_a_held_file_walks_the_folder(self, synced: Site) -> None:
        synced.app.state.drive_world["changes"] = [DriveChange(file_id="f1", removed=True)]
        self.tick(synced)
        assert synced.app.state.drive_world["walks"] == 2

    def test_a_new_file_under_the_folder_walks_it(self, synced: Site) -> None:
        synced.app.state.drive_world["changes"] = [
            DriveChange(file_id="new", parents=("1AbCdEfGhIjKl",))]
        self.tick(synced)
        assert synced.app.state.drive_world["walks"] == 2

    def test_a_change_elsewhere_in_drive_walks_nothing(self, synced: Site) -> None:
        synced.app.state.drive_world["changes"] = [
            DriveChange(file_id="other", parents=("someone-elses-folder",))]
        self.tick(synced)
        assert synced.app.state.drive_world["walks"] == 1

    def test_an_unreadable_feed_walks_and_starts_a_fresh_cursor(self, synced: Site) -> None:
        synced.app.state.drive_world["broken_feed"] = True
        assert self.tick(synced).json() == {"sheets": 1, "failed": 0}
        assert synced.app.state.drive_world["walks"] == 2
        assert self.record(synced)["cursor"] == "c0"

    def test_a_full_check_is_due_daily_whatever_the_feed_says(self, synced: Site) -> None:
        record = self.record(synced)
        record["last_full"] -= 24 * 3600
        asyncio.run(connections.put(record))
        self.tick(synced)
        assert synced.app.state.drive_world["walks"] == 2
        assert synced.app.state.drive_world["asked"] == []   # feed not consulted

    def test_out_of_time_the_rest_waits_and_the_next_pass_walks(self, synced: Site) -> None:
        synced.app.state.atlas.drive = DriveConfig(
            client_secret=SecretStr("cs"), token_key=SecretStr(KEY),
            public_url="https://atlas.test",
            scheduler_email="cron@atlas.iam.gserviceaccount.com", tick_seconds=0)
        assert self.tick(synced).json() == {"sheets": 0, "failed": 0}
        world = synced.app.state.drive_world
        assert world["walks"] == 1 and world["asked"] == []

    def test_a_pass_cut_short_is_resumed_by_a_walk(self, synced: Site) -> None:
        record = self.record(synced)
        record["resume"] = True
        asyncio.run(connections.put(record))
        self.tick(synced)
        world = synced.app.state.drive_world
        assert world["walks"] == 2 and world["asked"] == []   # walked, feed skipped
        assert self.record(synced)["resume"] is False

    def test_text_held_back_by_the_limit_is_walked_after_the_reset(self, synced: Site) -> None:
        record = self.record(synced)
        record["walk_after"] = 1.0              # the reset has passed
        asyncio.run(connections.put(record))
        self.tick(synced)
        assert synced.app.state.drive_world["walks"] == 2
        assert "walk_after" not in self.record(synced)
        record = self.record(synced)
        record["walk_after"] = 4e9              # not yet
        asyncio.run(connections.put(record))
        self.tick(synced)
        assert synced.app.state.drive_world["walks"] == 2

    def test_a_sheet_without_a_folder_is_left_alone(self, drive_site: Site) -> None:
        drive_site.app.state.drive_tick_verifier = FakeScheduler()
        admin = drive_site.sign_in("admin@acme.com")
        _back(admin, _connect(admin))
        assert self.tick(drive_site).json() == {"sheets": 0, "failed": 0}
