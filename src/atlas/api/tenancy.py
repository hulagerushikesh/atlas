"""
Tenancy: organisations, workspaces, users, roles, service accounts, and the
principal every request carries. Design: docs/e1-identity.md.

Design rationale:
    E1.1 stores the model and attaches a Principal to every request. E1.2
    makes routes ask: every workspace route calls `authz.authorize`, which
    resolves the name inside the caller's organisation and checks the role.

    A key with no tenancy record (not migrated yet), and the dev box with
    auth off, resolve to a *legacy* principal. Legacy keeps today's access
    and no more: every workspace of the public organisation, including a
    pre-E1 collection that has no workspace record yet, and nothing in any
    other organisation. A failed tenancy read refuses the request
    (`TenancyUnavailable`); it never falls back to legacy.

    Grants are kept on the subject (user or service account) as a map of
    workspace id -> role, so building a principal is one read in either
    backend. Organisation admin is a flag on the same record.

    Workspace ids are opaque. Workspaces that existed before E1 keep their
    Qdrant collection, so the migration re-ingests nothing; new ones get
    `atlas_{org}__{workspace}` so two organisations may both have "docs".

    Same two backends as the key store: SQLite for tests and the laptop,
    Firestore live. The Firestore client is built lazily, as in keystore.py.

    E2 (docs/e2-permissions.md) adds groups. A subject's group ids are kept
    on the subject next to its roles, so the principal still costs one read,
    and `Principal.access` turns them into the tokens every passage's access
    list is matched against.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import dataclass, field, replace
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

# The access-list token every reader of a workspace holds (docs/e2-permissions.md §2).
ACCESS_ALL = "all"


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
class Invitation:
    """A person an admin has let in, before they first sign in (E1.3).

    One per address: it is consumed by that address's first sign-in, which
    makes the user in `org_id` with exactly these grants.
    """

    email: str
    org_id: str
    org_admin: bool = False
    roles: dict[str, Role] = field(default_factory=dict)  # workspace id -> role
    invited_by: str = ""
    created_at: float | None = None


@dataclass(frozen=True)
class Group:
    """A named set of members inside one organisation (E2)."""

    id: str
    org_id: str
    name: str
    created_at: float | None = None


@dataclass(frozen=True)
class Subject:
    """A user or service account as stored: who it is and what it holds."""

    kind: SubjectKind
    id: str
    org_id: str
    org_admin: bool = False
    roles: dict[str, Role] = field(default_factory=dict)  # workspace id -> role
    groups: tuple[str, ...] = ()                           # group ids, E2


@dataclass(frozen=True)
class Principal:
    """Who is asking. Built by the auth middleware; routes read only this."""

    kind: PrincipalKind
    subject_id: str = ""
    org_id: str = ""
    org_admin: bool = False
    roles: dict[str, Role] = field(default_factory=dict)
    # Pre-tenancy access: a key not yet migrated, or auth switched off. May
    # read and write the public organisation, as every key could before E1,
    # and nothing else.
    legacy: bool = False
    groups: tuple[str, ...] = ()

    @property
    def access(self) -> frozenset[str]:
        """The tokens a passage's access list must share for this caller to read it.

        Everyone with a role on a workspace holds `all`. A user or service
        account also holds `user:{id}` and `group:{id}` for each of its
        groups. Visitors and legacy keys hold `all` only. Organisation admins
        get nothing extra: no bypass (D9).
        """
        tokens = {ACCESS_ALL}
        if self.kind in ("user", "service") and self.subject_id and not self.legacy:
            tokens.add(f"user:{self.subject_id}")
            tokens.update(f"group:{g}" for g in self.groups)
        return frozenset(tokens)

    @property
    def home_org(self) -> str:
        """The organisation workspace names are looked up in; "" for none."""
        if self.org_id:
            return self.org_id
        return PUBLIC_ORG_ID if self.legacy else ""

    def role_on(self, workspace_id: str) -> Role | None:
        if self.org_admin:
            return Role.ADMIN
        return self.roles.get(workspace_id)

    def can(self, workspace: Workspace, action: Action) -> bool:
        if self.legacy:
            return workspace.org_id == PUBLIC_ORG_ID
        if not self.org_id or workspace.org_id != self.org_id:
            return False
        role = self.role_on(workspace.id)
        return role is not None and role.rank >= _NEEDS[action].rank


ANONYMOUS = Principal(kind="anonymous", legacy=True)


def principal_from_subject(subject: Subject) -> Principal:
    return Principal(
        kind=subject.kind, subject_id=subject.id, org_id=subject.org_id,
        org_admin=subject.org_admin, roles=dict(subject.roles), groups=subject.groups,
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


# Collections of new workspaces are `atlas_{org}__{ws}`, so a name holding
# "__" could address another organisation's collection. No pre-E1 namespace
# has one; legacy resolution refuses them.
_RESERVED = "__"


def legacy_workspace(namespace: str) -> Workspace | None:
    """A pre-E1 namespace as the public workspace the migration makes of it.

    Same id and collection the migration writes, so a request before and after
    the migration reads the same collection and the same cache entries.
    """
    if not namespace or _RESERVED in namespace:
        return None
    return Workspace(id=legacy_workspace_id(namespace), org_id=PUBLIC_ORG_ID,
                     name=namespace, collection=f"atlas_{namespace}")


def registry_namespace(workspace: Workspace) -> str:
    """The key the namespace registry builds this workspace's pipeline under."""
    return workspace.collection.removeprefix("atlas_")


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


class GroupNameTaken(ValueError):
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
    # E1.3: sign-in, invitations and the members page.
    async def find_org_by_domain(self, domain: str) -> Organisation | None: ...
    async def get_user(self, user_id: str) -> User | None: ...
    async def list_users(self, org_id: str) -> list[User]: ...
    async def delete_user(self, user_id: str) -> None: ...
    async def list_subjects(self, org_id: str, kind: SubjectKind) -> list[Subject]: ...
    async def delete_subject(self, kind: SubjectKind, subject_id: str) -> None: ...
    async def put_invitation(self, invitation: Invitation) -> None: ...
    async def get_invitation(self, email: str) -> Invitation | None: ...
    async def list_invitations(self, org_id: str) -> list[Invitation]: ...
    async def delete_invitation(self, email: str) -> None: ...
    # E2: groups. Membership lives on the subject (Subject.groups).
    async def create_group(self, org_id: str, name: str) -> Group: ...
    async def get_group(self, group_id: str) -> Group | None: ...
    async def list_groups(self, org_id: str) -> list[Group]: ...
    async def delete_group(self, group_id: str) -> None: ...


def normalise_email(email: str) -> str:
    return email.strip().lower()


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
                      org_admin=current.org_admin if current else False, roles=roles,
                      groups=current.groups if current else ())
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
CREATE TABLE IF NOT EXISTS invitations (
    email TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES orgs(id),
    org_admin INTEGER NOT NULL DEFAULT 0, roles TEXT NOT NULL DEFAULT '{}',
    invited_by TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS groups (
    id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES orgs(id), name TEXT NOT NULL,
    created_at REAL NOT NULL, UNIQUE (org_id, name)
);
CREATE TABLE IF NOT EXISTS subject_groups (
    kind TEXT NOT NULL, subject_id TEXT NOT NULL, group_id TEXT NOT NULL,
    PRIMARY KEY (kind, subject_id, group_id)
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
        org = Organisation(id=org_id or _new_id("org"), name=name, domain=domain.strip().lower(),
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
            await db.execute("DELETE FROM subject_groups WHERE kind = ? AND subject_id = ?",
                             (subject.kind, subject.id))
            await db.executemany(
                "INSERT INTO subject_groups VALUES (?, ?, ?)",
                [(subject.kind, subject.id, g) for g in sorted(set(subject.groups))],
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
            groups = await (await db.execute(
                "SELECT group_id FROM subject_groups WHERE kind = ? AND subject_id = ? "
                "ORDER BY group_id", (kind, subject_id),
            )).fetchall()
        return Subject(kind=kind, id=subject_id, org_id=row["org_id"],
                       org_admin=bool(row["org_admin"]),
                       roles={g["workspace_id"]: Role(g["role"]) for g in grants},
                       groups=tuple(g["group_id"] for g in groups))

    async def _all(self, sql: str, params: tuple[Any, ...]) -> list[aiosqlite.Row]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            return list(await (await db.execute(sql, params)).fetchall())

    async def _run(self, *statements: tuple[str, tuple[Any, ...]]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            for sql, params in statements:
                await db.execute(sql, params)
            await db.commit()

    async def find_org_by_domain(self, domain: str) -> Organisation | None:
        if not domain:
            return None
        r = await self._one("SELECT * FROM orgs WHERE domain = ?", (domain.lower(),))
        return None if r is None else Organisation(r["id"], r["name"], r["domain"],
                                                   r["created_at"])

    @staticmethod
    def _user(r: aiosqlite.Row) -> User:
        return User(r["id"], r["org_id"], r["email"], r["name"], r["created_at"])

    async def get_user(self, user_id: str) -> User | None:
        r = await self._one("SELECT * FROM users WHERE id = ?", (user_id,))
        return None if r is None else self._user(r)

    async def list_users(self, org_id: str) -> list[User]:
        rows = await self._all("SELECT * FROM users WHERE org_id = ? ORDER BY email", (org_id,))
        return [self._user(r) for r in rows]

    async def delete_user(self, user_id: str) -> None:
        await self._run(("DELETE FROM users WHERE id = ?", (user_id,)))
        await self.delete_subject("user", user_id)

    async def list_subjects(self, org_id: str, kind: SubjectKind) -> list[Subject]:
        rows = await self._all("SELECT id FROM subjects WHERE org_id = ? AND kind = ?",
                               (org_id, kind))
        found = [await self.get_subject(kind, r["id"]) for r in rows]
        return [s for s in found if s is not None]

    async def delete_subject(self, kind: SubjectKind, subject_id: str) -> None:
        await self._run(
            ("DELETE FROM grants WHERE kind = ? AND subject_id = ?", (kind, subject_id)),
            ("DELETE FROM subject_groups WHERE kind = ? AND subject_id = ?", (kind, subject_id)),
            ("DELETE FROM subjects WHERE kind = ? AND id = ?", (kind, subject_id)),
        )

    @staticmethod
    def _invitation(r: aiosqlite.Row) -> Invitation:
        roles = {ws: Role(role) for ws, role in json.loads(r["roles"] or "{}").items()}
        return Invitation(email=r["email"], org_id=r["org_id"], org_admin=bool(r["org_admin"]),
                          roles=roles, invited_by=r["invited_by"], created_at=r["created_at"])

    async def put_invitation(self, invitation: Invitation) -> None:
        roles = json.dumps({ws: role.value for ws, role in invitation.roles.items()})
        await self._run((
            "INSERT INTO invitations VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (email) DO UPDATE "
            "SET org_id = excluded.org_id, org_admin = excluded.org_admin, "
            "roles = excluded.roles, invited_by = excluded.invited_by, "
            "created_at = excluded.created_at",
            (normalise_email(invitation.email), invitation.org_id, int(invitation.org_admin),
             roles, invitation.invited_by, invitation.created_at or time.time()),
        ))

    async def get_invitation(self, email: str) -> Invitation | None:
        r = await self._one("SELECT * FROM invitations WHERE email = ?", (normalise_email(email),))
        return None if r is None else self._invitation(r)

    async def list_invitations(self, org_id: str) -> list[Invitation]:
        rows = await self._all("SELECT * FROM invitations WHERE org_id = ? ORDER BY email",
                               (org_id,))
        return [self._invitation(r) for r in rows]

    async def delete_invitation(self, email: str) -> None:
        await self._run(("DELETE FROM invitations WHERE email = ?", (normalise_email(email),)))

    async def create_group(self, org_id: str, name: str) -> Group:
        group = Group(id=_new_id("grp"), org_id=org_id, name=name, created_at=time.time())
        try:
            await self._run(("INSERT INTO groups VALUES (?, ?, ?, ?)",
                             (group.id, group.org_id, group.name, group.created_at)))
        except aiosqlite.IntegrityError as exc:
            raise GroupNameTaken(name) from exc
        return group

    async def get_group(self, group_id: str) -> Group | None:
        r = await self._one("SELECT * FROM groups WHERE id = ?", (group_id,))
        return None if r is None else Group(r["id"], r["org_id"], r["name"], r["created_at"])

    async def list_groups(self, org_id: str) -> list[Group]:
        rows = await self._all("SELECT * FROM groups WHERE org_id = ? ORDER BY name", (org_id,))
        return [Group(r["id"], r["org_id"], r["name"], r["created_at"]) for r in rows]

    async def delete_group(self, group_id: str) -> None:
        # Membership first: a member left holding a deleted group's id would
        # keep reading documents shared with it if the id were ever reused.
        await self._run(
            ("DELETE FROM subject_groups WHERE group_id = ?", (group_id,)),
            ("DELETE FROM groups WHERE id = ?", (group_id,)),
        )


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
        org = Organisation(id=org_id or _new_id("org"), name=name, domain=domain.strip().lower(),
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
            "groups": sorted(set(subject.groups)),
        })

    async def get_subject(self, kind: SubjectKind, subject_id: str) -> Subject | None:
        snap = await self._col("subjects").document(f"{kind}:{subject_id}").get()
        if not snap.exists:
            return None
        d = snap.to_dict() or {}
        return self._subject(kind, subject_id, d)

    @staticmethod
    def _subject(kind: SubjectKind, subject_id: str, d: dict[str, Any]) -> Subject:
        return Subject(kind=kind, id=subject_id, org_id=d.get("org_id", ""),
                       org_admin=bool(d.get("org_admin", False)),
                       roles={ws: Role(r) for ws, r in (d.get("roles") or {}).items()},
                       groups=tuple(d.get("groups") or ()))

    async def find_org_by_domain(self, domain: str) -> Organisation | None:
        if not domain:
            return None
        snaps = await self._col("orgs").where(
            filter=self._eq("domain", domain.strip().lower())).limit(1).get()
        for s in snaps:
            d = s.to_dict() or {}
            return Organisation(s.id, d.get("name", ""), d.get("domain", ""), d.get("created_at"))
        return None

    @staticmethod
    def _user(doc_id: str, d: dict[str, Any]) -> User:
        return User(doc_id, d.get("org_id", ""), d.get("email", ""), d.get("name", ""),
                    d.get("created_at"))

    async def get_user(self, user_id: str) -> User | None:
        snap = await self._col("users").document(user_id).get()
        return self._user(snap.id, snap.to_dict() or {}) if snap.exists else None

    async def list_users(self, org_id: str) -> list[User]:
        snaps = await self._col("users").where(filter=self._eq("org_id", org_id)).get()
        return sorted((self._user(s.id, s.to_dict() or {}) for s in snaps), key=lambda u: u.email)

    async def delete_user(self, user_id: str) -> None:
        await self._col("users").document(user_id).delete()
        await self.delete_subject("user", user_id)

    async def list_subjects(self, org_id: str, kind: SubjectKind) -> list[Subject]:
        snaps = await self._col("subjects").where(filter=self._eq("org_id", org_id)).get()
        out = []
        for s in snaps:
            d = s.to_dict() or {}
            if d.get("kind") == kind:
                out.append(self._subject(kind, str(d.get("id", "")), d))
        return out

    async def delete_subject(self, kind: SubjectKind, subject_id: str) -> None:
        await self._col("subjects").document(f"{kind}:{subject_id}").delete()

    @staticmethod
    def _invitation(d: dict[str, Any]) -> Invitation:
        return Invitation(
            email=d.get("email", ""), org_id=d.get("org_id", ""),
            org_admin=bool(d.get("org_admin", False)),
            roles={ws: Role(r) for ws, r in (d.get("roles") or {}).items()},
            invited_by=d.get("invited_by", ""), created_at=d.get("created_at"),
        )

    async def put_invitation(self, invitation: Invitation) -> None:
        email = normalise_email(invitation.email)
        await self._col("invitations").document(email).set({
            "email": email, "org_id": invitation.org_id, "org_admin": invitation.org_admin,
            "roles": {ws: role.value for ws, role in invitation.roles.items()},
            "invited_by": invitation.invited_by,
            "created_at": invitation.created_at or time.time(),
        })

    async def get_invitation(self, email: str) -> Invitation | None:
        snap = await self._col("invitations").document(normalise_email(email)).get()
        return self._invitation(snap.to_dict() or {}) if snap.exists else None

    async def list_invitations(self, org_id: str) -> list[Invitation]:
        snaps = await self._col("invitations").where(filter=self._eq("org_id", org_id)).get()
        return sorted((self._invitation(s.to_dict() or {}) for s in snaps), key=lambda i: i.email)

    async def delete_invitation(self, email: str) -> None:
        await self._col("invitations").document(normalise_email(email)).delete()

    @staticmethod
    def _group(doc_id: str, d: dict[str, Any]) -> Group:
        return Group(doc_id, d.get("org_id", ""), d.get("name", ""), d.get("created_at"))

    async def create_group(self, org_id: str, name: str) -> Group:
        if any(g.name == name for g in await self.list_groups(org_id)):
            raise GroupNameTaken(name)
        group = Group(id=_new_id("grp"), org_id=org_id, name=name, created_at=time.time())
        await self._col("groups").document(group.id).set(
            {"org_id": org_id, "name": name, "created_at": group.created_at})
        return group

    async def get_group(self, group_id: str) -> Group | None:
        snap = await self._col("groups").document(group_id).get()
        return self._group(snap.id, snap.to_dict() or {}) if snap.exists else None

    async def list_groups(self, org_id: str) -> list[Group]:
        snaps = await self._col("groups").where(filter=self._eq("org_id", org_id)).get()
        return sorted((self._group(s.id, s.to_dict() or {}) for s in snaps), key=lambda g: g.name)

    async def delete_group(self, group_id: str) -> None:
        group = await self.get_group(group_id)
        if group is not None:
            # Membership first, as in SQLite.
            for kind in ("user", "service"):
                for s in await self.list_subjects(group.org_id, kind):
                    if group_id in s.groups:
                        await self.put_subject(replace(
                            s, groups=tuple(g for g in s.groups if g != group_id)))
        await self._col("groups").document(group_id).delete()


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


class TenancyUnavailable(RuntimeError):
    """The tenancy store could not be read. The request is refused, not guessed:
    falling back to legacy would hand an organisation's key the public one."""


async def principal_for_key(key_id: object) -> Principal:
    """The principal behind an API key. Unmigrated keys keep today's access."""
    try:
        subject = await _store.get_subject("service", str(key_id))
    except Exception as exc:
        logger.warning("principal_lookup_failed", error=str(exc))
        raise TenancyUnavailable(str(exc)) from exc
    return legacy_key_principal(key_id) if subject is None else principal_from_subject(subject)


async def principal_for_user(user_id: str) -> Principal | None:
    """The principal behind a session; None once the member has been removed.

    Read on every request, not carried in the cookie, so removing a member or
    changing a role takes effect on their next request.
    """
    try:
        subject = await _store.get_subject("user", user_id)
    except Exception as exc:
        logger.warning("principal_lookup_failed", error=str(exc))
        raise TenancyUnavailable(str(exc)) from exc
    return None if subject is None else principal_from_subject(subject)


class NotInvited(PermissionError):
    """A Google account with no user, no invitation and no matching domain."""


async def place_user(store: TenancyStore, email: str, name: str, hosted_domain: str) -> User:
    """The user a verified Google sign-in becomes (docs/e1-identity.md §3).

    In order: an existing user; else an invitation, consumed here with its
    grants; else an organisation whose Workspace domain is the account's
    `hd` claim, which places the user with no workspace roles until an admin
    grants some. A personal address with no invitation is refused.
    """
    email = normalise_email(email)
    if (user := await store.find_user(email)) is not None:
        return user
    if (inv := await store.get_invitation(email)) is not None:
        user = await store.create_user(inv.org_id, email, name)
        await store.put_subject(Subject(kind="user", id=user.id, org_id=inv.org_id,
                                        org_admin=inv.org_admin, roles=dict(inv.roles)))
        await store.delete_invitation(email)
        logger.info("user_joined", org_id=inv.org_id, via="invitation")
        return user
    if hosted_domain and (org := await store.find_org_by_domain(hosted_domain)) is not None:
        user = await store.create_user(org.id, email, name)
        await store.put_subject(Subject(kind="user", id=user.id, org_id=org.id))
        logger.info("user_joined", org_id=org.id, via="domain")
        return user
    raise NotInvited(email)


async def principal_for_visitor(visitor_id: str, demo_namespace: str) -> Principal:
    try:
        ws = await _store.get_workspace(legacy_workspace_id(demo_namespace))
    except Exception as exc:
        logger.warning("principal_lookup_failed", error=str(exc))
        raise TenancyUnavailable(str(exc)) from exc
    # Before the migration the demo sheet has no record; it is still the
    # public workspace the migration will write, under the same id.
    return visitor_principal(visitor_id, ws or legacy_workspace(demo_namespace))


async def resolve_workspace(principal: Principal, name: str) -> Workspace | None:
    """The workspace *name* means to this caller, looked up in its own
    organisation only, so another organisation's name is simply not found."""
    org = principal.home_org
    if not org:
        return None
    try:
        ws = await find_workspace(_store, org, name)
    except Exception as exc:
        logger.warning("workspace_lookup_failed", error=str(exc))
        raise TenancyUnavailable(str(exc)) from exc
    if ws is None and org == PUBLIC_ORG_ID:
        ws = legacy_workspace(name)
    return ws


async def readable_workspaces(principal: Principal, namespaces: list[str]) -> list[Workspace]:
    """Every workspace this caller may read. *namespaces* are the collections
    Qdrant holds; in the public organisation those without a record count too."""
    org = principal.home_org
    if not org:
        return []
    try:
        found = await _store.list_workspaces(org)
    except Exception as exc:
        logger.warning("workspace_lookup_failed", error=str(exc))
        raise TenancyUnavailable(str(exc)) from exc
    if org == PUBLIC_ORG_ID:
        held = {w.collection for w in found}
        found += [w for ns in namespaces
                  if (w := legacy_workspace(ns)) is not None and w.collection not in held]
    return sorted((w for w in found if principal.can(w, "read")), key=lambda w: w.name)


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
