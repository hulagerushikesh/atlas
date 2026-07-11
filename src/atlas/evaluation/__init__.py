"""
Module D — Evaluation harness.

Submodules:
    metrics     — faithfulness, answer_relevance, context_precision, context_recall
    runner      — executes full pipeline over an EvalDataset, emits EvalResult
    reporter    — formats EvalResult as JSON + markdown table
    comparator  — diffs two EvalResults for A/B comparison
"""

from atlas.evaluation.comparator import ComparisonResult, MetricDelta, compare, save_comparison
from atlas.evaluation.metrics import (
    AnswerRelevanceMetric,
    BaseMetric,
    ContextPrecisionMetric,
    ContextRecallMetric,
    FaithfulnessMetric,
)
from atlas.evaluation.reporter import print_report, save_report
from atlas.evaluation.runner import EvalRunner

__all__ = [
    # Metrics
    "BaseMetric",
    "ContextPrecisionMetric",
    "ContextRecallMetric",
    "FaithfulnessMetric",
    "AnswerRelevanceMetric",
    # Runner
    "EvalRunner",
    # Reporter
    "save_report",
    "print_report",
    # Comparator
    "compare",
    "save_comparison",
    "ComparisonResult",
    "MetricDelta",
]
