"""
Tests for EvalRunner — verifies orchestration, aggregation, and fault isolation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from atlas.evaluation.runner import _FAILED_SENTINEL, EvalRunner
from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.evaluator import (
    EvalDataset,
    EvalSample,
    MetricScore,
    PipelineConfig,
    SampleResult,
)
from atlas.interfaces.retriever import RetrievedChunk
from atlas.usage import UsageMeter


def _chunk(cid: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, content="text", score=0.8,
        metadata=ChunkMetadata(
            doc_id="d1", source="t.md", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=4,
        ),
    )


def _sample(sid: str, question: str = "What is X?") -> EvalSample:
    return EvalSample(
        id=sid, question=question,
        ground_truth_answer="X is Y.",
        relevant_doc_ids=["d1"],
    )


def _mock_pipeline(answer: str = "X is Y [1].", chunks: list | None = None) -> MagicMock:
    pipeline = MagicMock()
    result = MagicMock()
    result.answer = answer
    result.retrieved_chunks = chunks or [_chunk("c1")]
    pipeline.run = AsyncMock(return_value=result)
    return pipeline


def _mock_metric(name: str, score: float) -> MagicMock:
    m = MagicMock()
    m.name = name
    m.score = AsyncMock(
        return_value=MetricScore(metric_name=name, score=score, reasoning="ok")
    )
    return m


@pytest.fixture
def dataset() -> EvalDataset:
    return EvalDataset(
        name="test",
        samples=[_sample("s1"), _sample("s2"), _sample("s3")],
    )


@pytest.fixture
def config() -> PipelineConfig:
    return PipelineConfig(name="baseline")


class TestEvalRunner:
    @pytest.mark.asyncio
    async def test_returns_eval_result(self, dataset: EvalDataset, config: PipelineConfig) -> None:
        runner = EvalRunner(_mock_pipeline(), [_mock_metric("context_precision", 0.8)])
        result = await runner.run(dataset, config)
        assert result.pipeline_config.name == "baseline"
        assert len(result.sample_results) == 3

    @pytest.mark.asyncio
    async def test_aggregate_scores_computed(
        self, dataset: EvalDataset, config: PipelineConfig
    ) -> None:
        runner = EvalRunner(
            _mock_pipeline(),
            [_mock_metric("context_precision", 0.8), _mock_metric("faithfulness", 0.9)],
        )
        result = await runner.run(dataset, config)
        assert result.aggregate_scores["context_precision"] == pytest.approx(0.8)
        assert result.aggregate_scores["faithfulness"] == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_all_metrics_called_per_sample(
        self, dataset: EvalDataset, config: PipelineConfig
    ) -> None:
        m1 = _mock_metric("context_precision", 0.5)
        m2 = _mock_metric("faithfulness", 0.7)
        runner = EvalRunner(_mock_pipeline(), [m1, m2])
        await runner.run(dataset, config)
        # 3 samples × 1 call each
        assert m1.score.await_count == 3
        assert m2.score.await_count == 3

    @pytest.mark.asyncio
    async def test_fault_isolation_on_pipeline_error(
        self, config: PipelineConfig
    ) -> None:
        """One failing sample must not abort the run; other samples succeed."""
        pipeline = MagicMock()
        call_count = 0

        async def run_side_effect(question: str) -> object:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("transient error")
            result = MagicMock()
            result.answer = "answer"
            result.retrieved_chunks = [_chunk("c1")]
            return result

        pipeline.run = run_side_effect
        dataset = EvalDataset(
            name="test", samples=[_sample("s1"), _sample("s2"), _sample("s3")]
        )
        runner = EvalRunner(pipeline, [_mock_metric("context_precision", 0.8)])
        result = await runner.run(dataset, config)

        assert len(result.sample_results) == 3
        failed = [sr for sr in result.sample_results if any(
            m.score == _FAILED_SENTINEL for m in sr.metrics
        )]
        assert len(failed) == 1

    @pytest.mark.asyncio
    async def test_aggregate_excludes_failed_samples(
        self, config: PipelineConfig
    ) -> None:
        pipeline = MagicMock()
        call_count = 0

        async def run_side_effect(question: str) -> object:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("error")
            r = MagicMock()
            r.answer = "a"
            r.retrieved_chunks = [_chunk("c1")]
            return r

        pipeline.run = run_side_effect
        dataset = EvalDataset(
            name="test", samples=[_sample("s1"), _sample("s2")]
        )
        runner = EvalRunner(pipeline, [_mock_metric("context_precision", 1.0)])
        result = await runner.run(dataset, config)
        # Aggregate should be 1.0 (only the successful sample counts)
        assert result.aggregate_scores["context_precision"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_duration_recorded(self, dataset: EvalDataset, config: PipelineConfig) -> None:
        runner = EvalRunner(_mock_pipeline(), [_mock_metric("cp", 0.5)])
        result = await runner.run(dataset, config)
        assert result.duration_seconds >= 0


class TestTokenAccounting:
    """What the report says a run spent.

    Until 2026-09-28 this was `result.generation`'s two counts and nothing
    else, so the router, decomposer, grader, faithfulness checker, both
    judges and every embedding were missing from a field being read as the
    run's cost. The runner now counts a scope, so anything that records —
    wherever it sits in the object graph — is included.
    """

    @staticmethod
    def _spending_pipeline(prompt: int, completion: int) -> MagicMock:
        """A pipeline that bills like a real one: a provider recording into
        whatever scope happens to be active."""
        provider = UsageMeter()
        pipeline = MagicMock()

        async def run(question: str) -> object:
            provider.record("chat-1", prompt_tokens=prompt, completion_tokens=completion)
            provider.record("embed-1", kind="embedding", prompt_tokens=8)
            r = MagicMock()
            r.answer = "a"
            r.retrieved_chunks = [_chunk("c1")]
            return r

        pipeline.run = run
        return pipeline

    @pytest.mark.asyncio
    async def test_counts_every_model_not_just_generation(
        self, dataset: EvalDataset, config: PipelineConfig
    ) -> None:
        runner = EvalRunner(self._spending_pipeline(100, 10), [_mock_metric("cp", 0.5)])
        result = await runner.run(dataset, config)

        assert result.token_usage["chat-1"].calls == 3        # one per sample
        assert result.token_usage["chat-1"].prompt_tokens == 300
        assert result.token_usage["embed-1"].kind == "embedding"
        assert result.total_tokens_used == 3 * (100 + 10) + 3 * 8

    @pytest.mark.asyncio
    async def test_judges_are_counted_too(
        self, dataset: EvalDataset, config: PipelineConfig
    ) -> None:
        """A judge holds its own provider. The old walk found it only if it
        sat within two attributes of the metric; a scope does not care."""
        judge_provider = UsageMeter()
        metric = _mock_metric("cp", 0.5)

        async def score(**kwargs: object) -> MetricScore:
            judge_provider.record("chat-1", prompt_tokens=40, completion_tokens=4)
            return MetricScore(metric_name="cp", score=0.5, reasoning="ok")

        metric.score = score
        runner = EvalRunner(self._spending_pipeline(100, 10), [metric])
        result = await runner.run(dataset, config)

        assert result.token_usage["chat-1"].prompt_tokens == 3 * (100 + 40)

    @pytest.mark.asyncio
    async def test_model_calls_excludes_the_embedding_model(
        self, dataset: EvalDataset, config: PipelineConfig
    ) -> None:
        """`model_calls` drives the report's mixed-model warning, which fires
        on a second model. The embedding model must not trip it."""
        runner = EvalRunner(self._spending_pipeline(100, 10), [_mock_metric("cp", 0.5)])
        result = await runner.run(dataset, config)

        assert result.model_calls == {"chat-1": 3}

    @pytest.mark.asyncio
    async def test_only_this_runs_calls_are_counted(
        self, dataset: EvalDataset, config: PipelineConfig
    ) -> None:
        """A provider shared with something outside the run keeps its own
        lifetime total; the report must carry this run's."""
        pipeline = self._spending_pipeline(100, 10)
        outside = UsageMeter()
        outside.record("chat-1", prompt_tokens=100_000)

        runner = EvalRunner(pipeline, [_mock_metric("cp", 0.5)])
        result = await runner.run(dataset, config)

        assert result.token_usage["chat-1"].prompt_tokens == 300


class TestWhatOneQueryCost:
    """Run-wide usage cannot answer "what does a production query cost?".

    It includes the judges -- roughly 7.8 chat calls a sample against
    production's ~4 -- so dividing it by sample count overstates a real query
    by whatever the judges happened to spend. That is why cost per query was
    hand-checked rather than read off a report. `SampleResult.token_usage`
    carries the pipeline's own calls and nothing else.
    """

    @staticmethod
    def _pipeline_and_judge(metric_name: str = "cp") -> tuple[MagicMock, MagicMock]:
        """A pipeline and a judge that bill from separate providers."""
        pipeline_provider = UsageMeter()
        judge_provider = UsageMeter()
        pipeline = MagicMock()

        async def run(question: str) -> object:
            pipeline_provider.record("chat-1", prompt_tokens=100, completion_tokens=10)
            r = MagicMock()
            r.answer = "a"
            r.retrieved_chunks = [_chunk("c1")]
            r.stage_ms = {}
            return r

        pipeline.run = run

        metric = _mock_metric(metric_name, 0.5)

        async def score(**kwargs: object) -> MetricScore:
            judge_provider.record("chat-1", prompt_tokens=40, completion_tokens=4)
            return MetricScore(metric_name=metric_name, score=0.5, reasoning="ok")

        metric.score = score
        return pipeline, metric

    @pytest.mark.asyncio
    async def test_a_sample_carries_only_the_pipelines_spend(
        self, dataset: EvalDataset, config: PipelineConfig
    ) -> None:
        pipeline, metric = self._pipeline_and_judge()
        result = await EvalRunner(pipeline, [metric]).run(dataset, config)

        for sr in result.sample_results:
            assert sr.token_usage["chat-1"].prompt_tokens == 100
            assert sr.token_usage["chat-1"].completion_tokens == 10
            assert sr.pipeline_tokens == 110
            # The judge spent 44 more against the same model name. If it
            # leaked in, this would read 140/14.
            assert sr.token_usage["chat-1"].calls == 1

    @pytest.mark.asyncio
    async def test_the_run_total_still_counts_both(
        self, dataset: EvalDataset, config: PipelineConfig
    ) -> None:
        """The nested scope takes the pipeline's calls off the run meter;
        merging them back is what keeps this true. Without the merge this
        would read 3 * 44 and the run would look two thirds cheaper."""
        pipeline, metric = self._pipeline_and_judge()
        result = await EvalRunner(pipeline, [metric]).run(dataset, config)

        assert result.token_usage["chat-1"].prompt_tokens == 3 * (100 + 40)
        assert result.token_usage["chat-1"].calls == 3 * 2
        assert result.total_tokens_used == 3 * (110 + 44)

    @pytest.mark.asyncio
    async def test_the_judges_share_is_the_difference(
        self, dataset: EvalDataset, config: PipelineConfig
    ) -> None:
        """The point of the split: run minus samples is what measuring cost."""
        pipeline, metric = self._pipeline_and_judge()
        result = await EvalRunner(pipeline, [metric]).run(dataset, config)

        pipeline_total = sum(sr.pipeline_tokens for sr in result.sample_results)
        assert pipeline_total == 3 * 110
        assert result.total_tokens_used - pipeline_total == 3 * 44

    @pytest.mark.asyncio
    async def test_a_failed_sample_still_reports_what_it_spent(
        self, dataset: EvalDataset, config: PipelineConfig
    ) -> None:
        """Reporting zero would make a run that died halfway look cheap."""
        provider = UsageMeter()
        pipeline = MagicMock()

        async def run(question: str) -> object:
            provider.record("chat-1", prompt_tokens=100, completion_tokens=10)
            raise RuntimeError("qdrant went away")

        pipeline.run = run
        result = await EvalRunner(pipeline, [_mock_metric("cp", 0.5)]).run(dataset, config)

        for sr in result.sample_results:
            assert sr.generated_answer.startswith("[ERROR:")
            assert sr.pipeline_tokens == 110
        assert result.total_tokens_used == 3 * 110

    @pytest.mark.asyncio
    async def test_an_old_report_reads_as_not_measured_not_as_zero(self) -> None:
        """Every report on disk predates this field. `{}` is how a reader
        tells "nothing recorded" from "a query that cost nothing"."""
        sr = SampleResult(
            sample_id="s1",
            question="q",
            generated_answer="a",
            retrieved_chunk_ids=[],
            metrics=[],
        )
        assert sr.token_usage == {}
        assert sr.pipeline_tokens == 0
