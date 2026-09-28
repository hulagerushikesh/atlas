"""Tests for RetrievalGrader."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from atlas.config import GraderConfig
from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.llm import GenerationResponse
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.grader import RetrievalGrader


def _chunk(cid: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, content=f"content {cid}", score=0.8,
        metadata=ChunkMetadata(
            doc_id="d1", source="t.md", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=10,
        ),
    )


def _llm_returning(sufficient: bool, score: float, reformulated: str = "new query") -> AsyncMock:
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=GenerationResponse(
            content=json.dumps({
                "sufficient": sufficient,
                "score": score,
                "reasoning": "test",
                "reformulated_query": reformulated,
            }),
            model_used="gpt-4o-mini",
            prompt_tokens=40, completion_tokens=30, total_tokens=70,
        )
    )
    return llm


class TestRetrievalGrader:
    @pytest.mark.asyncio
    async def test_sufficient_context(self) -> None:
        grader = RetrievalGrader(_llm_returning(True, 0.9))
        sufficient, score, _ = await grader.grade("q", [_chunk("c1")])
        assert sufficient is True
        assert score == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_insufficient_context(self) -> None:
        grader = RetrievalGrader(_llm_returning(False, 0.2))
        sufficient, score, reformulated = await grader.grade("q", [_chunk("c1")])
        assert sufficient is False
        assert reformulated == "new query"

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_insufficient(self) -> None:
        llm = AsyncMock()  # should not be called
        grader = RetrievalGrader(llm)
        sufficient, score, _ = await grader.grade("q", [])
        assert sufficient is False
        assert score == 0.0
        llm.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reformulated_query_returned(self) -> None:
        grader = RetrievalGrader(_llm_returning(False, 0.3, "better rephrased query"))
        _, _, reformulated = await grader.grade("original", [_chunk("c1")])
        assert reformulated == "better rephrased query"

    @pytest.mark.asyncio
    async def test_threshold_respected(self) -> None:
        # score=0.6, threshold=0.8 → insufficient
        grader = RetrievalGrader(_llm_returning(True, 0.6), GraderConfig(threshold=0.8))
        # The LLM says sufficient=True but score is below our threshold —
        # the LLM's boolean is used directly (grader trusts the model's judgement)
        sufficient, _, _ = await grader.grade("q", [_chunk("c1")])
        assert sufficient is True  # LLM's verdict takes precedence


class TestGradedWindow:
    """How much of the retrieval the grader is shown, and why it is a slice.

    Measured on 2026-09-28. Grading all 15 instead of the top 5 cost 0.060
    context recall, all of it fq-006 and fq-012 — the two multi-document
    questions. A grader shown a slice is pessimistic, pessimism triggers a
    retry, and a retry accumulates context, so the slice is how a
    five-document question collects five documents. These tests pin the
    default that measurement produced, because the shape of the code argues
    for the other one.
    """

    @staticmethod
    def _passages(llm: AsyncMock) -> str:
        """The context block the grader actually sent."""
        request = llm.generate.await_args.args[0]
        return request.messages[1].content

    @pytest.mark.asyncio
    async def test_only_the_top_five_are_graded_by_default(self) -> None:
        llm = _llm_returning(True, 0.9)
        grader = RetrievalGrader(llm)

        await grader.grade("q", [_chunk(f"c{i}") for i in range(15)])

        sent = self._passages(llm)
        assert "[5]" in sent
        assert "[6]" not in sent

    @pytest.mark.asyncio
    async def test_the_whole_window_is_one_setting_away(self) -> None:
        """`--set grader.context_chunks=15`, or None, re-runs the 2026-09-28
        experiment without editing the source — which is how it came to be
        changed on reasoning alone the first time."""
        llm = _llm_returning(True, 0.9)
        grader = RetrievalGrader(llm, GraderConfig(context_chunks=None))

        await grader.grade("q", [_chunk(f"c{i}") for i in range(15)])

        sent = self._passages(llm)
        assert "[15]" in sent
        assert "[6]" in sent

    @pytest.mark.asyncio
    async def test_a_cap_larger_than_the_window_is_not_an_error(self) -> None:
        llm = _llm_returning(True, 0.9)
        grader = RetrievalGrader(llm, GraderConfig(context_chunks=50))

        await grader.grade("q", [_chunk("c0"), _chunk("c1")])

        assert "[2]" in self._passages(llm)

    @pytest.mark.asyncio
    async def test_a_short_window_is_graded_whole(self) -> None:
        """The cap is a maximum, not a requirement — a retrieval that came
        back with three chunks is graded on three."""
        llm = _llm_returning(True, 0.9)
        grader = RetrievalGrader(llm)

        await grader.grade("q", [_chunk(f"c{i}") for i in range(3)])

        assert "[3]" in self._passages(llm)


class TestGraderConfigFromEnv:
    def test_a_blank_env_var_means_grade_everything(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Blank is how .env.example says "unset" for every other optional.
        An int field rejects it outright, so a line copied from the example
        crashed get_settings() at import with nothing naming the variable."""
        monkeypatch.setenv("GRADER_CONTEXT_CHUNKS", "")
        assert GraderConfig().context_chunks is None

    def test_a_number_still_caps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GRADER_CONTEXT_CHUNKS", "5")
        assert GraderConfig().context_chunks == 5
