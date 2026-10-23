"""Tests for AnswerGenerator — citation parsing and result structure."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.llm import GenerationResponse
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.generator import (
    OUT_OF_SCOPE_MSG,
    REFUSAL,
    AnswerGenerator,
    is_non_answer,
)


def _chunk(cid: str, source: str = "doc.pdf", page: int | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        content=f"Content of chunk {cid}.",
        score=0.9,
        metadata=ChunkMetadata(
            doc_id="d1", source=source, doc_type=DocumentType.PDF,
            chunk_index=0, start_char=0, end_char=20,
            page_number=page,
        ),
    )


def _llm_returning(answer: str) -> AsyncMock:
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=GenerationResponse(
            content=answer,
            model_used="gpt-4o-mini",
            prompt_tokens=50, completion_tokens=40, total_tokens=90,
        )
    )
    return llm


class TestAnswerGenerator:
    @pytest.mark.asyncio
    async def test_answer_in_result(self) -> None:
        gen = AnswerGenerator(_llm_returning("The answer is [1]."))
        result = await gen.generate("q", [_chunk("c1")])
        assert result.answer == "The answer is [1]."

    @pytest.mark.asyncio
    async def test_citation_resolved(self) -> None:
        gen = AnswerGenerator(_llm_returning("Fact from [1] and [2]."))
        result = await gen.generate("q", [_chunk("c1"), _chunk("c2")])
        assert 1 in result.citations
        assert 2 in result.citations
        assert result.citations[1].chunk_id == "c1"
        assert result.citations[2].chunk_id == "c2"

    @pytest.mark.asyncio
    async def test_out_of_range_citation_ignored(self) -> None:
        gen = AnswerGenerator(_llm_returning("See [5] for details."))
        result = await gen.generate("q", [_chunk("c1")])  # only 1 chunk
        assert 5 not in result.citations

    @pytest.mark.asyncio
    async def test_cited_chunks_populated(self) -> None:
        gen = AnswerGenerator(_llm_returning("From [1]: something true."))
        result = await gen.generate("q", [_chunk("c1"), _chunk("c2")])
        assert len(result.cited_chunks) == 1
        assert result.cited_chunks[0].chunk_id == "c1"

    @pytest.mark.asyncio
    async def test_no_citations_in_answer(self) -> None:
        gen = AnswerGenerator(_llm_returning("A claim without any citation."))
        result = await gen.generate("q", [_chunk("c1")])
        assert result.citations == {}
        assert result.cited_chunks == []

    @pytest.mark.asyncio
    async def test_page_number_in_citation_ref(self) -> None:
        gen = AnswerGenerator(_llm_returning("Fact [1]."))
        result = await gen.generate("q", [_chunk("c1", page=7)])
        assert result.citations[1].page_number == 7

    @pytest.mark.asyncio
    async def test_duplicate_citations_not_duplicated_in_cited_chunks(self) -> None:
        gen = AnswerGenerator(_llm_returning("[1] is important. Also [1]."))
        result = await gen.generate("q", [_chunk("c1")])
        assert len(result.cited_chunks) == 1


class TestThePipelineHasTwoNonAnswersAndBothMustBeRecognised:
    """The generator refuses with REFUSAL; the router refuses with
    OUT_OF_SCOPE_MSG before generation ever runs.

    Four readers skip a refusal — the inference-time faithfulness checker and
    three eval metrics — and until 2026-10-19 every one of them tested only
    the generator's string. On the first eval run where the router correctly
    refused an out-of-scope question, `answer_correctness` scored it 0.000
    with the reasoning "the pipeline answered instead of refusing",
    `answer_relevance` averaged 0.41 into the headline, and `faithfulness`
    audited the out-of-scope sentence as two supported claims and returned
    1.0. The router got better and three published numbers got worse.
    """

    def test_the_generators_refusal_is_a_non_answer(self) -> None:
        assert is_non_answer(REFUSAL)

    def test_the_pipelines_out_of_scope_message_is_a_non_answer(self) -> None:
        assert is_non_answer(OUT_OF_SCOPE_MSG)

    def test_a_real_answer_is_not(self) -> None:
        assert not is_non_answer("FastAPI validates request bodies with Pydantic [1].")

    def test_the_out_of_scope_check_is_equality_not_substring(self) -> None:
        # Same rule as is_refusal: an answer that names the scope and then
        # answers is an answer, and exempting it from every check that
        # matters is the failure this mirrors.
        hedged = f"{OUT_OF_SCOPE_MSG} That said, path parameters are declared in the path [1]."
        assert not is_non_answer(hedged)

    def test_punctuation_and_whitespace_do_not_change_the_verdict(self) -> None:
        assert is_non_answer(f"  {OUT_OF_SCOPE_MSG}  ")
        assert is_non_answer(OUT_OF_SCOPE_MSG.rstrip(".") + "!")

    def test_the_constant_is_the_one_the_pipeline_actually_emits(self) -> None:
        # The two used to be separate strings in separate modules, which is
        # how they drifted apart without anything failing. This fails if
        # either moves.
        from atlas.orchestration import pipeline

        assert pipeline.OUT_OF_SCOPE_MSG is OUT_OF_SCOPE_MSG


class TestTheReleaseDatingRuleReachesTheModel:
    """Rule 6 is the only part of the prompt a downstream artefact depends on.

    `apply_context_headers` goes out of its way to keep a release heading on
    the chunk that states a Python floor — a version-like heading survives a
    same-level sibling precisely so `## 0.104.0 (2023-10-18)` is not dropped
    from that chunk's trail. That work buys nothing unless the generator is
    told what the date in the header is for, and nothing else in the suite
    would fail if the rule were deleted: the answers would simply go back to
    stating 2023 facts in the present tense, which is what `fq-002` scored
    *contradicted* for. Pinned here so the two halves cannot drift apart.
    """

    def test_the_prompt_tells_the_model_to_date_a_release_claim(self) -> None:
        from atlas.orchestration.generator import _SYSTEM_PROMPT

        assert "release" in _SYSTEM_PROMPT.lower()
        assert "as of 0.104.0 (2023-10-18)" in _SYSTEM_PROMPT

    def test_it_does_not_ask_for_a_date_on_undated_passages(self) -> None:
        # Dating everything is the failure mode the rule has to avoid: most
        # of the corpus is tutorial prose with no release in its heading
        # trail, and a fabricated date there is a new unsupported claim for
        # the faithfulness checker to catch.
        from atlas.orchestration.generator import _SYSTEM_PROMPT

        assert "do not invent a date" in _SYSTEM_PROMPT.lower()

    def test_both_call_paths_send_the_same_system_prompt(self) -> None:
        # `generate` and `stream` build their messages separately; a rule
        # added to one and not the other is a console that dates its answers
        # and an API that does not, or the reverse.
        import inspect

        from atlas.orchestration import generator as gen

        source = inspect.getsource(gen.AnswerGenerator)
        assert source.count("content=_SYSTEM_PROMPT") == 2
