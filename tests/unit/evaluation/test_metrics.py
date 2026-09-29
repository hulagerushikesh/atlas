"""
Tests for all five evaluation metrics.

Programmatic metrics (precision, recall) need no mocks — pure computation.
LLM-as-judge metrics (faithfulness, answer_relevance, answer_correctness)
mock the LLM and embedder.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from atlas.evaluation.metrics import (
    AnswerCorrectnessMetric,
    AnswerRelevanceMetric,
    ContextPrecisionMetric,
    ContextRecallMetric,
    FaithfulnessMetric,
)
from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.embedder import EmbeddingResult
from atlas.interfaces.llm import GenerationResponse
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.generator import REFUSAL

# ── Helpers ───────────────────────────────────────────────────────────────────

def _chunk(cid: str, doc_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, content=f"Content from {doc_id}.", score=0.8,
        metadata=ChunkMetadata(
            doc_id=doc_id, source=f"{doc_id}.md", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=20,
        ),
    )


def _llm(content: str) -> AsyncMock:
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=GenerationResponse(
            content=content, model_used="gpt-4o-mini",
            prompt_tokens=30, completion_tokens=20, total_tokens=50,
        )
    )
    return llm


# ── ContextPrecisionMetric ────────────────────────────────────────────────────

class TestContextPrecision:
    @pytest.mark.asyncio
    async def test_all_relevant(self) -> None:
        chunks = [_chunk("c1", "d1"), _chunk("c2", "d2")]
        metric = ContextPrecisionMetric()
        ms = await metric.score("q", "a", "gen", chunks, ["d1", "d2"])
        assert ms.score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_half_relevant(self) -> None:
        chunks = [_chunk("c1", "d1"), _chunk("c2", "d_noise")]
        metric = ContextPrecisionMetric()
        ms = await metric.score("q", "a", "gen", chunks, ["d1"])
        assert ms.score == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_none_relevant(self) -> None:
        chunks = [_chunk("c1", "d_noise")]
        metric = ContextPrecisionMetric()
        ms = await metric.score("q", "a", "gen", chunks, ["d1"])
        assert ms.score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_empty_chunks(self) -> None:
        metric = ContextPrecisionMetric()
        ms = await metric.score("q", "a", "gen", [], ["d1"])
        assert ms.score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_reasoning_populated(self) -> None:
        metric = ContextPrecisionMetric()
        ms = await metric.score("q", "a", "gen", [_chunk("c1", "d1")], ["d1"])
        assert ms.reasoning != ""

    def test_metric_name(self) -> None:
        assert ContextPrecisionMetric().name == "context_precision"


# ── ContextRecallMetric ───────────────────────────────────────────────────────

class TestContextRecall:
    @pytest.mark.asyncio
    async def test_full_recall(self) -> None:
        chunks = [_chunk("c1", "d1"), _chunk("c2", "d2")]
        metric = ContextRecallMetric()
        ms = await metric.score("q", "a", "gen", chunks, ["d1", "d2"])
        assert ms.score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_partial_recall(self) -> None:
        chunks = [_chunk("c1", "d1")]
        metric = ContextRecallMetric()
        ms = await metric.score("q", "a", "gen", chunks, ["d1", "d2"])
        assert ms.score == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_zero_recall(self) -> None:
        chunks = [_chunk("c1", "d_noise")]
        metric = ContextRecallMetric()
        ms = await metric.score("q", "a", "gen", chunks, ["d1"])
        assert ms.score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_no_relevant_docs_vacuously_perfect(self) -> None:
        metric = ContextRecallMetric()
        ms = await metric.score("q", "a", "gen", [], [])
        assert ms.score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_missing_doc_in_reasoning(self) -> None:
        metric = ContextRecallMetric()
        ms = await metric.score("q", "a", "gen", [_chunk("c1", "d1")], ["d1", "d2"])
        assert "d2" in ms.reasoning

    def test_metric_name(self) -> None:
        assert ContextRecallMetric().name == "context_recall"


# ── FaithfulnessMetric ────────────────────────────────────────────────────────

class TestFaithfulnessMetric:
    @pytest.mark.asyncio
    async def test_refusal_is_excluded_not_scored_zero(self) -> None:
        # The judge used to enumerate the refusal sentence as one unsupported
        # claim and return 0.0. On the 2026-09-24 run that one sample dropped
        # the headline from 1.000 to 0.933 for declining to fabricate.
        llm = _llm(json.dumps({"claims": [], "faithfulness_score": 0.0}))
        ms = await FaithfulnessMetric(llm).score(
            "q", "a", REFUSAL, [_chunk("c1", "d1")], []
        )
        assert ms.applicable is False
        llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_real_answer_stays_applicable(self) -> None:
        payload = json.dumps({
            "claims": [{"claim": "X", "verdict": "supported"}],
            "faithfulness_score": 1.0,
        })
        ms = await FaithfulnessMetric(_llm(payload)).score(
            "q", "a", "FastAPI validates with Pydantic [1].", [_chunk("c1", "d1")], []
        )
        assert ms.applicable is True

    @pytest.mark.asyncio
    async def test_high_faithfulness(self) -> None:
        payload = json.dumps({
            "claims": [{"claim": "X", "verdict": "supported"}],
            "faithfulness_score": 1.0,
        })
        metric = FaithfulnessMetric(_llm(payload))
        ms = await metric.score("q", "a", "generated answer", [_chunk("c1", "d1")], [])
        assert ms.score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_low_faithfulness(self) -> None:
        payload = json.dumps({
            "claims": [
                {"claim": "X", "verdict": "supported"},
                {"claim": "Y", "verdict": "unsupported"},
            ],
            "faithfulness_score": 0.5,
        })
        metric = FaithfulnessMetric(_llm(payload))
        ms = await metric.score("q", "a", "answer", [_chunk("c1", "d1")], [])
        assert ms.score == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_unsupported_in_reasoning(self) -> None:
        payload = json.dumps({
            "claims": [{"claim": "Fake claim", "verdict": "unsupported"}],
            "faithfulness_score": 0.0,
        })
        metric = FaithfulnessMetric(_llm(payload))
        ms = await metric.score("q", "a", "answer", [_chunk("c1", "d1")], [])
        assert "Fake claim" in ms.reasoning

    def test_metric_name(self) -> None:
        llm = AsyncMock()
        assert FaithfulnessMetric(llm).name == "faithfulness"


# ── AnswerRelevanceMetric ─────────────────────────────────────────────────────

class TestAnswerRelevanceMetric:
    def _mock_embedder(self, vectors: list[list[float]]) -> AsyncMock:
        emb = AsyncMock()
        emb.embed_texts = AsyncMock(
            return_value=EmbeddingResult(vectors=vectors, model="mock", total_tokens=10)
        )
        return emb

    @pytest.mark.asyncio
    async def test_perfect_relevance(self) -> None:
        # Synthetic questions identical to original → cosine sim = 1.0
        payload = json.dumps({"questions": ["q", "q", "q"]})
        # All vectors identical → sim = 1.0
        vecs = [[1.0, 0.0]] * 4  # orig + 3 synthetic
        metric = AnswerRelevanceMetric(_llm(payload), self._mock_embedder(vecs))
        ms = await metric.score("q", "a", "answer", [], [])
        assert ms.score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_zero_relevance(self) -> None:
        payload = json.dumps({"questions": ["unrelated 1", "unrelated 2", "unrelated 3"]})
        # Orthogonal vectors → sim = 0.0
        vecs = [[1.0, 0.0], [0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]
        metric = AnswerRelevanceMetric(_llm(payload), self._mock_embedder(vecs))
        ms = await metric.score("q", "a", "answer", [], [])
        assert ms.score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_empty_synthetic_questions(self) -> None:
        payload = json.dumps({"questions": []})
        metric = AnswerRelevanceMetric(_llm(payload), self._mock_embedder([]))
        ms = await metric.score("q", "a", "answer", [], [])
        assert ms.score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_score_clamped_to_unit_interval(self) -> None:
        payload = json.dumps({"questions": ["q1"]})
        # Vectors that produce sim slightly > 1.0 due to float arithmetic
        vecs = [[1.0, 0.0], [1.0, 0.0]]
        metric = AnswerRelevanceMetric(_llm(payload), self._mock_embedder(vecs))
        ms = await metric.score("q", "a", "answer", [], [])
        assert 0.0 <= ms.score <= 1.0

    def test_metric_name(self) -> None:
        assert AnswerRelevanceMetric(AsyncMock(), AsyncMock()).name == "answer_relevance"


# ── Out-of-scope rows ─────────────────────────────────────────────────────────

class TestOutOfScopeSamples:
    """A row with no relevant documents cannot measure retrieval quality.

    fq-015 is such a row: the right answer is a refusal. Precision is 0.0
    however well the retriever behaves and recall is a free 1.0, so counting
    either one reports the dataset's shape as if it were the pipeline's.
    """

    @pytest.mark.asyncio
    async def test_precision_is_inapplicable_without_relevant_docs(self) -> None:
        chunks = [_chunk("c1", "d1"), _chunk("c2", "d2")]
        ms = await ContextPrecisionMetric().score("q", "a", "gen", chunks, [])
        assert ms.applicable is False
        assert ms.score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_recall_is_inapplicable_without_relevant_docs(self) -> None:
        chunks = [_chunk("c1", "d1")]
        ms = await ContextRecallMetric().score("q", "a", "gen", chunks, [])
        assert ms.applicable is False
        assert ms.score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_empty_retrieval_with_real_targets_still_counts(self) -> None:
        # Retrieving nothing when documents *do* exist is a genuine failure,
        # not an undefined measurement — it must stay in the mean.
        ms = await ContextPrecisionMetric().score("q", "a", "gen", [], ["d1"])
        assert ms.applicable is True
        assert ms.score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_normal_rows_remain_applicable(self) -> None:
        chunks = [_chunk("c1", "d1")]
        for metric in (ContextPrecisionMetric(), ContextRecallMetric()):
            ms = await metric.score("q", "a", "gen", chunks, ["d1"])
            assert ms.applicable is True


# ── AnswerCorrectnessMetric ───────────────────────────────────────────────────

def _facts(*verdicts: str) -> str:
    return json.dumps({
        "facts": [{"fact": f"fact {i}", "verdict": v} for i, v in enumerate(verdicts)]
    })


class TestAnswerCorrectnessMetric:
    """The first metric to read `ground_truth_answer`. Everything before it
    could score a grounded, on-topic, wrong answer as perfect."""

    @pytest.mark.asyncio
    async def test_all_reference_facts_present_is_one(self) -> None:
        ms = await AnswerCorrectnessMetric(
            _llm(_facts("present", "present"))
        ).score("q", "ref", "gen", [], ["d1"])
        assert ms.score == pytest.approx(1.0)
        assert ms.applicable is True

    @pytest.mark.asyncio
    async def test_a_missing_fact_costs_its_share(self) -> None:
        ms = await AnswerCorrectnessMetric(
            _llm(_facts("present", "present", "present", "missing"))
        ).score("q", "ref", "gen", [], ["d1"])
        assert ms.score == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_a_contradiction_costs_twice_an_omission(self) -> None:
        """An incomplete answer and a wrong one are different failures, and
        a metric that scored them alike would be no use for deciding whether
        a configuration is safe to ship."""
        omitted = await AnswerCorrectnessMetric(
            _llm(_facts("present", "present", "present", "missing"))
        ).score("q", "ref", "gen", [], ["d1"])
        wrong = await AnswerCorrectnessMetric(
            _llm(_facts("present", "present", "present", "contradicted"))
        ).score("q", "ref", "gen", [], ["d1"])

        assert omitted.score == pytest.approx(0.75)
        assert wrong.score == pytest.approx(0.50)

    @pytest.mark.asyncio
    async def test_score_never_goes_below_zero(self) -> None:
        ms = await AnswerCorrectnessMetric(
            _llm(_facts("contradicted", "contradicted"))
        ).score("q", "ref", "gen", [], ["d1"])
        assert ms.score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_contradicted_facts_are_named_in_the_reasoning(self) -> None:
        ms = await AnswerCorrectnessMetric(
            _llm(_facts("present", "contradicted"))
        ).score("q", "ref", "gen", [], ["d1"])
        assert "Contradicted:" in ms.reasoning
        assert "fact 1" in ms.reasoning

    @pytest.mark.asyncio
    async def test_a_refusal_on_an_answerable_row_is_wrong(self) -> None:
        """Unlike faithfulness, which has nothing to audit and abstains: a
        refusal covers none of the reference's facts, and the dataset says
        this row is answerable."""
        llm = _llm(_facts("present"))
        ms = await AnswerCorrectnessMetric(llm).score("q", "ref", REFUSAL, [], ["d1"])
        assert ms.score == pytest.approx(0.0)
        assert ms.applicable is True
        llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_refusal_on_an_out_of_scope_row_is_right(self) -> None:
        """No labels means a declared out-of-scope row. This is the only
        metric that can score the refusal path at all — precision and recall
        skip the row, faithfulness abstains, answer relevance returns noise."""
        llm = _llm(_facts("present"))
        ms = await AnswerCorrectnessMetric(llm).score("q", "ref", REFUSAL, [], [])
        assert ms.score == pytest.approx(1.0)
        assert ms.applicable is True
        llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_answering_an_out_of_scope_row_is_wrong(self) -> None:
        ms = await AnswerCorrectnessMetric(_llm(_facts("present"))).score(
            "q", "ref", "Here is a confident answer.", [], []
        )
        assert ms.score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_no_reference_answer_is_inapplicable_not_zero(self) -> None:
        """The dataset is incomplete there; that is not the pipeline's
        failure to carry into the mean."""
        ms = await AnswerCorrectnessMetric(_llm(_facts("present"))).score(
            "q", "   ", "gen", [], ["d1"]
        )
        assert ms.applicable is False

    @pytest.mark.asyncio
    async def test_a_judge_that_extracts_nothing_is_inapplicable(self) -> None:
        ms = await AnswerCorrectnessMetric(_llm(json.dumps({"facts": []}))).score(
            "q", "ref", "gen", [], ["d1"]
        )
        assert ms.applicable is False

    @pytest.mark.asyncio
    async def test_extra_correct_detail_is_not_penalised(self) -> None:
        """`fq-012`'s correct answer spans five pages where the reference
        names one. Scoring extra material as a false positive would measure
        how closely the answer matched the length of a hand-written summary."""
        metric = AnswerCorrectnessMetric(_llm(_facts("present", "present")))
        ms = await metric.score(
            "q", "Short reference.", "A much longer answer with more true detail.",
            [], ["d1"],
        )
        assert ms.score == pytest.approx(1.0)

    def test_metric_name(self) -> None:
        assert AnswerCorrectnessMetric(AsyncMock()).name == "answer_correctness"


class TestAnswerRelevanceOnRefusals:
    """Until 2026-09-29 this metric reverse-questioned the refusal sentence and
    folded the resulting noise into the mean, having paid a generation call and
    an embedding call for it. Nothing caught it because the dataset had no row
    the pipeline was supposed to refuse."""

    @pytest.mark.asyncio
    async def test_a_refusal_is_inapplicable(self) -> None:
        metric = AnswerRelevanceMetric(_llm("{}"), AsyncMock())
        ms = await metric.score("What Python version?", "3.10", REFUSAL, [], [])
        assert ms.applicable is False

    @pytest.mark.asyncio
    async def test_a_refusal_costs_no_model_call(self) -> None:
        llm, emb = _llm("{}"), AsyncMock()
        await AnswerRelevanceMetric(llm, emb).score("q", "a", REFUSAL, [], [])
        llm.generate.assert_not_awaited()
        emb.embed_texts.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_ordinary_answer_is_still_scored(self) -> None:
        # The branch must not swallow answers that merely sound uncertain.
        payload = json.dumps({"questions": ["q", "q", "q"]})
        emb = AsyncMock()
        emb.embed_texts = AsyncMock(
            return_value=EmbeddingResult(vectors=[[1.0, 0.0]] * 4, model="mock", total_tokens=10)
        )
        ms = await AnswerRelevanceMetric(_llm(payload), emb).score(
            "q", "a", "I don't have the exact number, but it is documented here [1].", [], []
        )
        assert ms.applicable is True
        assert ms.score == pytest.approx(1.0)


class TestOutOfScopeRowScoring:
    """The refusal path, end to end across the metrics that see it. Only
    `answer_correctness` produces a number; the other four abstain, which is
    why the row could not be scored at all before 2026-09-28."""

    @pytest.mark.asyncio
    async def test_correctness_rewards_a_refusal_without_a_judge(self) -> None:
        llm = _llm("{}")
        ms = await AnswerCorrectnessMetric(llm).score("q", "out of scope", REFUSAL, [], [])
        assert ms.score == 1.0
        assert ms.applicable is True
        llm.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_correctness_punishes_answering_anyway(self) -> None:
        # The failure this row exists to catch: the corpus has an adjacent
        # page, so the pipeline can produce something confident and wrong.
        llm = _llm("{}")
        ms = await AnswerCorrectnessMetric(llm).score(
            "q", "out of scope", "You verify the signature with the webhooks API [1].", [], []
        )
        assert ms.score == 0.0
        assert ms.applicable is True
        llm.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_other_four_abstain_on_the_row(self) -> None:
        emb = AsyncMock()
        precision = await ContextPrecisionMetric().score("q", "", REFUSAL, [], [])
        recall = await ContextRecallMetric().score("q", "", REFUSAL, [], [])
        faith = await FaithfulnessMetric(_llm("{}")).score("q", "", REFUSAL, [], [])
        relevance = await AnswerRelevanceMetric(_llm("{}"), emb).score("q", "", REFUSAL, [], [])
        assert [m.applicable for m in (precision, recall, faith, relevance)] == [False] * 4
