"""
Per-model token accounting.

Why this exists:
    Until 2026-09-28 the only tokens anything counted were the generation
    call's. `runner.py` stashed `prompt_tokens + completion_tokens` off
    `result.generation` and summed that over the samples, so "total tokens" in
    every eval report ever written left out the router, the decomposer, the
    grader, the faithfulness checker, both LLM judges, and every embedding.
    The figure was consistent across runs, so comparing two reports still
    worked — but it was not what the run cost, and it was being read as one.

    The API had the same hole somewhere it matters more. `/query` priced a
    request from the generation call alone and added that number to the daily
    spend cap, so the cap admitted roughly twice the spend it was set to. The
    route's own docstring described the gap and left it open.

    A provider is the only object that sees every call it makes, so it is the
    only place that can count honestly. `UsageMeter` lives on the provider and
    accumulates for the provider's lifetime — the shape `model_calls` already
    had, with the tokens it should have carried from the start.

Why scopes:
    A lifetime counter answers "what has this process spent?". Both callers
    need a narrower question — "what did this eval run spend?", "what did this
    request spend?" — and neither can be answered by subtracting two readings,
    because an API process serves requests concurrently and their deltas
    interleave.

    `usage_scope()` puts a meter in a ContextVar. Every record inside it
    writes to the provider's own meter *and* to the scope's. asyncio copies
    the context when a task is created, so the sub-tasks a pipeline fans out
    inherit the same meter object and add to it, while a request running
    concurrently in another task holds a different one. That inheritance is
    the property that makes per-request accounting correct rather than
    approximately correct under load.

Rounding: none. These are counts of tokens as the API reported them, except
where an endpoint omits usage — the embedder approximates at ~4 chars/token
and says so at the call site, and the streaming path does the same, because a
silent zero in a spend cap is worse than a known approximation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal, TypeVar

from pydantic import BaseModel

Kind = Literal["chat", "embedding"]
T = TypeVar("T")


class ModelUsage(BaseModel):
    """What one model was asked for, and how much of it.

    `kind` is stored rather than inferred from the model name: pricing a
    completion at chat rates when it was an embedding overstates it by a
    factor of ten or more, and an unfamiliar model name is exactly the case
    where a guess would be wrong.
    """

    kind: Kind = "chat"
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class UsageMeter:
    """Token and call counts per model, for the life of whatever holds it."""

    def __init__(self) -> None:
        self._by_model: dict[str, ModelUsage] = {}

    def record(
        self,
        model: str,
        *,
        kind: Kind = "chat",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        """Count one call against *model*, here and in the active scope."""
        self._add(model, kind, prompt_tokens, completion_tokens)
        scoped = _active_scope.get()
        # `is not self` guards the case where the scope's own meter is what
        # was recorded into directly — counting it twice would be worse than
        # not counting it, because it would look plausible.
        if scoped is not None and scoped is not self:
            scoped._add(model, kind, prompt_tokens, completion_tokens)

    def _add(self, model: str, kind: Kind, prompt: int, completion: int) -> None:
        entry = self._by_model.get(model)
        if entry is None:
            entry = self._by_model[model] = ModelUsage(kind=kind)
        entry.calls += 1
        entry.prompt_tokens += prompt
        entry.completion_tokens += completion

    def merge(self, other: Mapping[str, ModelUsage]) -> None:
        """Fold another meter's totals into this one."""
        for model, usage in other.items():
            self._add(model, usage.kind, usage.prompt_tokens, usage.completion_tokens)
            # _add counted one call; the merged rows may represent many.
            self._by_model[model].calls += usage.calls - 1

    @property
    def by_model(self) -> dict[str, ModelUsage]:
        """A copy, so a reader cannot quietly edit the counter it read."""
        return {model: usage.model_copy() for model, usage in self._by_model.items()}

    def calls_by_model(self, kind: Kind | None = None) -> dict[str, int]:
        """Call counts, optionally for one kind of model only.

        The eval report's "mixed models" warning is about the chat model
        falling back mid-run, and it fires on seeing more than one model. An
        embedding model in the same dict would fire it on every run.
        """
        return {
            model: usage.calls
            for model, usage in self._by_model.items()
            if kind is None or usage.kind == kind
        }

    @property
    def total_tokens(self) -> int:
        return sum(u.total_tokens for u in self._by_model.values())

    def __bool__(self) -> bool:
        return bool(self._by_model)


_active_scope: ContextVar[UsageMeter | None] = ContextVar("atlas_usage_scope", default=None)


@contextmanager
def usage_scope() -> Iterator[UsageMeter]:
    """Count everything recorded inside this block, in this task and its children.

    Nesting is allowed and the inner scope wins: only the innermost meter is
    written to, plus each provider's own. Nothing in Atlas nests today, so the
    alternative (walking a stack of scopes) would be untested machinery.
    """
    meter = UsageMeter()
    token = _active_scope.set(meter)
    try:
        yield meter
    finally:
        try:
            _active_scope.reset(token)
        except ValueError:
            # An async generator's cleanup can run in a different context
            # from the one that entered the scope — a client disconnecting
            # mid-stream does exactly that. Clearing is then the honest
            # outcome; raising here would turn an accounting detail into a
            # failed teardown on a request that already ended.
            _active_scope.set(None)


async def counted(meter: UsageMeter, awaitable: Awaitable[T]) -> T:
    """Await *awaitable* inside a scope and fold what it spent into *meter*.

    For code that has to count across a `yield` — the SSE handler is the one
    case. An async generator has no context of its own: it runs in whichever
    task resumes it, so a scope entered before a yield and left after it can
    be entered and exited in two different contexts. That is not theoretical;
    Starlette's TestClient resumes a streaming body that way, and the scope
    silently stopped applying halfway through the response.

    Scoping one await at a time never spans a yield, so it holds however the
    generator is driven.
    """
    with usage_scope() as step:
        result = await awaitable
    meter.merge(step.by_model)
    return result
