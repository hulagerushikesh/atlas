"""Tests for FaithfulnessChecker."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.llm import GenerationResponse
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.faithfulness import FaithfulnessChecker
from atlas.orchestration.generator import OUT_OF_SCOPE_MSG, REFUSAL


def _chunk(cid: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, content="Context content.", score=0.9,
        metadata=ChunkMetadata(
            doc_id="d1", source="t.md", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=15,
        ),
    )


def _llm(score: float, claims: list[dict]) -> AsyncMock:  # type: ignore[type-arg]
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=GenerationResponse(
            content=json.dumps({
                "claims": claims,
                "faithfulness_score": score,
                "summary": "test summary",
            }),
            model_used="gpt-4o-mini",
            prompt_tokens=60, completion_tokens=50, total_tokens=110,
        )
    )
    return llm


_SUPPORTED_CLAIMS = [
    {"claim": "X is true", "verdict": "supported", "evidence": "Context says X"},
]
_UNSUPPORTED_CLAIMS = [
    {"claim": "Y is true", "verdict": "unsupported", "evidence": ""},
]


class TestFaithfulnessChecker:
    @pytest.mark.asyncio
    async def test_faithful_high_score(self) -> None:
        checker = FaithfulnessChecker(_llm(0.9, _SUPPORTED_CLAIMS))
        result = await checker.check("answer text", [_chunk("c1")])
        assert result.is_faithful is True
        assert result.score == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_unfaithful_low_score(self) -> None:
        checker = FaithfulnessChecker(_llm(0.3, _UNSUPPORTED_CLAIMS))
        result = await checker.check("answer text", [_chunk("c1")])
        assert result.is_faithful is False

    @pytest.mark.asyncio
    async def test_unsupported_claims_populated(self) -> None:
        checker = FaithfulnessChecker(_llm(0.5, _UNSUPPORTED_CLAIMS))
        result = await checker.check("answer", [_chunk("c1")])
        assert "Y is true" in result.unsupported_claims

    @pytest.mark.asyncio
    async def test_disabled_reports_no_verdict_not_a_perfect_one(self) -> None:
        """
        A check that did not run has no result. Returning 1.0/True made the
        console render "Supported 1.00" — its strongest badge — for an answer
        nobody audited, which is worse than rendering nothing.
        """
        llm = AsyncMock()
        checker = FaithfulnessChecker(llm, enabled=False)
        result = await checker.check("any answer", [_chunk("c1")])
        assert result.score is None
        assert result.is_faithful is None
        llm.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unparseable_judge_is_zero_not_none(self) -> None:
        """
        The one branch that deliberately keeps a number. None means "nobody
        looked"; here somebody looked and the audit itself failed, which a
        human should triage rather than see rendered as a quiet "unchecked".
        """
        llm = AsyncMock()
        llm.generate = AsyncMock(
            return_value=GenerationResponse(
                content="not json {", model_used="gpt-4o-mini",
                prompt_tokens=10, completion_tokens=2, total_tokens=12,
            )
        )
        result = await FaithfulnessChecker(llm).check("answer", [_chunk("c1")])
        assert result.score == 0.0
        assert result.is_faithful is False

    @pytest.mark.asyncio
    async def test_judge_that_omits_the_score_does_not_score_perfect(self) -> None:
        """
        `parsed.get("faithfulness_score", 1.0)` gave a judge that skipped the
        question a perfect verdict — the same silencing as the disabled
        branch, one level in.
        """
        llm = AsyncMock()
        llm.generate = AsyncMock(
            return_value=GenerationResponse(
                content=json.dumps({"claims": [], "summary": "s"}),
                model_used="gpt-4o-mini",
                prompt_tokens=10, completion_tokens=2, total_tokens=12,
            )
        )
        result = await FaithfulnessChecker(llm).check("answer", [_chunk("c1")])
        assert result.score == 0.0
        assert result.is_faithful is False

    @pytest.mark.asyncio
    async def test_claims_parsed(self) -> None:
        checker = FaithfulnessChecker(_llm(0.8, _SUPPORTED_CLAIMS))
        result = await checker.check("answer", [_chunk("c1")])
        assert len(result.claims) == 1
        assert result.claims[0].verdict == "supported"

    @pytest.mark.asyncio
    async def test_summary_populated(self) -> None:
        checker = FaithfulnessChecker(_llm(0.9, _SUPPORTED_CLAIMS))
        result = await checker.check("answer", [_chunk("c1")])
        assert result.summary == "test summary"


class TestRefusals:
    """A refusal asserts nothing, so there is nothing to audit."""

    @pytest.mark.asyncio
    async def test_refusal_is_neither_unfaithful_nor_perfectly_supported(self) -> None:
        # Before this, the auditor read the refusal sentence as a claim, found
        # no passage supporting it, scored 0.0, and the API warned the caller
        # that the one answer that cannot be fabricated might be. The first
        # fix overshot to 1.0/True, which had the console award "Supported
        # 1.00" to an answer that said it did not know. Neither is the fact:
        # there was nothing to ground.
        checker = FaithfulnessChecker(llm=_llm(0.0, [{"claim": REFUSAL, "verdict": "unsupported"}]))
        result = await checker.check(REFUSAL, [_chunk("c1")])
        assert result.score is None
        assert result.is_faithful is None
        assert result.is_faithful is not False

    @pytest.mark.asyncio
    async def test_refusal_skips_the_llm_call(self) -> None:
        llm = _llm(0.0, [])
        await FaithfulnessChecker(llm=llm).check(REFUSAL + ".", [_chunk("c1")])
        llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_answer_that_merely_opens_with_a_caveat_is_still_audited(self) -> None:
        # "I don't have sufficient information about X, but Y" makes a claim
        # about Y. Exempting it would skip the check on exactly the answers
        # most likely to be hedged fabrication.
        llm = _llm(0.4, [{"claim": "Y is true", "verdict": "unsupported"}])
        hedged = f"{REFUSAL} about timeouts, but the retry policy is three attempts [1]."
        result = await FaithfulnessChecker(llm=llm).check(hedged, [_chunk("c1")])
        llm.generate.assert_called_once()
        assert result.score == 0.4


class TestTheCheckerSkipsTheRoutersRefusalToo:
    """Defence in depth: today the pipeline short-circuits before the checker
    on an out-of-scope route, so the checker never sees OUT_OF_SCOPE_MSG. It
    should still abstain if it ever does — the same reasoning as the refusal
    branch, and the eval metrics were caught out by exactly this gap.
    """

    @pytest.mark.asyncio
    async def test_out_of_scope_message_is_not_audited(self) -> None:
        llm = AsyncMock()
        result = await FaithfulnessChecker(llm=llm).check(OUT_OF_SCOPE_MSG, [_chunk("c1")])
        assert result.score is None
        assert result.is_faithful is None
        llm.generate.assert_not_called()
