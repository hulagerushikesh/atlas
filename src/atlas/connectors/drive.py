"""
Google Drive connector (E3.1, docs/e3-drive-connector.md).

Three parts, kept apart so each is testable without Google:

* `DriveSource` — what the sync needs from Drive: walk a folder, read one
  file's sharing, download its text. `GoogleDrive` is the real one (Drive v3
  REST over httpx, with the connecting person's refresh token); tests use a
  fake.
* `acl_for` — Drive sharing as Atlas access tokens (§4). Fails closed:
  sharing Atlas cannot read, or only through an unlinked Google Group, gives
  an empty list, which nobody can read.
* `sync_folder` — one pass over a connected folder: index new and changed
  files, rewrite access lists that changed (₹0, no re-embedding), remove
  files that left the folder. Returns counts for the console.
* `touches` — whether anything in Drive's change feed concerns the folder
  (E3.2), so the 5-minute check skips the walk when nothing did.

A synced file's document id is `document_id("drive:{file id}")`, so a
rename or a move inside the folder is the same document, and its source is
the file's path in the folder, which is what a citation shows.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
import structlog

from atlas.api.tenancy import ACCESS_ALL, ACCESS_DOMAIN, ACCESS_EMAIL
from atlas.ingestion.loaders.registry import get_loader
from atlas.interfaces.document import document_id

logger = structlog.get_logger(__name__)

SCOPE = "https://www.googleapis.com/auth/drive.readonly"
FOLDER = "application/vnd.google-apps.folder"
GOOGLE_DOC = "application/vnd.google-apps.document"

# Drive mime type -> the extension whose loader reads it. Docs are exported
# as Markdown so headings survive into the context headers.
SUPPORTED: dict[str, str] = {
    GOOGLE_DOC: ".md",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/x-markdown": ".md",
}


@dataclass(frozen=True)
class DrivePermission:
    type: str            # user | group | domain | anyone
    email: str = ""
    domain: str = ""
    role: str = "reader"


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    path: str            # inside the connected folder, e.g. "Policies/Leave.md"
    version: str = ""    # changes whenever the content does
    size: int = 0


@dataclass(frozen=True)
class DriveChange:
    file_id: str
    removed: bool = False                 # deleted, or no longer visible to the connector
    parents: tuple[str, ...] = ()


class DriveSource(Protocol):
    async def walk(self, folder_id: str) -> list[DriveFile]: ...
    async def permissions(self, file_id: str) -> list[DrivePermission] | None: ...
    async def download(self, file: DriveFile) -> bytes: ...
    async def start_cursor(self) -> str: ...
    async def changes(self, cursor: str) -> tuple[list[DriveChange], str]: ...


def drive_doc_id(file_id: str) -> str:
    return document_id(f"drive:{file_id}")


def acl_for(perms: list[DrivePermission] | None,
            group_links: dict[str, str]) -> list[str]:
    """Drive sharing as Atlas tokens (docs/e3-drive-connector.md §4)."""
    if perms is None:
        return []
    tokens: set[str] = set()
    for p in perms:
        if p.type == "anyone":
            tokens.add(ACCESS_ALL)
        elif p.type == "user" and p.email:
            tokens.add(f"{ACCESS_EMAIL}{p.email.lower()}")
        elif p.type == "domain" and p.domain:
            tokens.add(f"{ACCESS_DOMAIN}{p.domain.lower()}")
        elif p.type == "group" and p.email.lower() in group_links:
            tokens.add(f"group:{group_links[p.email.lower()]}")
    return sorted(tokens)


def touches(changes: Iterable[DriveChange], held: Iterable[str],
            folders: Iterable[str]) -> bool:
    """Whether a change concerns the folder: a held file changed, moved or went
    away, or something was added under one of the folder's folders."""
    watched = set(held) | set(folders)
    return any(c.file_id in watched or watched.intersection(c.parents) for c in changes)


# ── The real Drive ────────────────────────────────────────────────────────────

_API = "https://www.googleapis.com/drive/v3"
_TOKEN_URL = "https://oauth2.googleapis.com/token"


class DriveAuthError(RuntimeError):
    """The stored grant no longer works: revoked, or expired (7 days in Testing)."""


class GoogleDrive:
    """Drive v3 as the connecting person, from their refresh token."""

    def __init__(self, refresh_token: str, client_id: str, client_secret: str,
                 http: httpx.AsyncClient | None = None) -> None:
        self._refresh = refresh_token
        self._client_id, self._client_secret = client_id, client_secret
        self._http = http or httpx.AsyncClient(timeout=60.0)
        self._token = ""

    async def _access_token(self) -> str:
        if not self._token:
            r = await self._http.post(_TOKEN_URL, data={
                "grant_type": "refresh_token", "refresh_token": self._refresh,
                "client_id": self._client_id, "client_secret": self._client_secret})
            if r.status_code in (400, 401):
                raise DriveAuthError("Google refused the stored Drive grant; reconnect Drive")
            r.raise_for_status()
            self._token = str(r.json()["access_token"])
        return self._token

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {await self._access_token()}"}
            r = await self._http.get(url, params=params, headers=headers)
            if r.status_code == 401 and attempt == 1:
                self._token = ""     # expired access token: refresh once
                continue
            return r
        return r

    async def walk(self, folder_id: str) -> list[DriveFile]:
        out: list[DriveFile] = []
        pending: list[tuple[str, str]] = [(folder_id, "")]
        seen: set[str] = set()
        while pending:
            parent, prefix = pending.pop()
            if parent in seen:          # a folder reachable twice (shortcuts)
                continue
            seen.add(parent)
            page = None
            while True:
                params: dict[str, Any] = {
                    "q": f"'{parent}' in parents and trashed = false",
                    "fields": "nextPageToken, files(id, name, mimeType, version, size)",
                    "pageSize": 1000, "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                }
                if page:
                    params["pageToken"] = page
                r = await self._get(f"{_API}/files", params)
                r.raise_for_status()
                body = r.json()
                for f in body.get("files", []):
                    path = f"{prefix}{f['name']}"
                    if f["mimeType"] == FOLDER:
                        pending.append((f["id"], f"{path}/"))
                        out.append(DriveFile(id=f["id"], name=f["name"], mime_type=FOLDER,
                                             path=f"{path}/"))
                    else:
                        out.append(DriveFile(id=f["id"], name=f["name"],
                                             mime_type=f["mimeType"], path=path,
                                             version=str(f.get("version", "")),
                                             size=int(f.get("size", 0) or 0)))
                page = body.get("nextPageToken")
                if not page:
                    break
        return out

    async def permissions(self, file_id: str) -> list[DrivePermission] | None:
        perms: list[DrivePermission] = []
        page = None
        while True:
            params: dict[str, Any] = {
                "fields": "nextPageToken, permissions(type, emailAddress, domain, role)",
                "supportsAllDrives": "true", "pageSize": 100}
            if page:
                params["pageToken"] = page
            r = await self._get(f"{_API}/files/{file_id}/permissions", params)
            if r.status_code in (403, 404):
                # A file the person may view but not share: its sharing is
                # hidden from them, so Atlas cannot know who may read it.
                return None
            r.raise_for_status()
            body = r.json()
            perms.extend(DrivePermission(type=p.get("type", ""),
                                         email=p.get("emailAddress", ""),
                                         domain=p.get("domain", ""),
                                         role=p.get("role", ""))
                         for p in body.get("permissions", []))
            page = body.get("nextPageToken")
            if not page:
                return perms

    async def download(self, file: DriveFile) -> bytes:
        if file.mime_type == GOOGLE_DOC:
            r = await self._get(f"{_API}/files/{file.id}/export",
                                {"mimeType": "text/markdown"})
        else:
            r = await self._get(f"{_API}/files/{file.id}",
                                {"alt": "media", "supportsAllDrives": "true"})
        r.raise_for_status()
        return r.content

    async def start_cursor(self) -> str:
        r = await self._get(f"{_API}/changes/startPageToken", {"supportsAllDrives": "true"})
        r.raise_for_status()
        return str(r.json()["startPageToken"])

    async def changes(self, cursor: str) -> tuple[list[DriveChange], str]:
        """Everything that changed for the connector since *cursor*, and the
        cursor to ask from next time. Sharing changes are listed too."""
        out: list[DriveChange] = []
        page = cursor
        while True:
            r = await self._get(f"{_API}/changes", {
                "pageToken": page, "pageSize": 1000, "includeRemoved": "true",
                "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                "fields": "nextPageToken, newStartPageToken, "
                          "changes(fileId, removed, file(parents, trashed))"})
            r.raise_for_status()
            body = r.json()
            for c in body.get("changes", []):
                file = c.get("file") or {}
                out.append(DriveChange(
                    file_id=str(c.get("fileId", "")),
                    removed=bool(c.get("removed")) or bool(file.get("trashed")),
                    parents=tuple(file.get("parents") or ())))
            if body.get("newStartPageToken"):
                return out, str(body["newStartPageToken"])
            page = body.get("nextPageToken")
            if not page:
                return out, cursor

    async def aclose(self) -> None:
        await self._http.aclose()


# ── One pass over a folder ────────────────────────────────────────────────────

@dataclass
class SyncReport:
    indexed: int = 0          # new or changed files read and indexed
    unchanged: int = 0
    access_changed: int = 0   # access list rewritten, no re-embedding
    removed: int = 0          # left the folder (or Drive)
    skipped: list[str] = field(default_factory=list)      # unsupported or too big
    closed: list[str] = field(default_factory=list)       # sharing unreadable → nobody
    failed: list[str] = field(default_factory=list)
    folders: list[str] = field(default_factory=list)      # watched by the change feed

    def as_dict(self) -> dict[str, Any]:
        return {"indexed": self.indexed, "unchanged": self.unchanged,
                "access_changed": self.access_changed, "removed": self.removed,
                "skipped": self.skipped[:50], "closed": self.closed[:50],
                "failed": self.failed[:50]}


class Indexer(Protocol):
    async def index_documents(self, documents: list[Any]) -> Any: ...
    async def document_acl(self, doc_id: str) -> list[str] | None: ...
    async def set_document_acl(self, doc_id: str, acl: list[str]) -> int: ...
    async def delete_document(self, doc_id: str) -> int: ...


async def _read(file: DriveFile, raw: bytes) -> Any:
    """The file's bytes as an Atlas document, through the existing loaders."""
    ext = SUPPORTED[file.mime_type]
    with tempfile.TemporaryDirectory(prefix="atlas-drive-") as tmp:
        path = Path(tmp) / f"file{ext}"
        path.write_bytes(raw)
        docs = await get_loader(path).load(path)
    if not docs:
        return None
    doc = docs[0]
    doc.source = file.path
    doc.id = drive_doc_id(file.id)
    return doc


async def sync_folder(source: DriveSource, indexer: Indexer, folder_id: str,
                      held: dict[str, str], group_links: dict[str, str], *,
                      max_files: int = 500, max_file_bytes: int = 10 * 1024 * 1024,
                      ) -> tuple[SyncReport, dict[str, str]]:
    """Bring the sheet in line with the folder.

    *held* maps each Drive file id already synced to the version indexed; the
    returned map replaces it. Access lists are re-read every pass, because a
    sharing change does not change a file's version.
    """
    report = SyncReport()
    walked = await source.walk(folder_id)
    report.folders = [folder_id] + [f.id for f in walked if f.mime_type == FOLDER]
    files = [f for f in walked if f.mime_type != FOLDER]
    now: dict[str, str] = {}
    supported = [f for f in files if f.mime_type in SUPPORTED]
    report.skipped.extend(f.path for f in files if f.mime_type not in SUPPORTED)
    for f in supported[max_files:]:
        report.skipped.append(f.path)
    for f in supported[:max_files]:
        if f.size > max_file_bytes:
            report.skipped.append(f.path)
            continue
        try:
            perms = await source.permissions(f.id)
            acl = acl_for(perms, group_links)
            if not acl:
                # Nobody in Atlas may read it, so its text is not fetched,
                # embedded or kept; if it was held, the loop below removes it.
                report.closed.append(f.path)
                continue
            doc_id = drive_doc_id(f.id)
            if held.get(f.id) != f.version or not f.version:
                doc = await _read(f, await source.download(f))
                if doc is None:
                    report.failed.append(f.path)
                    continue
                doc.acl = acl
                await indexer.index_documents([doc])
                report.indexed += 1
            else:
                report.unchanged += 1
            # Unchanged passages are not rewritten by an index, so the list is
            # set here whenever it differs, new file or old.
            if (await indexer.document_acl(doc_id) or []) != acl:
                await indexer.set_document_acl(doc_id, acl)
                if held.get(f.id) == f.version:
                    report.access_changed += 1
            now[f.id] = f.version
        except Exception as exc:  # noqa: BLE001 -- one bad file must not stop the folder
            logger.warning("drive_file_failed", file_id=f.id, error=str(exc))
            report.failed.append(f.path)
            if f.id in held:
                now[f.id] = held[f.id]   # keep what is indexed; retry next pass
    for gone in _gone(held, now):
        await indexer.delete_document(drive_doc_id(gone))
        report.removed += 1
    logger.info("drive_synced", **{k: v if isinstance(v, int) else len(v)
                                   for k, v in report.as_dict().items()})
    return report, now


def _gone(held: Iterable[str], now: dict[str, str]) -> list[str]:
    return [f for f in held if f not in now]
