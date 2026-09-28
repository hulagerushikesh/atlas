"""
Tests for per-model token accounting.

The property under test that is easy to get wrong is scope inheritance: the
eval runner and the /query route both count a *scope* of work, not a
process, and both fan out into tasks. If a task did not inherit the scope,
the counts would be silently low — which is the exact failure the meter
exists to end.
"""

from __future__ import annotations

import asyncio

import pytest

from atlas.usage import ModelUsage, UsageMeter, usage_scope


class TestUsageMeter:
    def test_records_calls_and_tokens(self) -> None:
        meter = UsageMeter()
        meter.record("chat-1", prompt_tokens=100, completion_tokens=20)
        meter.record("chat-1", prompt_tokens=50, completion_tokens=5)

        entry = meter.by_model["chat-1"]
        assert (entry.calls, entry.prompt_tokens, entry.completion_tokens) == (2, 150, 25)
        assert entry.total_tokens == 175
        assert meter.total_tokens == 175

    def test_by_model_is_a_copy(self) -> None:
        meter = UsageMeter()
        meter.record("chat-1", prompt_tokens=10)
        meter.by_model["chat-1"].prompt_tokens = 9999
        assert meter.by_model["chat-1"].prompt_tokens == 10

    def test_calls_by_model_filters_kind(self) -> None:
        """The report's mixed-model warning fires on a second model; without
        this filter the embedding model would trip it on every run."""
        meter = UsageMeter()
        meter.record("chat-1", prompt_tokens=10, completion_tokens=1)
        meter.record("embed-1", kind="embedding", prompt_tokens=7)

        assert meter.calls_by_model(kind="chat") == {"chat-1": 1}
        assert meter.calls_by_model() == {"chat-1": 1, "embed-1": 1}

    def test_merge_preserves_call_counts(self) -> None:
        source = UsageMeter()
        source.record("chat-1", prompt_tokens=10, completion_tokens=2)
        source.record("chat-1", prompt_tokens=10, completion_tokens=2)

        target = UsageMeter()
        target.record("chat-1", prompt_tokens=1, completion_tokens=1)
        target.merge(source.by_model)

        entry = target.by_model["chat-1"]
        assert (entry.calls, entry.prompt_tokens, entry.completion_tokens) == (3, 21, 5)

    def test_empty_meter_is_falsey(self) -> None:
        assert not UsageMeter()
        meter = UsageMeter()
        meter.record("chat-1")
        assert meter


class TestUsageScope:
    def test_scope_sees_a_providers_records(self) -> None:
        provider = UsageMeter()
        with usage_scope() as scope:
            provider.record("chat-1", prompt_tokens=30, completion_tokens=3)
        assert scope.by_model["chat-1"].prompt_tokens == 30
        # And the provider keeps its own lifetime total.
        assert provider.by_model["chat-1"].prompt_tokens == 30

    def test_records_outside_a_scope_reach_no_scope(self) -> None:
        provider = UsageMeter()
        provider.record("chat-1", prompt_tokens=5)
        with usage_scope() as scope:
            pass
        assert scope.by_model == {}

    def test_scope_does_not_double_count_itself(self) -> None:
        with usage_scope() as scope:
            scope.record("chat-1", prompt_tokens=10)
        assert scope.by_model["chat-1"].calls == 1
        assert scope.by_model["chat-1"].prompt_tokens == 10

    @pytest.mark.asyncio
    async def test_child_tasks_inherit_the_scope(self) -> None:
        """asyncio copies the context into a new task, and the copy holds the
        same meter object — which is what makes a fanned-out eval run or a
        pipeline's parallel sub-queries add up."""
        provider = UsageMeter()

        async def one_call(n: int) -> None:
            await asyncio.sleep(0)
            provider.record("chat-1", prompt_tokens=n)

        with usage_scope() as scope:
            await asyncio.gather(*[one_call(n) for n in (1, 2, 3)])

        assert scope.by_model["chat-1"].calls == 3
        assert scope.by_model["chat-1"].prompt_tokens == 6

    @pytest.mark.asyncio
    async def test_concurrent_scopes_do_not_mix(self) -> None:
        """Two requests in one process must not be charged each other's
        tokens. This is why the API scopes instead of diffing a lifetime
        counter."""
        provider = UsageMeter()
        started = asyncio.Event()

        async def request(tokens: int, wait: bool) -> UsageMeter:
            with usage_scope() as scope:
                if wait:
                    started.set()
                    await asyncio.sleep(0.01)
                else:
                    await started.wait()
                provider.record("chat-1", prompt_tokens=tokens)
                return scope

        slow, fast = await asyncio.gather(request(100, True), request(7, False))

        assert slow.total_tokens == 100
        assert fast.total_tokens == 7
        assert provider.total_tokens == 107

    def test_scope_is_restored_after_exit(self) -> None:
        with usage_scope() as outer:
            with usage_scope() as inner:
                UsageMeter().record("chat-1", prompt_tokens=1)
            UsageMeter().record("chat-1", prompt_tokens=2)

        assert inner.total_tokens == 1
        # The inner scope shadows the outer rather than nesting into it; only
        # what was recorded after it closed lands here.
        assert outer.total_tokens == 2


class TestModelUsage:
    def test_kind_defaults_to_chat(self) -> None:
        assert ModelUsage().kind == "chat"

    def test_total_is_prompt_plus_completion(self) -> None:
        assert ModelUsage(prompt_tokens=8, completion_tokens=2).total_tokens == 10
