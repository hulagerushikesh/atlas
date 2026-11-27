"""
E3.1 pieces on their own: Drive sharing → tokens, the signed cookie that
carries a verified email, sealed tokens and consent state, one sync pass's
bookkeeping, and the real Drive client against a recorded HTTP exchange.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet

from atlas.api import sessions
from atlas.api.tenancy import Principal
from atlas.connectors import connections
from atlas.connectors.drive import (
    GOOGLE_DOC,
    DriveAuthError,
    DriveFile,
    DrivePermission,
    GoogleDrive,
    acl_for,
    sync_folder,
)


class TestSharingToTokens:
    def test_each_kind_of_share(self) -> None:
        perms = [DrivePermission(type="user", email="Alice@Acme.com"),
                 DrivePermission(type="domain", domain="Acme.com"),
                 DrivePermission(type="anyone")]
        assert acl_for(perms, {}) == ["all", "domain:acme.com", "email:alice@acme.com"]

    def test_a_google_group_counts_only_once_linked(self) -> None:
        perms = [DrivePermission(type="group", email="hr@acme.com")]
        assert acl_for(perms, {}) == []
        assert acl_for(perms, {"hr@acme.com": "grp_1"}) == ["group:grp_1"]

    def test_unreadable_sharing_is_nobody(self) -> None:
        assert acl_for(None, {}) == []


class TestWhoHoldsWhat:
    def test_a_signed_in_person_holds_their_email_and_domain(self) -> None:
        p = Principal(kind="user", subject_id="u", org_id="o", email="A@Acme.com",
                      hosted_domain="acme.com")
        assert p.access == {"all", "user:u", "email:a@acme.com", "domain:acme.com"}

    def test_keys_and_visitors_hold_neither(self) -> None:
        for kind in ("service", "visitor"):
            p = Principal(kind=kind, subject_id="k", email="x@y.z", hosted_domain="y.z")
            assert not any(t.startswith(("email:", "domain:")) for t in p.access)


class TestSessionCookie:
    SECRET = "s3cret"

    def test_it_carries_the_verified_email_and_domain(self) -> None:
        v = sessions.sign_session("usr_1", self.SECRET, email="A@acme.com",
                                  hosted_domain="Acme.com")
        s = sessions.read_session_identity(v, self.SECRET)
        assert s == sessions.Session("usr_1", "a@acme.com", "acme.com")

    def test_the_email_cannot_be_swapped(self) -> None:
        v = sessions.sign_session("usr_1", self.SECRET, email="a@acme.com")
        parts = v.split(".")
        parts[2] = sessions._b64("ceo@acme.com")
        assert sessions.read_session_identity(".".join(parts), self.SECRET) is None

    def test_an_old_cookie_still_signs_in_without_an_email(self) -> None:
        payload = "v1.usr_1.9999999999"
        old = f"{payload}.{sessions._mac(self.SECRET, payload)}"
        assert sessions.read_session_identity(old, self.SECRET) == sessions.Session("usr_1")


class TestSealedTokenAndState:
    def test_a_token_round_trips_only_under_its_key(self) -> None:
        key, other = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        sealed = connections.seal("refresh-123", key)
        assert "refresh-123" not in sealed
        assert connections.unseal(sealed, key) == "refresh-123"
        assert connections.unseal(sealed, other) is None

    def test_state_names_sheet_and_person_and_expires(self) -> None:
        st = connections.sign_state("ws_1", "usr_1", "k", now=0)
        assert connections.read_state(st, "k", now=599) == ("ws_1", "usr_1")
        assert connections.read_state(st, "k", now=600) is None
        assert connections.read_state(st.replace("usr_1", "usr_2"), "k", now=1) is None

    def test_the_public_view_never_has_the_token(self) -> None:
        view = connections.public_view({"token": "sealed", "folder_id": "f", "files": {"a": "1"}})
        assert "token" not in view and view["connected"] is True and view["files"] == 1


# ── One pass's bookkeeping, with a fake Drive and a fake indexer ─────────────

class FakeIndexer:
    def __init__(self) -> None:
        self.acl: dict[str, list[str]] = {}
        self.indexed: list[str] = []

    async def index_documents(self, documents: list[Any]) -> Any:
        for d in documents:
            self.indexed.append(d.source)
            self.acl[d.id] = list(d.acl)

    async def document_acl(self, doc_id: str) -> list[str] | None:
        return self.acl.get(doc_id)

    async def set_document_acl(self, doc_id: str, acl: list[str]) -> int:
        self.acl[doc_id] = list(acl)
        return 1

    async def delete_document(self, doc_id: str) -> int:
        return 1 if self.acl.pop(doc_id, None) is not None else 0


class Folder:
    def __init__(self, files: list[DriveFile], broken: set[str] | None = None) -> None:
        self.files, self.broken = files, broken or set()

    async def walk(self, folder_id: str) -> list[DriveFile]:
        return self.files

    async def permissions(self, file_id: str) -> list[DrivePermission] | None:
        return [DrivePermission(type="anyone")]

    async def download(self, file: DriveFile) -> bytes:
        if file.id in self.broken:
            raise RuntimeError("network")
        return b"# Title\n\nsome text here"


def _f(fid: str, mime: str = GOOGLE_DOC, size: int = 10, version: str = "1") -> DriveFile:
    return DriveFile(id=fid, name=fid, mime_type=mime, path=f"dir/{fid}", version=version,
                     size=size)


class TestOnePass:
    def test_unsupported_and_oversized_files_are_listed_as_skipped(self) -> None:
        folder = Folder([_f("doc"), _f("sheet", "application/vnd.google-apps.spreadsheet"),
                         _f("big", "application/pdf", size=10**9)])
        report, held = asyncio.run(sync_folder(folder, FakeIndexer(), "r", {}, {}))
        assert report.indexed == 1 and set(report.skipped) == {"dir/sheet", "dir/big"}
        assert held == {"doc": "1"}

    def test_a_folder_bigger_than_the_cap_stops_at_the_cap(self) -> None:
        folder = Folder([_f(f"d{i}") for i in range(5)])
        report, held = asyncio.run(sync_folder(folder, FakeIndexer(), "r", {}, {}, max_files=3))
        assert report.indexed == 3 and len(report.skipped) == 2

    def test_a_file_that_fails_keeps_what_was_indexed(self) -> None:
        idx = FakeIndexer()
        _, held = asyncio.run(sync_folder(Folder([_f("a")]), idx, "r", {}, {}))
        folder = Folder([_f("a", version="2")], broken={"a"})
        report, held = asyncio.run(sync_folder(folder, idx, "r", held, {}))
        assert report.failed == ["dir/a"] and report.removed == 0 and held == {"a": "1"}

    def test_a_second_pass_with_nothing_changed_reads_nothing(self) -> None:
        idx = FakeIndexer()
        _, held = asyncio.run(sync_folder(Folder([_f("a")]), idx, "r", {}, {}))
        report, _ = asyncio.run(sync_folder(Folder([_f("a")]), idx, "r", held, {}))
        assert (report.indexed, report.unchanged, report.access_changed) == (0, 1, 0)
        assert idx.indexed == ["dir/a"]


# ── The real client, against recorded responses ─────────────────────────────

def _drive_http(routes: dict[str, Any], seen: list[str]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.url.path == "/token":
            body = routes.get("token", {"access_token": "at"})
            return httpx.Response(body.get("status", 200), json=body)
        key = request.url.path
        if key.endswith("/files") and "q" in request.url.params:
            key = f"list:{request.url.params['q'].split(chr(39))[1]}"
        status, body = routes.get(key, (404, {}))
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestGoogleDrive:
    def test_it_walks_subfolders_and_names_paths_from_the_root(self) -> None:
        routes = {
            "list:root": (200, {"files": [
                {"id": "sub", "name": "Policies", "mimeType": "application/vnd.google-apps.folder"},
                {"id": "a", "name": "Intro", "mimeType": GOOGLE_DOC, "version": "3"}]}),
            "list:sub": (200, {"files": [
                {"id": "b", "name": "Leave.pdf", "mimeType": "application/pdf", "size": "99"}]}),
        }
        drive = GoogleDrive("rt", "cid", "cs", http=_drive_http(routes, []))
        files = asyncio.run(drive.walk("root"))
        assert {(f.id, f.path, f.version) for f in files} == {
            ("a", "Intro", "3"), ("b", "Policies/Leave.pdf", ""), ("sub", "Policies/", "")}

    def test_sharing_hidden_from_the_connector_is_none(self) -> None:
        routes = {"/drive/v3/files/x/permissions": (403, {})}
        drive = GoogleDrive("rt", "cid", "cs", http=_drive_http(routes, []))
        assert asyncio.run(drive.permissions("x")) is None

    def test_a_google_doc_is_exported_as_markdown(self) -> None:
        routes = {"/drive/v3/files/d/export": (200, b"# Doc")}
        seen: list[str] = []
        drive = GoogleDrive("rt", "cid", "cs", http=_drive_http(routes, seen))
        f = DriveFile(id="d", name="Doc", mime_type=GOOGLE_DOC, path="Doc")
        assert asyncio.run(drive.download(f)) == b"# Doc"
        assert seen == ["POST /token", "GET /drive/v3/files/d/export"]

    def test_a_refused_grant_says_reconnect(self) -> None:
        drive = GoogleDrive("rt", "cid", "cs",
                            http=_drive_http({"token": {"status": 400, "error": "x"}}, []))
        with pytest.raises(DriveAuthError):
            asyncio.run(drive.permissions("x"))

    def test_the_token_is_never_in_what_it_logs(self, capsys: pytest.CaptureFixture[str]) -> None:
        routes = {"/drive/v3/files/x/permissions": (200, {"permissions": [
            {"type": "user", "emailAddress": "a@b.c", "role": "reader"}]})}
        drive = GoogleDrive("refresh-SECRET", "cid", "cs", http=_drive_http(routes, []))
        assert asyncio.run(drive.permissions("x")) == [
            DrivePermission(type="user", email="a@b.c", role="reader")]
        assert "refresh-SECRET" not in capsys.readouterr().out
        assert json.dumps(connections.public_view({"token": "refresh-SECRET"})).find(
            "refresh-SECRET") == -1
