"""
Context Recall: what fraction of relevant documents were actually retrieved?

Definition:
    Context Recall = |{relevant_doc_ids ∩ doc_ids of retrieved chunks}| / |relevant_doc_ids|

Design rationale:
    Recall is the complement of precision — it measures coverage. A pipeline
    with perfect precision but poor recall has found only irrelevant material;
    one with perfect recall but poor precision has found everything relevant
    plus a lot of noise. Reporting both gives a complete picture.

    We compute at document granularity: a relevant document is "recalled" if
    ANY chunk from it appears in the retrieved set. This is intentionally
    generous — in practice one chunk from a long document may be sufficient
    for the generator to answer the question.

    Zero relevant_doc_ids → score=1.0 (vacuously true: nothing to recall).
    This handles questions in the eval dataset that are intentionally
    out-of-scope or have no associated documents.

    In A/B comparison (comparator.py), recall differences are the primary
    signal for evaluating retrieval_top_k changes: increasing top_k typically
    improves recall at the cost of precision. The comparator surfaces both
    delta values so this tradeoff is explicit.
"""

from __future__ import annotations

from atlas.interfaces.evaluator import MetricScore
from atlas.interfaces.retriever import RetrievedChunk
from atlas.evaluation.metrics.base import BaseMetric


class ContextRecallMetric(BaseMetric):
    """Fraction of relevant documents that appear in the retrieved set."""

    @property
    def name(self) -> str:
        return "context_recall"

    async def score(
        self,
        question: str,
        ground_truth_answer: str,
        generated_answer: str,
        retrieved_chunks: list[RetrievedChunk],
        relevant_doc_ids: list[str],
    ) -> MetricScore:
        if not relevant_doc_ids:
            return MetricScore(
                metric_name=self.name,
                score=1.0,
                reasoning="No relevant documents specified; recall is vacuously 1.0.",
            )

        retrieved_doc_ids = {c.metadata.doc_id for c in retrieved_chunks}
        relevant_set = set(relevant_doc_ids)
        recalled = relevant_set & retrieved_doc_ids
        recall = len(recalled) / len(relevant_set)

        missing = sorted(relevant_set - retrieved_doc_ids)
        return MetricScore(
            metric_name=self.name,
            score=round(recall, 4),
            reasoning=(
                f"Retrieved chunks from {len(recalled)}/{len(relevant_set)} relevant documents. "
                + (f"Missing: {missing}." if missing else "All relevant documents recalled.")
            ),
        )
