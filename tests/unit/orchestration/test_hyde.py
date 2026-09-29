"""Tests for HyDEExpander.

The expander sits in front of every search, so the cases that matter are the
ones where it is *not* supposed to change anything: a failed call, an empty
passage, a duplicated query. A feature that is off by default has to degrade
to off, not to broken.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from atlas.config import HyDEConfig
from atlas.interfaces.llm import GenerationResponse
from atlas.orchestration.hyde import HyDEExpander

PASSAGE = (
    "Use Query with Annotated to declare validation on a query parameter. "
    "min_length and max_length constrain a str, and pattern applies a regular "
    "expression."
)


def _llm(content: str = PASSAGE) -> AsyncMock:
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=GenerationResponse(
            content=content,
            model_used="gemini-3.1-flash-lite",
            prompt_tokens=80, completion_tokens=60, total_tokens=140,
        )
    )
    return llm


class TestHyDEExpander:
    @pytest.mark.asyncio
    async def test_concat_keeps_the_question_in_the_search_text(self) -> None:
        # The point of concat over the paper's replace: BM25 sees this string
        # too, and the question's own rare terms are part of what it matched
        # on before.
        expander = HyDEExpander(_llm(), HyDEConfig(mode="concat"))
        [expansion] = await expander.expand(["how do I validate a query param?"])
        assert expansion.text.startswith("how do I validate a query param?")
        assert PASSAGE in expansion.text
        assert expansion.hypothesis == PASSAGE

    @pytest.mark.asyncio
    async def test_replace_sends_the_passage_alone(self) -> None:
        expander = HyDEExpander(_llm(), HyDEConfig(mode="replace"))
        [expansion] = await expander.expand(["how do I validate a query param?"])
        assert expansion.text == PASSAGE
        assert "how do I validate" not in expansion.text

    @pytest.mark.asyncio
    async def test_the_passage_brings_vocabulary_the_question_lacks(self) -> None:
        # This is the entire mechanism being bet on for fq-012: the words the
        # answering pages use are absent from the question and present in the
        # probe.
        question = "how do I add string validation to a query parameter?"
        expander = HyDEExpander(_llm(), HyDEConfig(mode="concat"))
        [expansion] = await expander.expand([question])
        for term in ("Query", "Annotated", "min_length"):
            assert term not in question
            assert term in expansion.text

    @pytest.mark.asyncio
    async def test_a_failed_call_falls_back_to_the_query(self) -> None:
        llm = AsyncMock()
        llm.generate = AsyncMock(side_effect=RuntimeError("provider down"))
        expander = HyDEExpander(llm, HyDEConfig())
        [expansion] = await expander.expand(["q"])
        assert expansion.text == "q"
        assert expansion.hypothesis == ""

    @pytest.mark.asyncio
    async def test_an_empty_passage_falls_back_to_the_query(self) -> None:
        expander = HyDEExpander(_llm("   "), HyDEConfig())
        [expansion] = await expander.expand(["q"])
        assert expansion.text == "q"
        assert expansion.hypothesis == ""

    @pytest.mark.asyncio
    async def test_a_repeated_query_is_expanded_once(self) -> None:
        llm = _llm()
        expander = HyDEExpander(llm, HyDEConfig())
        expansions = await expander.expand(["same", "other", "same"])
        assert llm.generate.await_count == 2
        assert [e.query for e in expansions] == ["same", "other", "same"]
        assert expansions[0].text == expansions[2].text

    @pytest.mark.asyncio
    async def test_order_follows_the_queries_given(self) -> None:
        # Sub-query order decides the round-robin merge in the pipeline, so a
        # reordering here would silently reorder the context window.
        llm = AsyncMock()
        llm.generate = AsyncMock(side_effect=[
            GenerationResponse(content=f"passage {i}", model_used="m",
                               prompt_tokens=1, completion_tokens=1, total_tokens=2)
            for i in range(3)
        ])
        expander = HyDEExpander(llm, HyDEConfig(mode="replace"))
        expansions = await expander.expand(["a", "b", "c"])
        assert [e.query for e in expansions] == ["a", "b", "c"]
        assert [e.text for e in expansions] == ["passage 0", "passage 1", "passage 2"]

    @pytest.mark.asyncio
    async def test_the_probe_is_deterministic(self) -> None:
        # Sampling would make two runs of the same eval differ for a reason
        # that is not the knob under test.
        llm = _llm()
        await HyDEExpander(llm, HyDEConfig()).expand(["q"])
        request = llm.generate.await_args.args[0]
        assert request.temperature == 0.0
        assert request.json_mode is False

    @pytest.mark.asyncio
    async def test_max_tokens_is_the_configured_cap(self) -> None:
        llm = _llm()
        await HyDEExpander(llm, HyDEConfig(max_tokens=64)).expand(["q"])
        assert llm.generate.await_args.args[0].max_tokens == 64
