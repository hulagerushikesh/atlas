"""Tests for QueryRouter — mocks the LLM, tests classification logic."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from atlas.interfaces.llm import GenerationResponse
from atlas.orchestration.router import QueryRouter


def _mock_llm(classification: str) -> AsyncMock:
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=GenerationResponse(
            content=f'{{"classification": "{classification}", "reasoning": "test"}}',
            model_used="gpt-4o-mini",
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30,
        )
    )
    return llm


class TestQueryRouter:
    @pytest.mark.asyncio
    async def test_classifies_simple(self) -> None:
        router = QueryRouter(_mock_llm("simple"))
        result = await router.classify("What is the refund policy?")
        assert result == "simple"

    @pytest.mark.asyncio
    async def test_classifies_complex(self) -> None:
        router = QueryRouter(_mock_llm("complex"))
        result = await router.classify("Compare Q3 and Q4 revenue and explain the delta.")
        assert result == "complex"

    @pytest.mark.asyncio
    async def test_classifies_out_of_scope(self) -> None:
        router = QueryRouter(_mock_llm("out_of_scope"))
        result = await router.classify("Write me a sorting algorithm in Python.")
        assert result == "out_of_scope"

    @pytest.mark.asyncio
    async def test_llm_called_once(self) -> None:
        llm = _mock_llm("simple")
        router = QueryRouter(llm)
        await router.classify("any query")
        llm.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_classification_defaults_to_simple(self) -> None:
        llm = AsyncMock()
        llm.generate = AsyncMock(
            return_value=GenerationResponse(
                content='{"reasoning": "no classification key"}',
                model_used="gpt-4o-mini",
                prompt_tokens=10, completion_tokens=5, total_tokens=15,
            )
        )
        router = QueryRouter(llm)
        result = await router.classify("some query")
        assert result == "simple"
