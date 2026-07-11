"""
Evaluation metrics — four complementary dimensions of RAG quality.

    context_precision   (programmatic) retrieved chunk relevance rate
    context_recall      (programmatic) relevant document coverage rate
    faithfulness        (LLM-as-judge) answer grounded in context
    answer_relevance    (LLM-as-judge + embeddings) answer addresses the question
"""

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
]
