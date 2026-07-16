"""
API key storage and usage tracking via SQLite.

Design rationale:
    SQLite is chosen over Postgres/Redis for Phase D because it requires zero
    extra infra — the file lives alongside the application and is sufficient
    for hundreds of keys and millions of usage rows. Upgrading to Postgres is
    a one-file change (swap aiosqlite for asyncpg + adjust SQL dialect).

    Keys are stored as SHA-256 hashes; the raw key is shown only once at
    creation time and never stored. This means a stolen DB file does not
    expose valid keys.

    Usage rows are written fire-and-forget after each query response is sent —
    they never block the client. A missing usage row is better than a slow
    response.

    Rate limiting: Redis sliding-window if available, in-memory fallback
    (per-process, resets on restart). The in-memory fallback is acceptable
    for single-worker dev deployments; Redis is required for multi-worker prod.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite
import structlog

logger = structlog.get_logger(__name__)

_DB_PATH = Path("data/atlas.db")
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


@dataclass
class ApiKey:
    id: int
    name: str
    email: str
    is_active: bool
    rate_limit_rpm: int


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_key() -> str:
    """Generate a new random API key with an 'atl_' prefix."""
    return "atl_" + secrets.token_urlsafe(32)


async def init_db(db_path: Path = _DB_PATH) -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
    logger.info("auth_db_ready", path=str(db_path))


async def create_key(
    name: str,
    email: str = "",
    rate_limit_rpm: int = 60,
    db_path: Path = _DB_PATH,
) -> tuple[str, int]:
    """
    Create a new API key. Returns (raw_key, key_id).
    The raw key is shown once and never stored — only its hash is saved.
    """
    raw_key = generate_key()
    key_hash = _hash_key(raw_key)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "INSERT INTO api_keys (key_hash, name, email, created_at, rate_limit_rpm) "
            "VALUES (?, ?, ?, ?, ?)",
            (key_hash, name, email, time.time(), rate_limit_rpm),
        )
        await db.commit()
        key_id = cursor.lastrowid
    logger.info("api_key_created", name=name, key_id=key_id)
    return raw_key, key_id  # type: ignore[return-value]


async def lookup_key(raw_key: str, db_path: Path = _DB_PATH) -> ApiKey | None:
    """Return the ApiKey record for a raw key, or None if invalid/inactive."""
    key_hash = _hash_key(raw_key)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, name, email, is_active, rate_limit_rpm "
            "FROM api_keys WHERE key_hash = ?",
            (key_hash,),
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
    api_key_id: int,
    namespace: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: float,
    cache_hit: bool,
    db_path: Path = _DB_PATH,
) -> None:
    """Append a usage row. Fire-and-forget — never awaited by callers."""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "INSERT INTO usage_log "
                "(api_key_id, namespace, prompt_tokens, completion_tokens, latency_ms, cache_hit, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (api_key_id, namespace, prompt_tokens, completion_tokens,
                 latency_ms, int(cache_hit), time.time()),
            )
            await db.commit()
    except Exception as exc:
        logger.warning("usage_log_failed", error=str(exc))


async def get_usage_stats(
    api_key_id: int,
    db_path: Path = _DB_PATH,
) -> dict:
    """Aggregate usage stats for one API key."""
    async with aiosqlite.connect(db_path) as db:
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

    return {
        "total_queries": row["total_queries"] or 0,
        "cache_hits": row["cache_hits"] or 0,
        "total_prompt_tokens": row["total_prompt_tokens"] or 0,
        "total_completion_tokens": row["total_completion_tokens"] or 0,
        "avg_latency_ms": round(row["avg_latency_ms"] or 0, 1),
        "first_query_at": row["first_query_at"],
        "last_query_at": row["last_query_at"],
        "by_namespace": [{"namespace": r["namespace"], "queries": r["cnt"]} for r in ns_rows],
    }


# ── In-memory rate limiter (per-process fallback) ─────────────────────────────

@dataclass
class _Window:
    timestamps: list[float] = field(default_factory=list)

_windows: dict[int, _Window] = defaultdict(_Window)


def _check_rate_limit_memory(key_id: int, rpm: int) -> bool:
    """Sliding-window rate check. Returns True if the request is allowed."""
    now = time.time()
    window = _windows[key_id]
    window.timestamps = [t for t in window.timestamps if now - t < 60.0]
    if len(window.timestamps) >= rpm:
        return False
    window.timestamps.append(now)
    return True


async def check_rate_limit(key_id: int, rpm: int, redis_client=None) -> bool:  # type: ignore[return]
    """Check rate limit. Uses Redis if available, in-memory fallback otherwise."""
    if redis_client is None:
        return _check_rate_limit_memory(key_id, rpm)
    try:
        pipe = redis_client.pipeline()
        bucket = f"rl:{key_id}"
        now_ms = int(time.time() * 1000)
        cutoff = now_ms - 60_000
        await pipe.zremrangebyscore(bucket, "-inf", cutoff)
        await pipe.zadd(bucket, {str(now_ms): now_ms})
        await pipe.zcard(bucket)
        await pipe.expire(bucket, 70)
        results = await pipe.execute()
        count = results[2]
        return count <= rpm
    except Exception:
        return _check_rate_limit_memory(key_id, rpm)
