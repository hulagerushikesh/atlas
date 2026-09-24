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
from typing import Any

import structlog

from atlas.evaluation.metrics.base import BaseMetric
from atlas.interfaces.evaluator import (
    EvalDataset,
    EvalResult,
    MetricScore,
    PipelineConfig,
    SampleResult,
)
from atlas.interfaces.retriever import RetrievedChunk

logger = structlog.get_logger(__name__)

_FAILED_SENTINEL = -1.0   # score value for a sample that errored


def _find_providers(pipeline: object, metrics: list[BaseMetric]) -> list[Any]:
    """Every distinct LLM provider reachable from the pipeline and the judges.

    Deduplicated by identity, because the pipeline's stages usually share one
    provider and counting it once per stage would report six times the calls.
    """
    found: list[Any] = []
    seen: set[int] = set()

    def walk(obj: object, depth: int) -> None:
        # Depth 2 reaches a judge's own provider (metric._llm) and a pipeline
        # stage's (pipeline._generator._llm). Deeper would start walking into
        # the OpenAI client itself for nothing.
        if depth < 0 or not hasattr(obj, "__dict__"):
            return
        for attr in vars(obj).values():
            # isinstance, not hasattr: a Mock answers hasattr for every name,
            # so attribute-presence duck-typing matched every test double and
            # then tried to iterate a coroutine.
            if isinstance(getattr(attr, "model_calls", None), dict):
                if id(attr) not in seen:
                    seen.add(id(attr))
                    found.append(attr)
            else:
                walk(attr, depth - 1)

    for holder in [pipeline, *metrics]:
        walk(holder, 2)
    return found


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
        # Providers are found by duck-type rather than passed in: the pipeline
        # and each judge may share one instance or hold their own, and the
        # runner should not have to know which.
        self._providers = _find_providers(pipeline, metrics)

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
                if ms.metric_name == metric.name
                and ms.score != _FAILED_SENTINEL
                and ms.applicable
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
            model_calls=self._model_calls(),
        )

    def _model_calls(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for provider in self._providers:
            for model, n in provider.model_calls.items():
                totals[model] = totals.get(model, 0) + n
        return totals

    async def _score_sample(self, sample: object) -> SampleResult:
        async with self._sem:
            try:
                result = await self._pipeline.run(sample.question)  # type: ignore[attr-defined]
                chunks: list[RetrievedChunk] = result.retrieved_chunks
                answer: str = result.answer

                metric_scores: list[MetricScore] = []
                for metric in self._metrics:
                    try:
                        ms = await metric.score(
                            question=sample.question,  # type: ignore[attr-defined]
                            ground_truth_answer=sample.ground_truth_answer,  # type: ignore[attr-defined]
                            generated_answer=answer,
                            retrieved_chunks=chunks,
                            relevant_doc_ids=sample.relevant_doc_ids,  # type: ignore[attr-defined]
                        )
                    except Exception as exc:
                        # One judge failing must not erase the programmatic
                        # metrics for this sample.
                        logger.error(
                            "eval_metric_failed",
                            sample_id=getattr(sample, "id", "?"),
                            metric=metric.name,
                            error=str(exc),
                        )
                        ms = MetricScore(
                            metric_name=metric.name, score=_FAILED_SENTINEL, reasoning=str(exc)
                        )
                    metric_scores.append(ms)

                sr = SampleResult(
                    sample_id=sample.id,  # type: ignore[attr-defined]
                    question=sample.question,  # type: ignore[attr-defined]
                    generated_answer=answer,
                    retrieved_chunk_ids=[c.chunk_id for c in chunks],
                    metrics=metric_scores,
                    stage_ms=dict(getattr(result, "stage_ms", {}) or {}),
                )
                # Stash token count as a private attr for aggregation above
                gen = getattr(result, "generation", None)
                sr._tokens_used = (  # type: ignore[attr-defined]
                    (gen.prompt_tokens + gen.completion_tokens) if gen else 0
                )
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
