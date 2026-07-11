"""
Context Precision: what fraction of retrieved chunks came from relevant documents?

Definition:
    Context Precision @ k = |{retrieved chunks whose doc_id ∈ relevant_doc_ids}| / k

    where k = number of retrieved chunks.

Design rationale:
    This is a precision metric: it measures retrieval specificity. A pipeline
    that returns 5 chunks all from relevant documents scores 1.0. One that
    returns 5 chunks with only 2 from relevant documents scores 0.4.

    We compute it purely from chunk metadata — no LLM call needed. This makes
    it the cheapest and most reproducible metric in the harness.

    Doc-ID matching rather than chunk-ID matching: the eval dataset specifies
    relevant_doc_ids (document-level), not individual chunk IDs. This is more
    practical to annotate (a human can label "this document is relevant"
    without enumerating every chunk), and it's the standard in BEIR benchmarks.

    Weighted variant (AP@k, Average Precision): sum over positions where a
    relevant chunk appears, weighted by rank. We implement the simpler P@k
    here because it's what most interviews expect, and because the reranker
    already handles ordering — AP@k would penalise good chunks ranked below
    bad ones, double-counting the reranker's job.
"""

from __future__ import annotations

from atlas.interfaces.evaluator import MetricScore
from atlas.interfaces.retriever import RetrievedChunk
from atlas.evaluation.metrics.base import BaseMetric


class ContextPrecisionMetric(BaseMetric):
    """Fraction of retrieved chunks whose parent document is relevant."""

    @property
    def name(self) -> str:
        return "context_precision"

    async def score(
        self,
        question: str,
        ground_truth_answer: str,
        generated_answer: str,
        retrieved_chunks: list[RetrievedChunk],
        relevant_doc_ids: list[str],
    ) -> MetricScore:
        if not retrieved_chunks:
            return MetricScore(
                metric_name=self.name,
                score=0.0,
                reasoning="No chunks were retrieved.",
            )

        relevant_set = set(relevant_doc_ids)
        hits = sum(
            1 for c in retrieved_chunks if c.metadata.doc_id in relevant_set
        )
        precision = hits / len(retrieved_chunks)

        return MetricScore(
            metric_name=self.name,
            score=round(precision, 4),
            reasoning=(
                f"{hits}/{len(retrieved_chunks)} retrieved chunks came from "
                f"relevant documents (relevant doc IDs: {sorted(relevant_set)})."
            ),
        )
