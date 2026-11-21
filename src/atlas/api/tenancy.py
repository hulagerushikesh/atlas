"""
Tenancy: organisations, workspaces, users, roles, service accounts, and the
principal every request carries. Design: docs/e1-identity.md.

Design rationale:
    E1.1 stores the model and attaches a Principal to every request without
    changing what anyone can reach. Routes start asking `principal.can(...)`
    in E1.2; until then a key with no tenancy record resolves to a *legacy*
    principal that may do everything a key can do today.

    Grants are kept on the subject (user or service account) as a map of
    workspace id -> role, so building a principal is one read in either
    backend. Organisation admin is a flag on the same record.

    Workspace ids are opaque. Workspaces that existed before E1 keep their
    Qdrant collection, so the migration re-ingests nothing; new ones get
    `atlas_{org}__{workspace}` so two organisations may both have "docs".

    Same two backends as the key store: SQLite for tests and the laptop,
    Firestore live. The Firestore client is built lazily, as in keystore.py.
"""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

import aiosqlite
import structlog

logger = structlog.get_logger(__name__)


class Role(StrEnum):
    READER = "reader"   # ask
    EDITOR = "editor"   # ask, add and remove documents
    ADMIN = "admin"     # also members, service accounts, usage

    @property
    def rank(self) -> int:
        return _RANK[self]


_RANK = {Role.READER: 1, Role.EDITOR: 2, Role.ADMIN: 3}

Action = Literal["read", "write", "manage"]
_NEEDS: dict[str, Role] = {"read": Role.READER, "write": Role.EDITOR, "manage": Role.ADMIN}

SubjectKind = Literal["user", "service"]
PrincipalKind = Literal["user", "service", "visitor", "anonymous"]

PUBLIC_ORG_ID = "org_public"
PUBLIC_ORG_NAME = "Public"


@dataclass(frozen=True)
class Organisation:
    id: str
    name: str
    domain: str = ""        # Google Workspace domain; places signing-in users (E1.3)
    created_at: float | None = None


@dataclass(frozen=True)
class Workspace:
    id: str
    org_id: str
    name: str
    collection: str         # the Qdrant collection this workspace reads
    created_at: float | None = None


@dataclass(frozen=True)
class User:
    id: str
    org_id: str
    email: str
    name: str = ""
    created_at: float | None = None


@dataclass(frozen=True)
class Subject:
    """A user or service account as stored: who it is and what it holds."""

    kind: SubjectKind
    id: str
    org_id: str
    org_admin: bool = False
    roles: dict[str, Role] = field(default_factory=dict)  # workspace id -> role


@dataclass(frozen=True)
class Principal:
    """Who is asking. Built by the auth middleware; routes read only this."""

    kind: PrincipalKind
    subject_id: str = ""
    org_id: str = ""
    org_admin: bool = False
    roles: dict[str, Role] = field(default_factory=dict)
    # Pre-tenancy access: a key not yet migrated, or auth switched off. Keeps
    # today's behaviour while E1.1 is live; E1.2 decides what it may still do.
    legacy: bool = False

    def role_on(self, workspace_id: str) -> Role | None:
        if self.org_admin:
            return Role.ADMIN
        return self.roles.get(workspace_id)

    def can(self, workspace: Workspace, action: Action) -> bool:
        if self.legacy:
            return True
        if workspace.org_id != self.org_id:
            return False
        role = self.role_on(workspace.id)
        return role is not None and role.rank >= _NEEDS[action].rank


ANONYMOUS = Principal(kind="anonymous", legacy=True)


def principal_from_subject(subject: Subject) -> Principal:
    return Principal(
        kind=subject.kind, subject_id=subject.id, org_id=subject.org_id,
        org_admin=subject.org_admin, roles=dict(subject.roles),
    )


def legacy_key_principal(key_id: object) -> Principal:
    return Principal(kind="service", subject_id=str(key_id), legacy=True)


def visitor_principal(visitor_id: str, demo_workspace: Workspace | None) -> Principal:
    """A keyless visitor: reader on the demo workspace and nothing else."""
    if demo_workspace is None:
        return Principal(kind="visitor", subject_id=visitor_id)
    return Principal(
        kind="visitor", subject_id=visitor_id, org_id=demo_workspace.org_id,
        roles={demo_workspace.id: Role.READER},
    )


_SLUG = re.compile(r"[^a-z0-9_-]+")


def slug(name: str) -> str:
    s = _SLUG.sub("-", name.strip().lower()).strip("-")
    if not s:
        raise ValueError(f"name {name!r} has no usable characters")
    return s


def new_collection_name(org_id: str, workspace_name: str) -> str:
    return f"atlas_{slug(org_id)}__{slug(workspace_name)}"


def legacy_workspace_id(namespace: str) -> str:
    """Deterministic, so re-running the migration finds what it made before."""
    return f"ws_public_{namespace}"


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class WorkspaceNameTaken(ValueError):
    pass


class TenancyStore(Protocol):
    async def init(self) -> None: ...
    async def create_org(self, name: str, domain: str = "", *,
                         org_id: str | None = None) -> Organisation: ...
    async def get_org(self, org_id: str) -> Organisation | None: ...
    async def create_workspace(self, org_id: str, name: str, *, collection: str | None = None,
                               workspace_id: str | None = None) -> Workspace: ...
    async def get_workspace(self, workspace_id: str) -> Workspace | None: ...
    async def list_workspaces(self, org_id: str) -> list[Workspace]: ...
    async def create_user(self, org_id: str, email: str, name: str = "") -> User: ...
    async def find_user(self, email: str) -> User | None: ...
    async def put_subject(self, subject: Subject) -> None: ...
    async def get_subject(self, kind: SubjectKind, subject_id: str) -> Subject | None: ...


async def find_workspace(store: TenancyStore, org_id: str, name: str) -> Workspace | None:
    """By name, inside one organisation: another org's name is simply not found."""
    for ws in await store.list_workspaces(org_id):
        if ws.name == name:
            return ws
    return None


async def grant(store: TenancyStore, kind: SubjectKind, subject_id: str, org_id: str,
                workspace_id: str, role: Role) -> Subject:
    """Give a subject a role on one workspace of its own organisation."""
    ws = await store.get_workspace(workspace_id)
    if ws is None or ws.org_id != org_id:
        raise ValueError(f"workspace {workspace_id!r} is not in organisation {org_id!r}")
    current = await store.get_subject(kind, subject_id)
    if current is not None and current.org_id != org_id:
        raise ValueError(f"{kind} {subject_id!r} belongs to another organisation")
    roles = dict(current.roles) if current else {}
    roles[workspace_id] = role
    subject = Subject(kind=kind, id=subject_id, org_id=org_id,
                      org_admin=current.org_admin if current else False, roles=roles)
    await store.put_subject(subject)
    return subject


# ── SQLite ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, domain TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES orgs(id), name TEXT NOT NULL,
    collection TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE (org_id, name)
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES orgs(id),
    email TEXT NOT NULL UNIQUE, name TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS subjects (
    kind TEXT NOT NULL, id TEXT NOT NULL, org_id TEXT NOT NULL REFERENCES orgs(id),
    org_admin INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS grants (
    kind TEXT NOT NULL, subject_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id), role TEXT NOT NULL,
    PRIMARY KEY (kind, subject_id, workspace_id)
);
"""


class SQLiteTenancyStore:
    def __init__(self, db_path: Path = Path("data/atlas.db")) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    async def _one(self, sql: str, params: tuple[Any, ...]) -> aiosqlite.Row | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            row: aiosqlite.Row | None = await (await db.execute(sql, params)).fetchone()
            return row

    async def create_org(self, name: str, domain: str = "", *,
                         org_id: str | None = None) -> Organisation:
        if org_id is not None and (existing := await self.get_org(org_id)) is not None:
            return existing
        org = Organisation(id=org_id or _new_id("org"), name=name, domain=domain,
                           created_at=time.time())
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT INTO orgs VALUES (?, ?, ?, ?)",
                             (org.id, org.name, org.domain, org.created_at))
            await db.commit()
        return org

    async def get_org(self, org_id: str) -> Organisation | None:
        r = await self._one("SELECT * FROM orgs WHERE id = ?", (org_id,))
        return None if r is None else Organisation(r["id"], r["name"], r["domain"],
                                                   r["created_at"])

    async def create_workspace(self, org_id: str, name: str, *, collection: str | None = None,
                               workspace_id: str | None = None) -> Workspace:
        if workspace_id is not None and (got := await self.get_workspace(workspace_id)):
            return got
        if await find_workspace(self, org_id, name) is not None:
            raise WorkspaceNameTaken(f"organisation {org_id!r} already has {name!r}")
        ws = Workspace(id=workspace_id or _new_id("ws"), org_id=org_id, name=name,
                       collection=collection or new_collection_name(org_id, name),
                       created_at=time.time())
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT INTO workspaces VALUES (?, ?, ?, ?, ?)",
                             (ws.id, ws.org_id, ws.name, ws.collection, ws.created_at))
            await db.commit()
        return ws

    @staticmethod
    def _ws(r: aiosqlite.Row) -> Workspace:
        return Workspace(r["id"], r["org_id"], r["name"], r["collection"], r["created_at"])

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        r = await self._one("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
        return None if r is None else self._ws(r)

    async def list_workspaces(self, org_id: str) -> list[Workspace]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(
                "SELECT * FROM workspaces WHERE org_id = ? ORDER BY name", (org_id,)
            )).fetchall()
        return [self._ws(r) for r in rows]

    async def create_user(self, org_id: str, email: str, name: str = "") -> User:
        user = User(id=_new_id("usr"), org_id=org_id, email=email.strip().lower(),
                    name=name, created_at=time.time())
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                             (user.id, user.org_id, user.email, user.name, user.created_at))
            await db.commit()
        return user

    async def find_user(self, email: str) -> User | None:
        r = await self._one("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
        return None if r is None else User(r["id"], r["org_id"], r["email"], r["name"],
                                           r["created_at"])

    async def put_subject(self, subject: Subject) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO subjects VALUES (?, ?, ?, ?) ON CONFLICT (kind, id) "
                "DO UPDATE SET org_id = excluded.org_id, org_admin = excluded.org_admin",
                (subject.kind, subject.id, subject.org_id, int(subject.org_admin)),
            )
            await db.execute("DELETE FROM grants WHERE kind = ? AND subject_id = ?",
                             (subject.kind, subject.id))
            await db.executemany(
                "INSERT INTO grants VALUES (?, ?, ?, ?)",
                [(subject.kind, subject.id, ws, role.value) for ws, role in subject.roles.items()],
            )
            await db.commit()

    async def get_subject(self, kind: SubjectKind, subject_id: str) -> Subject | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM subjects WHERE kind = ? AND id = ?", (kind, subject_id)
            )).fetchone()
            if row is None:
                return None
            grants = await (await db.execute(
                "SELECT workspace_id, role FROM grants WHERE kind = ? AND subject_id = ?",
                (kind, subject_id),
            )).fetchall()
        return Subject(kind=kind, id=subject_id, org_id=row["org_id"],
                       org_admin=bool(row["org_admin"]),
                       roles={g["workspace_id"]: Role(g["role"]) for g in grants})


# ── Firestore ─────────────────────────────────────────────────────────────────

class FirestoreTenancyStore:
    """
    One collection per kind: atlas_orgs, atlas_workspaces, atlas_users,
    atlas_subjects (doc id "{kind}:{id}", roles as a map on the doc).
    """

    def __init__(self, project: str | None = None, client: Any = None,
                 prefix: str = "atlas_") -> None:
        self._project, self._client, self._prefix = project, client, prefix

    def _col(self, name: str) -> Any:
        if self._client is None:
            from google.cloud import firestore  # noqa: PLC0415 — optional dependency

            self._client = firestore.AsyncClient(project=self._project)
        return self._client.collection(f"{self._prefix}{name}")

    @staticmethod
    def _eq(field_name: str, value: Any) -> Any:
        from google.cloud.firestore_v1.base_query import FieldFilter  # noqa: PLC0415

        return FieldFilter(field_name, "==", value)

    async def init(self) -> None:
        await self._col("orgs").limit(1).get()

    async def create_org(self, name: str, domain: str = "", *,
                         org_id: str | None = None) -> Organisation:
        if org_id is not None and (existing := await self.get_org(org_id)) is not None:
            return existing
        org = Organisation(id=org_id or _new_id("org"), name=name, domain=domain,
                           created_at=time.time())
        await self._col("orgs").document(org.id).set(
            {"name": org.name, "domain": org.domain, "created_at": org.created_at})
        return org

    async def get_org(self, org_id: str) -> Organisation | None:
        snap = await self._col("orgs").document(org_id).get()
        if not snap.exists:
            return None
        d = snap.to_dict() or {}
        return Organisation(snap.id, d.get("name", ""), d.get("domain", ""), d.get("created_at"))

    async def create_workspace(self, org_id: str, name: str, *, collection: str | None = None,
                               workspace_id: str | None = None) -> Workspace:
        if workspace_id is not None and (got := await self.get_workspace(workspace_id)):
            return got
        # Not transactional: two admins creating the same name in the same
        # instant could both succeed. Acceptable until admin traffic exists.
        if await find_workspace(self, org_id, name) is not None:
            raise WorkspaceNameTaken(f"organisation {org_id!r} already has {name!r}")
        ws = Workspace(id=workspace_id or _new_id("ws"), org_id=org_id, name=name,
                       collection=collection or new_collection_name(org_id, name),
                       created_at=time.time())
        await self._col("workspaces").document(ws.id).set({
            "org_id": ws.org_id, "name": ws.name, "collection": ws.collection,
            "created_at": ws.created_at,
        })
        return ws

    @staticmethod
    def _ws(doc_id: str, d: dict[str, Any]) -> Workspace:
        return Workspace(doc_id, d.get("org_id", ""), d.get("name", ""),
                         d.get("collection", ""), d.get("created_at"))

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        snap = await self._col("workspaces").document(workspace_id).get()
        return self._ws(snap.id, snap.to_dict() or {}) if snap.exists else None

    async def list_workspaces(self, org_id: str) -> list[Workspace]:
        snaps = await self._col("workspaces").where(filter=self._eq("org_id", org_id)).get()
        return sorted((self._ws(s.id, s.to_dict() or {}) for s in snaps), key=lambda w: w.name)

    async def create_user(self, org_id: str, email: str, name: str = "") -> User:
        email = email.strip().lower()
        if await self.find_user(email) is not None:
            raise ValueError(f"a user with email {email!r} already exists")
        user = User(id=_new_id("usr"), org_id=org_id, email=email, name=name,
                    created_at=time.time())
        await self._col("users").document(user.id).set(
            {"org_id": org_id, "email": email, "name": name, "created_at": user.created_at})
        return user

    async def find_user(self, email: str) -> User | None:
        snaps = await self._col("users").where(
            filter=self._eq("email", email.strip().lower())).limit(1).get()
        for s in snaps:
            d = s.to_dict() or {}
            return User(s.id, d.get("org_id", ""), d.get("email", ""), d.get("name", ""),
                        d.get("created_at"))
        return None

    async def put_subject(self, subject: Subject) -> None:
        await self._col("subjects").document(f"{subject.kind}:{subject.id}").set({
            "kind": subject.kind, "id": subject.id, "org_id": subject.org_id,
            "org_admin": subject.org_admin,
            "roles": {ws: role.value for ws, role in subject.roles.items()},
        })

    async def get_subject(self, kind: SubjectKind, subject_id: str) -> Subject | None:
        snap = await self._col("subjects").document(f"{kind}:{subject_id}").get()
        if not snap.exists:
            return None
        d = snap.to_dict() or {}
        return Subject(kind=kind, id=subject_id, org_id=d.get("org_id", ""),
                       org_admin=bool(d.get("org_admin", False)),
                       roles={ws: Role(r) for ws, r in (d.get("roles") or {}).items()})


def build_tenancy_store(backend: str, *, sqlite_path: Path | None = None,
                        firestore_project: str | None = None) -> TenancyStore:
    if backend == "sqlite":
        return SQLiteTenancyStore(sqlite_path or Path("data/atlas.db"))
    if backend == "firestore":
        return FirestoreTenancyStore(project=firestore_project)
    raise ValueError(f"unknown AUTH_STORE {backend!r}; expected 'sqlite' or 'firestore'")


# ── Process-wide store and request-time resolution ────────────────────────────

_store: TenancyStore = SQLiteTenancyStore()


def configure_tenancy(backend: str = "sqlite", *, sqlite_path: Path | None = None,
                      firestore_project: str | None = None) -> TenancyStore:
    global _store
    _store = build_tenancy_store(backend, sqlite_path=sqlite_path,
                                 firestore_project=firestore_project)
    return _store


def get_tenancy() -> TenancyStore:
    return _store


async def principal_for_key(key_id: object) -> Principal:
    """The principal behind an API key. Unmigrated keys keep today's access."""
    try:
        subject = await _store.get_subject("service", str(key_id))
    except Exception as exc:  # noqa: BLE001 -- E1.1 must not change behaviour
        # E1.2 must fail closed here instead; today nothing is enforced yet.
        logger.warning("principal_lookup_failed", error=str(exc))
        subject = None
    return legacy_key_principal(key_id) if subject is None else principal_from_subject(subject)


async def principal_for_visitor(visitor_id: str, demo_namespace: str) -> Principal:
    try:
        ws = await _store.get_workspace(legacy_workspace_id(demo_namespace))
    except Exception as exc:  # noqa: BLE001
        logger.warning("principal_lookup_failed", error=str(exc))
        ws = None
    return visitor_principal(visitor_id, ws)


# ── Migration ─────────────────────────────────────────────────────────────────

@dataclass
class MigrationReport:
    org_created: bool = False
    workspaces_created: list[str] = field(default_factory=list)
    workspaces_kept: list[str] = field(default_factory=list)
    keys_granted: int = 0
    keys_already_done: int = 0
    keys_skipped_other_org: int = 0


async def migrate(store: TenancyStore, namespaces: list[str], key_ids: list[object], *,
                  apply: bool) -> MigrationReport:
    """
    Public organisation; every existing collection a workspace in it, keeping
    its collection; every key editor on all of them. Re-runnable: what exists
    is kept, and a key's existing grants are added to, never removed.
    """
    report = MigrationReport()
    if await store.get_org(PUBLIC_ORG_ID) is None:
        report.org_created = True
        if apply:
            await store.create_org(PUBLIC_ORG_NAME, org_id=PUBLIC_ORG_ID)

    ws_ids: list[str] = []
    for ns in sorted(set(namespaces)):
        ws_id = legacy_workspace_id(ns)
        ws_ids.append(ws_id)
        if await store.get_workspace(ws_id) is not None:
            report.workspaces_kept.append(ns)
            continue
        report.workspaces_created.append(ns)
        if apply:
            await store.create_workspace(PUBLIC_ORG_ID, ns, collection=f"atlas_{ns}",
                                         workspace_id=ws_id)

    for key_id in key_ids:
        current = await store.get_subject("service", str(key_id))
        if current is not None and current.org_id != PUBLIC_ORG_ID:
            report.keys_skipped_other_org += 1
            continue
        roles = dict(current.roles) if current else {}
        missing = [w for w in ws_ids if w not in roles]
        if not missing and current is not None:
            report.keys_already_done += 1
            continue
        report.keys_granted += 1
        if apply:
            for w in missing:
                roles[w] = Role.EDITOR
            await store.put_subject(Subject(
                kind="service", id=str(key_id), org_id=PUBLIC_ORG_ID,
                org_admin=current.org_admin if current else False, roles=roles,
            ))
    return report
