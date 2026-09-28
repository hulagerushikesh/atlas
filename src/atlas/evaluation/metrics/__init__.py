"""
Evaluation metrics — five complementary dimensions of RAG quality.

    context_precision   (programmatic) retrieved chunk relevance rate
    context_recall      (programmatic) relevant document coverage rate
    faithfulness        (LLM-as-judge) answer grounded in context
    answer_relevance    (LLM-as-judge + embeddings) answer addresses the question
    answer_correctness  (LLM-as-judge) answer agrees with the reference answer

The fifth arrived on 2026-09-28. Until then nothing read
`ground_truth_answer`, so the other four could all be perfect on an answer
that was grounded, on-topic and wrong.
"""

from atlas.evaluation.metrics.answer_correctness import AnswerCorrectnessMetric
from atlas.evaluation.metrics.answer_relevance import AnswerRelevanceMetric
from atlas.evaluation.metrics.base import BaseMetric
from atlas.evaluation.metrics.context_precision import ContextPrecisionMetric
from atlas.evaluation.metrics.context_recall import ContextRecallMetric
from atlas.evaluation.metrics.faithfulness import FaithfulnessMetric

__all__ = [
    "BaseMetric",
    "ContextPrecisionMetric",
    "ContextRecallMetric",
    "FaithfulnessMetric",
    "AnswerRelevanceMetric",
    "AnswerCorrectnessMetric",
]
