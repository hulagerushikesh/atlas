#!/usr/bin/env python3
"""
check_health.py — verify all Atlas infrastructure is reachable before running.

Checks:
  1. OpenAI API key is valid and the embedding model responds.
  2. Qdrant is reachable and the collection (if it exists) is accessible.
  3. Redis is reachable and accepts PING.

Exit code 0 = all green. Exit code 1 = one or more failures.

Usage:
    python scripts/check_health.py
    python scripts/check_health.py --quiet   # suppress passing checks
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import NamedTuple

# Ensure the installed package is on the path when run from repo root.
sys.path.insert(0, "src")


class CheckResult(NamedTuple):
    name: str
    ok: bool
    latency_ms: float
    detail: str


async def check_openai(settings) -> CheckResult:
    import openai

    client = openai.AsyncOpenAI(api_key=settings.openai.api_key)
    t0 = time.perf_counter()
    try:
        resp = await client.embeddings.create(
            model=settings.openai.embedding_model,
            input=["health check"],
        )
        ms = (time.perf_counter() - t0) * 1000
        dims = len(resp.data[0].embedding)
        return CheckResult("OpenAI embeddings", True, ms, f"model={settings.openai.embedding_model} dims={dims}")
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return CheckResult("OpenAI embeddings", False, ms, str(exc))
    finally:
        await client.close()


async def check_qdrant(settings) -> CheckResult:
    from qdrant_client import AsyncQdrantClient

    client = AsyncQdrantClient(url=settings.qdrant.url)
    t0 = time.perf_counter()
    try:
        collections = await client.get_collections()
        ms = (time.perf_counter() - t0) * 1000
        names = [c.name for c in collections.collections]
        detail = f"collections={names}" if names else "no collections yet"
        return CheckResult("Qdrant", True, ms, detail)
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return CheckResult("Qdrant", False, ms, str(exc))
    finally:
        await client.close()


async def check_redis(settings) -> CheckResult:
    import redis.asyncio as aioredis

    client = aioredis.from_url(settings.redis.url, encoding="utf-8", decode_responses=True)
    t0 = time.perf_counter()
    try:
        await client.ping()
        ms = (time.perf_counter() - t0) * 1000
        return CheckResult("Redis", True, ms, f"url={settings.redis.url}")
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return CheckResult("Redis", False, ms, str(exc))
    finally:
        await client.aclose()


def _fmt(result: CheckResult, quiet: bool) -> str | None:
    icon = "✓" if result.ok else "✗"
    status = "OK" if result.ok else "FAIL"
    line = f"  {icon} {result.name:<22} {status:<6} {result.latency_ms:>6.1f}ms   {result.detail}"
    if quiet and result.ok:
        return None
    return line


async def main(quiet: bool) -> int:
    from atlas.config import get_settings
    from atlas.logging import configure_logging

    configure_logging(level="WARNING", json=False)
    settings = get_settings()

    print("Atlas infrastructure health check")
    print("─" * 60)

    results = await asyncio.gather(
        check_openai(settings),
        check_qdrant(settings),
        check_redis(settings),
        return_exceptions=False,
    )

    all_ok = True
    for r in results:
        line = _fmt(r, quiet)
        if line:
            print(line)
        if not r.ok:
            all_ok = False

    print("─" * 60)
    if all_ok:
        print("All checks passed.")
        return 0
    else:
        failed = [r.name for r in results if not r.ok]
        print(f"Failed: {', '.join(failed)}")
        print("Run `docker-compose up qdrant redis -d` to start infrastructure.")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check Atlas infrastructure health.")
    parser.add_argument("--quiet", action="store_true", help="Only print failures.")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.quiet)))
