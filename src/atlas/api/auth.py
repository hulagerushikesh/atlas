"""
API-key auth facade: a process-wide KeyStore plus the rate limiter.

Design rationale:
    Callers (middleware, /keys, /query usage logging) import this module and
    call plain functions; which store answers is decided once at startup by
    configure_store(). That keeps the store choice out of every route and
    lets tests run against SQLite in a temp dir without patching imports.

    Keys are stored as SHA-256 hashes in both backends; the raw key is shown
    only once at creation time. Usage writes are fire-and-forget after the
    response is sent — a missing usage row beats a slow response.

    Rate limiting: Redis sliding-window if available, in-memory fallback
    (per-process, resets on restart). The in-memory fallback is acceptable
    for a single instance; Redis is needed once there are several.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atlas.api.keystore import (
    ApiKey,
    KeyId,
    KeyStore,
    SQLiteKeyStore,
    build_key_store,
    generate_key,
    hash_key,
)

__all__ = [
    "ApiKey", "KeyId", "generate_key", "hash_key", "configure_store", "get_store",
    "init_db", "create_key", "lookup_key", "log_usage", "get_usage_stats",
    "check_rate_limit",
]

_store: KeyStore = SQLiteKeyStore()


def configure_store(backend: str = "sqlite", *, sqlite_path: Path | None = None,
                    firestore_project: str | None = None) -> KeyStore:
    """Choose the backend for this process. Called once from the app lifespan."""
    global _store
    _store = build_key_store(
        backend, sqlite_path=sqlite_path, firestore_project=firestore_project
    )
    return _store


def get_store() -> KeyStore:
    return _store


async def init_db() -> None:
    await _store.init()


async def create_key(name: str, email: str = "", rate_limit_rpm: int = 60) -> tuple[str, KeyId]:
    return await _store.create_key(name, email, rate_limit_rpm)


async def lookup_key(raw_key: str) -> ApiKey | None:
    return await _store.lookup_key(raw_key)


async def log_usage(
    api_key_id: KeyId,
    namespace: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: float,
    cache_hit: bool,
) -> None:
    await _store.log_usage(
        api_key_id, namespace, prompt_tokens, completion_tokens, latency_ms, cache_hit
    )


async def get_usage_stats(api_key_id: KeyId) -> dict[str, Any]:
    return await _store.get_usage_stats(api_key_id)


# ── In-memory rate limiter (per-process fallback) ─────────────────────────────

@dataclass
class _Window:
    timestamps: list[float] = field(default_factory=list)

_windows: dict[KeyId, _Window] = defaultdict(_Window)


def _check_rate_limit_memory(key_id: KeyId, rpm: int) -> bool:
    """Sliding-window rate check. Returns True if the request is allowed."""
    now = time.time()
    window = _windows[key_id]
    window.timestamps = [t for t in window.timestamps if now - t < 60.0]
    if len(window.timestamps) >= rpm:
        return False
    window.timestamps.append(now)
    return True


async def check_rate_limit(key_id: KeyId, rpm: int, redis_client: Any = None) -> bool:
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
        count = int(results[2])
        return count <= rpm
    except Exception:
        return _check_rate_limit_memory(key_id, rpm)
