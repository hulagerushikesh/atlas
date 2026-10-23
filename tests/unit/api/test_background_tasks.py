"""
What happens to work the response does not wait for.

Three writes on `/query` are deliberately un-awaited: the per-key usage
record, and the cache writes on both the hit and miss paths. They are not
optional — `cost / query` in BUDGET.md is computed from the first of them —
so "off the response path" has to mean deferred, not best-effort.

Two ways a bare `create_task` makes it best-effort, both covered here: the
loop holds only a weak reference, and nothing waits at shutdown.
"""

from __future__ import annotations

import asyncio

import pytest
import structlog.testing
from fastapi.testclient import TestClient

from atlas.api import background


@pytest.fixture(autouse=True)
def _clean() -> None:
    background._pending.clear()


class TestASpawnedTaskSurvivesUntilItFinishes:
    @pytest.mark.asyncio
    async def test_it_is_tracked_while_in_flight(self) -> None:
        gate = asyncio.Event()

        async def work() -> None:
            await gate.wait()

        background.spawn(work(), name="w")
        assert background.pending_count() == 1
        gate.set()
        await background.drain()
        assert background.pending_count() == 0

    @pytest.mark.asyncio
    async def test_it_is_not_collected_while_only_the_loop_refers_to_it(self) -> None:
        # The failure this guards is a garbage collection between creating
        # the task and its first completed step. asyncio documents the loop
        # as holding only a weak reference, so a `create_task` whose result
        # nobody keeps can vanish mid-write. Forcing a collection with no
        # local reference held is the only way to make that deterministic.
        import gc

        ran = asyncio.Event()

        async def work() -> None:
            await asyncio.sleep(0)
            ran.set()

        background.spawn(work(), name="w")
        gc.collect()
        await asyncio.wait_for(ran.wait(), timeout=1.0)

    @pytest.mark.asyncio
    async def test_a_finished_task_stops_being_tracked(self) -> None:
        async def work() -> None:
            return None

        background.spawn(work(), name="w")
        await background.drain()
        assert background.pending_count() == 0


class TestDrainWaitsForWhatIsStillInTheAir:
    @pytest.mark.asyncio
    async def test_it_lets_a_slow_write_finish(self) -> None:
        done: list[str] = []

        async def slow() -> None:
            await asyncio.sleep(0.05)
            done.append("written")

        background.spawn(slow(), name="log_usage")
        assert done == []
        lost = await background.drain()
        assert done == ["written"]
        assert lost == 0

    @pytest.mark.asyncio
    async def test_it_reports_what_it_could_not_wait_for(self) -> None:
        # A non-zero return is the count of records the instance is about
        # to lose. It is the only evidence the timeout is set too low, so
        # it is a number and a log line, not a silent return.
        async def never() -> None:
            await asyncio.sleep(10)

        task = background.spawn(never(), name="log_usage")
        with structlog.testing.capture_logs() as logs:
            lost = await background.drain(timeout=0.01)

        assert lost == 1
        incomplete = [e for e in logs if e.get("event") == "background_drain_incomplete"]
        assert len(incomplete) == 1
        assert incomplete[0]["lost"] == 1
        assert incomplete[0]["names"] == ["log_usage"]
        task.cancel()

    @pytest.mark.asyncio
    async def test_draining_nothing_is_free_and_silent(self) -> None:
        with structlog.testing.capture_logs() as logs:
            assert await background.drain() == 0
        assert logs == []


class TestAFailedWriteIsVisible:
    @pytest.mark.asyncio
    async def test_the_exception_is_logged_against_the_task_name(self) -> None:
        # Un-awaited, this reaches stderr at collection time as "Task
        # exception was never retrieved", detached from any request and
        # from the name of the thing that failed. A Firestore write failing
        # on every query should read as a rate, not as noise.
        async def boom() -> None:
            raise RuntimeError("firestore unavailable")

        with structlog.testing.capture_logs() as logs:
            background.spawn(boom(), name="log_usage")
            await background.drain()

        failed = [e for e in logs if e.get("event") == "background_task_failed"]
        assert len(failed) == 1
        assert failed[0]["task"] == "log_usage"
        assert "firestore unavailable" in failed[0]["error"]

    @pytest.mark.asyncio
    async def test_one_failure_does_not_take_the_others_with_it(self) -> None:
        done: list[str] = []

        async def boom() -> None:
            raise RuntimeError("no")

        async def ok() -> None:
            await asyncio.sleep(0.01)
            done.append("written")

        background.spawn(boom(), name="a")
        background.spawn(ok(), name="b")
        assert await background.drain() == 0
        assert done == ["written"]


class TestShutdownDoesNotAbandonThem:
    def test_the_lifespan_drains_before_it_closes_anything(self) -> None:
        # Ordering matters: redis is closed in the same block, and a cache
        # write draining into a closed client is the loss this is meant to
        # prevent, wearing a different error message.
        import inspect

        from atlas.api import app as app_mod

        source = inspect.getsource(app_mod._lifespan)
        assert "await drain()" in source
        assert source.index("await drain()") < source.index("redis_client.aclose()")


class TestTheQueryRouteSpawnsThroughTheRegistry:
    """A call site that still uses a bare `create_task` is not covered by
    any of the above, and looks identical in review."""

    def test_no_bare_create_task_remains_on_the_query_path(self) -> None:
        import inspect

        from atlas.api.routes import query as query_route

        source = inspect.getsource(query_route)
        assert "asyncio.create_task" not in source, (
            "a fire-and-forget write that bypasses background.spawn is neither "
            "referenced nor drained"
        )

    def test_a_query_registers_its_cache_write(self, client: TestClient) -> None:
        from unittest.mock import AsyncMock

        names: list[str] = []
        original = background.spawn

        def spy(coro: object, *, name: str) -> object:
            names.append(name)
            return original(coro, name=name)  # type: ignore[arg-type]

        from atlas.api.routes import query as query_route

        query_route.spawn = spy  # type: ignore[assignment]
        try:
            client.app.state.atlas.spend.add = AsyncMock()
            resp = client.post("/query", json={"query": "What is Atlas?"})
        finally:
            query_route.spawn = original  # type: ignore[assignment]

        assert resp.status_code == 200, resp.text
        assert names == ["cache_set"]
