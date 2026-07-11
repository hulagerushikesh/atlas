"""
Base class for all evaluation metrics.

Design rationale:
    Two fundamentally different metric families exist in RAG evaluation:

    Programmatic metrics (context_precision, context_recall) compare chunk IDs
    against a ground-truth set — O(1) computation, no LLM call needed. These
    are cheap, deterministic, and run first so failures don't waste LLM budget.

    LLM-as-judge metrics (faithfulness, answer_relevance) require a model to
    reason about semantic quality — slow, probabilistic, and expensive. They
    run after programmatic metrics and share a single LLM provider instance
    injected at construction time.

    Both families implement the same `score()` interface so the runner can
    iterate over a list[BaseMetric] without caring which type each one is.
    This is the Strategy pattern applied to evaluation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from atlas.interfaces.evaluator import MetricScore
from atlas.interfaces.retriever import RetrievedChunk


class BaseMetric(ABC):
    """Compute a single quality metric for one (sample, pipeline output) pair."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Metric identifier used in reports and comparisons."""

    @abstractmethod
    async def score(
        self,
        question: str,
        ground_truth_answer: str,
        generated_answer: str,
        retrieved_chunks: list[RetrievedChunk],
        relevant_doc_ids: list[str],
    ) -> MetricScore:
        """
        Compute and return a MetricScore for one eval sample.

        Args:
            question:             The original user question.
            ground_truth_answer:  Reference answer from the eval dataset.
            generated_answer:     Answer produced by the pipeline under test.
            retrieved_chunks:     Chunks returned by the retriever (ordered).
            relevant_doc_ids:     Gold-standard doc IDs from the eval dataset.
        """
