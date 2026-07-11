"""Tests for QueryDecomposer."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from atlas.interfaces.llm import GenerationResponse
from atlas.orchestration.decomposer import QueryDecomposer


def _llm_returning(sub_queries: list[str]) -> AsyncMock:
    import json
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=GenerationResponse(
            content=json.dumps({"sub_queries": sub_queries}),
            model_used="gpt-4o-mini",
            prompt_tokens=30, completion_tokens=20, total_tokens=50,
        )
    )
    return llm


class TestQueryDecomposer:
    @pytest.mark.asyncio
    async def test_returns_sub_queries(self) -> None:
        decomposer = QueryDecomposer(_llm_returning(["q1", "q2"]))
        result = await decomposer.decompose("complex multi-part question")
        assert result == ["q1", "q2"]

    @pytest.mark.asyncio
    async def test_caps_at_four(self) -> None:
        decomposer = QueryDecomposer(_llm_returning(["q1", "q2", "q3", "q4", "q5"]))
        result = await decomposer.decompose("very complex question")
        assert len(result) <= 4

    @pytest.mark.asyncio
    async def test_fallback_on_single_sub_query(self) -> None:
        # Only one sub-query → treat as fallback (return original)
        decomposer = QueryDecomposer(_llm_returning(["only one"]))
        result = await decomposer.decompose("original query")
        assert result == ["original query"]

    @pytest.mark.asyncio
    async def test_fallback_on_empty(self) -> None:
        decomposer = QueryDecomposer(_llm_returning([]))
        result = await decomposer.decompose("original")
        assert result == ["original"]

    @pytest.mark.asyncio
    async def test_llm_called_with_json_mode(self) -> None:
        llm = _llm_returning(["a", "b"])
        decomposer = QueryDecomposer(llm)
        await decomposer.decompose("q")
        req = llm.generate.call_args[0][0]
        assert req.json_mode is True
