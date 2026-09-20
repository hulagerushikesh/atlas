"""
API-key persistence: SQLite for a single box, Firestore for Cloud Run.

Design rationale:
    Cloud Run's filesystem is ephemeral and every revision is a fresh
    container, so the SQLite file that served Phase D would lose every key
    on deploy. Firestore is the cheapest durable store on GCP (free tier
    covers this project many times over), needs no connection string —
    the service account is the credential — and its transforms let usage
    counters be bumped without a read-modify-write.

    Both backends implement the same five calls behind KeyStore, chosen by
    AUTH_STORE. The SQLite backend is the one used in tests and locally;
    nothing about the Firestore one is exercised without a project.

    Key ids: SQLite hands back an autoincrement int; Firestore documents are
    keyed by the SHA-256 of the raw key, so the id is that hash. Callers only
    ever pass the id back, so ApiKey.id is int | str.

    Usage in Firestore is kept as counters on the key document itself
    (total_queries, sum of tokens, sum of latency, a per-namespace map)
    rather than one row per query. Stats become a single document read and
    the write is a fire-and-forget Increment. Precision lost: no per-query
    history — a usage log for billing would want BigQuery anyway.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import aiosqlite
import structlog

logger = structlog.get_logger(__name__)

KeyId = int | str


@dataclass
class ApiKey:
    id: KeyId
    name: str
    email: str
    is_active: bool
    rate_limit_rpm: int


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_key() -> str:
    """Generate a random API key with an 'atlas_' prefix for easy identification."""
    return f"atlas_{secrets.token_urlsafe(32)}"


_EMPTY_STATS: dict[str, Any] = {
    "total_queries": 0,
    "cache_hits": 0,
    "total_prompt_tokens": 0,
    "total_completion_tokens": 0,
    "avg_latency_ms": 0.0,
    "first_query_at": None,
    "last_query_at": None,
    "by_namespace": [],
}


class KeyStore(Protocol):
    async def init(self) -> None: ...

    async def create_key(
        self, name: str, email: str = "", rate_limit_rpm: int = 60
    ) -> tuple[str, KeyId]: ...

    async def lookup_key(self, raw_key: str) -> ApiKey | None: ...

    async def log_usage(
        self,
        api_key_id: KeyId,
        namespace: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        cache_hit: bool,
    ) -> None: ...

    async def get_usage_stats(self, api_key_id: KeyId) -> dict[str, Any]: ...


# ── SQLite ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash    TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    email       TEXT    NOT NULL DEFAULT '',
    created_at  REAL    NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1,
    rate_limit_rpm INTEGER NOT NULL DEFAULT 60
);

CREATE TABLE IF NOT EXISTS usage_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id      INTEGER NOT NULL,
    namespace       TEXT    NOT NULL DEFAULT 'default',
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms      REAL    NOT NULL DEFAULT 0,
    cache_hit       INTEGER NOT NULL DEFAULT 0,
    created_at      REAL    NOT NULL,
    FOREIGN KEY (api_key_id) REFERENCES api_keys(id)
);

CREATE INDEX IF NOT EXISTS idx_usage_key ON usage_log(api_key_id);
CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_log(created_at);
"""


class SQLiteKeyStore:
    """One file next to the app. Keys are stored hashed; usage is one row per query."""

    def __init__(self, db_path: Path = Path("data/atlas.db")) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        logger.info("auth_db_ready", backend="sqlite", path=str(self.db_path))

    async def create_key(
        self, name: str, email: str = "", rate_limit_rpm: int = 60
    ) -> tuple[str, KeyId]:
        raw_key = generate_key()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO api_keys (key_hash, name, email, created_at, rate_limit_rpm) "
                "VALUES (?, ?, ?, ?, ?)",
                (hash_key(raw_key), name, email, time.time(), rate_limit_rpm),
            )
            await db.commit()
            key_id = cursor.lastrowid
        logger.info("api_key_created", name=name, key_id=key_id)
        return raw_key, key_id  # type: ignore[return-value]

    async def lookup_key(self, raw_key: str) -> ApiKey | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, name, email, is_active, rate_limit_rpm "
                "FROM api_keys WHERE key_hash = ?",
                (hash_key(raw_key),),
            )
            row = await cursor.fetchone()
        if row is None or not row["is_active"]:
            return None
        return ApiKey(
            id=row["id"],
            name=row["name"],
            email=row["email"],
            is_active=bool(row["is_active"]),
            rate_limit_rpm=row["rate_limit_rpm"],
        )

    async def log_usage(
        self,
        api_key_id: KeyId,
        namespace: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        cache_hit: bool,
    ) -> None:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "INSERT INTO usage_log "
                    "(api_key_id, namespace, prompt_tokens, completion_tokens, "
                    "latency_ms, cache_hit, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (api_key_id, namespace, prompt_tokens, completion_tokens,
                     latency_ms, int(cache_hit), time.time()),
                )
                await db.commit()
        except Exception as exc:
            logger.warning("usage_log_failed", error=str(exc))

    async def get_usage_stats(self, api_key_id: KeyId) -> dict[str, Any]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                """SELECT
                    COUNT(*)                          AS total_queries,
                    SUM(cache_hit)                    AS cache_hits,
                    SUM(prompt_tokens)                AS total_prompt_tokens,
                    SUM(completion_tokens)            AS total_completion_tokens,
                    AVG(latency_ms)                   AS avg_latency_ms,
                    MIN(created_at)                   AS first_query_at,
                    MAX(created_at)                   AS last_query_at
                   FROM usage_log WHERE api_key_id = ?""",
                (api_key_id,),
            )).fetchone()
            ns_rows = await (await db.execute(
                "SELECT namespace, COUNT(*) AS cnt FROM usage_log "
                "WHERE api_key_id = ? GROUP BY namespace ORDER BY cnt DESC",
                (api_key_id,),
            )).fetchall()

        # An aggregate SELECT always yields one row, but fetchone() is typed
        # Optional and a schema change could make that untrue.
        if row is None:
            return dict(_EMPTY_STATS)
        return {
            "total_queries": row["total_queries"] or 0,
            "cache_hits": row["cache_hits"] or 0,
            "total_prompt_tokens": row["total_prompt_tokens"] or 0,
            "total_completion_tokens": row["total_completion_tokens"] or 0,
            "avg_latency_ms": round(row["avg_latency_ms"] or 0, 1),
            "first_query_at": row["first_query_at"],
            "last_query_at": row["last_query_at"],
            "by_namespace": [
                {"namespace": r["namespace"], "queries": r["cnt"]} for r in ns_rows
            ],
        }


# ── Firestore ─────────────────────────────────────────────────────────────────

class FirestoreKeyStore:
    """
    Document per key at {collection}/{sha256(raw_key)}; usage counters live on
    the same document. The client is built lazily so importing this module
    never needs google-cloud-firestore or credentials.
    """

    def __init__(self, project: str | None = None, collection: str = "atlas_api_keys",
                 client: Any = None) -> None:
        self._project = project
        self._collection = collection
        self._client = client

    def _keys(self) -> Any:
        if self._client is None:
            from google.cloud import firestore  # noqa: PLC0415 — optional dependency

            self._client = firestore.AsyncClient(project=self._project)
        return self._client.collection(self._collection)

    async def init(self) -> None:
        # Firestore has no schema; touching the collection surfaces a missing
        # database or credential at startup rather than on the first request.
        await self._keys().limit(1).get()
        logger.info("auth_db_ready", backend="firestore", collection=self._collection)

    async def create_key(
        self, name: str, email: str = "", rate_limit_rpm: int = 60
    ) -> tuple[str, KeyId]:
        raw_key = generate_key()
        key_id = hash_key(raw_key)
        await self._keys().document(key_id).set({
            "name": name,
            "email": email,
            "created_at": time.time(),
            "is_active": True,
            "rate_limit_rpm": rate_limit_rpm,
            "usage": {
                "total_queries": 0,
                "cache_hits": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "latency_ms_sum": 0.0,
                "first_query_at": None,
                "last_query_at": None,
                "by_namespace": {},
            },
        })
        logger.info("api_key_created", name=name, key_id=key_id[:8])
        return raw_key, key_id

    async def lookup_key(self, raw_key: str) -> ApiKey | None:
        snap = await self._keys().document(hash_key(raw_key)).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        if not data.get("is_active", False):
            return None
        return ApiKey(
            id=snap.id,
            name=data.get("name", ""),
            email=data.get("email", ""),
            is_active=True,
            rate_limit_rpm=int(data.get("rate_limit_rpm", 60)),
        )

    async def log_usage(
        self,
        api_key_id: KeyId,
        namespace: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        cache_hit: bool,
    ) -> None:
        try:
            from google.cloud.firestore_v1 import Increment  # noqa: PLC0415

            now = time.time()
            await self._keys().document(str(api_key_id)).update({
                "usage.total_queries": Increment(1),
                "usage.cache_hits": Increment(1 if cache_hit else 0),
                "usage.prompt_tokens": Increment(prompt_tokens),
                "usage.completion_tokens": Increment(completion_tokens),
                "usage.latency_ms_sum": Increment(latency_ms),
                "usage.last_query_at": now,
                f"usage.by_namespace.{namespace}": Increment(1),
            })
        except Exception as exc:
            logger.warning("usage_log_failed", error=str(exc))

    async def get_usage_stats(self, api_key_id: KeyId) -> dict[str, Any]:
        snap = await self._keys().document(str(api_key_id)).get()
        if not snap.exists:
            return dict(_EMPTY_STATS)
        u = (snap.to_dict() or {}).get("usage", {})
        total = int(u.get("total_queries", 0))
        by_ns = sorted(
            u.get("by_namespace", {}).items(), key=lambda kv: kv[1], reverse=True
        )
        return {
            "total_queries": total,
            "cache_hits": int(u.get("cache_hits", 0)),
            "total_prompt_tokens": int(u.get("prompt_tokens", 0)),
            "total_completion_tokens": int(u.get("completion_tokens", 0)),
            "avg_latency_ms": round(u.get("latency_ms_sum", 0.0) / total, 1) if total else 0.0,
            # first_query_at is not tracked by the counters; created_at is the
            # closest honest answer and always precedes the first query.
            "first_query_at": (snap.to_dict() or {}).get("created_at") if total else None,
            "last_query_at": u.get("last_query_at"),
            "by_namespace": [{"namespace": ns, "queries": int(n)} for ns, n in by_ns],
        }


def build_key_store(backend: str, *, sqlite_path: Path | None = None,
                    firestore_project: str | None = None) -> KeyStore:
    if backend == "sqlite":
        return SQLiteKeyStore(sqlite_path or Path("data/atlas.db"))
    if backend == "firestore":
        return FirestoreKeyStore(project=firestore_project)
    raise ValueError(f"unknown AUTH_STORE {backend!r}; expected 'sqlite' or 'firestore'")
