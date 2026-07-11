"""
Tests for EvalRunner — verifies orchestration, aggregation, and fault isolation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.evaluator import EvalDataset, EvalSample, MetricScore, PipelineConfig
from atlas.interfaces.retriever import RetrievedChunk
from atlas.evaluation.runner import EvalRunner, _FAILED_SENTINEL


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
    async def test_aggregate_scores_computed(self, dataset: EvalDataset, config: PipelineConfig) -> None:
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
