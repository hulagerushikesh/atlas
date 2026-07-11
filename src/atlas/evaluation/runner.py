"""
Evaluation runner: execute the full RAG pipeline over an EvalDataset.

Design rationale:
    The runner is the bridge between the eval dataset (static JSON) and the
    live pipeline (Module C + Module B). It runs each sample through the
    pipeline, scores the output on all metrics, and assembles an EvalResult.

    Concurrency: samples are run with bounded concurrency (default 4) so the
    runner doesn't simultaneously issue dozens of LLM + retrieval requests —
    that would saturate rate limits and produce misleading latency measurements.
    asyncio.Semaphore provides the bound without spawning threads.

    Fault isolation: a single-sample failure (network error, LLM timeout)
    should not abort the entire run. We catch per-sample exceptions, log them,
    and record score=-1.0 as a sentinel so the reporter can flag failed samples
    rather than silently dropping them. This matters for long (30+ sample) runs
    where a retry would be expensive.

    Token tracking: the runner accumulates total_tokens_used across all pipeline
    runs. This is surfaced in EvalResult so you can estimate the dollar cost of
    one full eval pass — important for deciding how often to run evals in CI.

    Timing: wall-clock duration of the full run is recorded in EvalResult.
    Combined with per-metric scores this lets you reason about the
    quality-latency tradeoff of different configurations.
"""

from __future__ import annotations

import asyncio
import time
from statistics import mean

import structlog

from atlas.interfaces.evaluator import EvalDataset, EvalResult, MetricScore, PipelineConfig, SampleResult
from atlas.interfaces.retriever import RetrievedChunk
from atlas.evaluation.metrics.base import BaseMetric

logger = structlog.get_logger(__name__)

_FAILED_SENTINEL = -1.0   # score value for a sample that errored


class EvalRunner:
    """Run a retrieval pipeline over an EvalDataset and score the results."""

    def __init__(
        self,
        pipeline: object,          # RAGPipeline duck-type: has async run(query) → PipelineResult
        metrics: list[BaseMetric],
        concurrency: int = 4,
    ) -> None:
        self._pipeline = pipeline
        self._metrics = metrics
        self._sem = asyncio.Semaphore(concurrency)

    async def run(
        self,
        dataset: EvalDataset,
        config: PipelineConfig,
    ) -> EvalResult:
        """
        Run the pipeline over every sample in *dataset* and return a scored report.

        Args:
            dataset: Eval samples with ground-truth answers and relevant doc IDs.
            config:  Metadata describing this pipeline configuration (for the report).
        """
        start = time.monotonic()
        logger.info("eval_run_start", dataset=dataset.name, samples=len(dataset.samples))

        tasks = [self._score_sample(s) for s in dataset.samples]
        sample_results: list[SampleResult] = await asyncio.gather(*tasks)

        # Aggregate: mean score per metric, ignoring failed samples
        aggregate: dict[str, float] = {}
        for metric in self._metrics:
            valid_scores = [
                ms.score
                for sr in sample_results
                for ms in sr.metrics
                if ms.metric_name == metric.name and ms.score != _FAILED_SENTINEL
            ]
            aggregate[metric.name] = round(mean(valid_scores), 4) if valid_scores else 0.0

        total_tokens = sum(
            getattr(sr, "_tokens_used", 0) for sr in sample_results
        )
        duration = round(time.monotonic() - start, 2)

        logger.info(
            "eval_run_complete",
            samples=len(sample_results),
            duration_s=duration,
            aggregate=aggregate,
        )
        return EvalResult(
            pipeline_config=config,
            sample_results=sample_results,
            aggregate_scores=aggregate,
            total_tokens_used=total_tokens,
            duration_seconds=duration,
        )

    async def _score_sample(self, sample: object) -> SampleResult:  # type: ignore[override]
        async with self._sem:
            try:
                result = await self._pipeline.run(sample.question)  # type: ignore[attr-defined]
                chunks: list[RetrievedChunk] = result.retrieved_chunks
                answer: str = result.answer

                metric_scores: list[MetricScore] = []
                for metric in self._metrics:
                    ms = await metric.score(
                        question=sample.question,  # type: ignore[attr-defined]
                        ground_truth_answer=sample.ground_truth_answer,  # type: ignore[attr-defined]
                        generated_answer=answer,
                        retrieved_chunks=chunks,
                        relevant_doc_ids=sample.relevant_doc_ids,  # type: ignore[attr-defined]
                    )
                    metric_scores.append(ms)

                sr = SampleResult(
                    sample_id=sample.id,  # type: ignore[attr-defined]
                    question=sample.question,  # type: ignore[attr-defined]
                    generated_answer=answer,
                    retrieved_chunk_ids=[c.chunk_id for c in chunks],
                    metrics=metric_scores,
                )
                # Stash token count as a private attr for aggregation above
                sr._tokens_used = getattr(result, "total_tokens", 0)  # type: ignore[attr-defined]
                return sr

            except Exception as exc:
                logger.error(
                    "eval_sample_failed",
                    sample_id=getattr(sample, "id", "?"),
                    error=str(exc),
                )
                return SampleResult(
                    sample_id=getattr(sample, "id", "unknown"),
                    question=getattr(sample, "question", ""),
                    generated_answer=f"[ERROR: {exc}]",
                    retrieved_chunk_ids=[],
                    metrics=[
                        MetricScore(metric_name=m.name, score=_FAILED_SENTINEL, reasoning=str(exc))
                        for m in self._metrics
                    ],
                )
