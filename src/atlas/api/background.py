"""
Fire-and-forget tasks that still have to finish.

Why this exists:
    Three things on the `/query` path are deliberately not awaited: the
    per-key usage record, the cache write, and the cache write's cache-hit
    sibling. Awaiting any of them puts a round trip to Firestore or Redis in
    front of the response, which is the wrong trade for work the caller does
    not need.

    `asyncio.create_task` alone pays for that in two ways the route never
    sees. The task is only weakly referenced by the loop, so a garbage
    collection between creation and completion can drop it mid-flight — the
    behaviour `app.py` already works around by hand for the reranker warm
    task. And nothing waits for it at shutdown: an instance torn down in
    that window loses whatever was in the air.

    Cloud Run scale-in is when both happen, and scale-in follows a burst, so
    the records most likely to be lost are the ones from the busiest minute.
    That only became a correctness problem on 2026-10-22, when BUDGET.md's
    `cost / query` started being computed from those per-key counters: an
    under-count there reads as the service being cheaper than it is, which
    is the direction nobody checks.

Why a set and not a list:
    The task removes itself in a done callback, so the set is the live
    in-flight population at any moment rather than a log of everything ever
    spawned. `drain()` is then a snapshot of what is actually outstanding.

Failures:
    An un-awaited task that raises gets its traceback printed by asyncio at
    garbage-collection time, to stderr, with no request context attached.
    `spawn` logs it instead, under a name the caller gives, so a Firestore
    write that is failing every time is visible as a rate rather than as
    noise in the container log.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_pending: set[asyncio.Task[Any]] = set()

# Cloud Run sends SIGTERM and then SIGKILL ten seconds later, and the
# shutdown path has other work after this. A drain that outlives the grace
# period is not a longer drain, it is the same loss plus a hang, so the
# budget is deliberately well inside it.
DRAIN_TIMEOUT_S = 5.0


def spawn(coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
    """Run *coro* off the response path, holding a reference until it ends."""
    task = asyncio.create_task(coro, name=name)
    _pending.add(task)
    task.add_done_callback(_finish)
    return task


def _finish(task: asyncio.Task[Any]) -> None:
    _pending.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("background_task_failed", task=task.get_name(), error=str(exc))


def pending_count() -> int:
    """How many spawned tasks have not finished."""
    return len(_pending)


async def drain(timeout: float = DRAIN_TIMEOUT_S) -> int:
    """Wait for in-flight tasks. Returns how many were still unfinished.

    A non-zero return is the count of records this instance is about to
    lose, which is worth a log line even though nothing can be done about
    it: it is the only evidence that the timeout is set too low.
    """
    if not _pending:
        return 0
    outstanding = set(_pending)
    logger.info("background_drain_start", tasks=len(outstanding))
    _done, unfinished = await asyncio.wait(outstanding, timeout=timeout)
    if unfinished:
        logger.warning(
            "background_drain_incomplete",
            lost=len(unfinished),
            names=sorted({t.get_name() for t in unfinished}),
        )
    else:
        logger.info("background_drain_complete", tasks=len(outstanding))
    return len(unfinished)
