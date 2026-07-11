"""
Evaluation dataset format and metric result models.

Design rationale:
    Separating the *data contract* (EvalSample, EvalDataset) from the metric
    *computation* (in atlas.evaluation) means Module D can evolve its LLM-
    judge prompts without changing the JSON schema that CI loads from disk.

    PipelineConfig is deliberately a free-form dict of overrides rather than
    a strongly-typed class — it represents "run the default pipeline but with
    these settings changed." This lets the A/B runner vary any setting
    (reranker model, top_k, chunking strategy) without modifying code.

    MetricScore.reasoning stores the LLM judge's chain-of-thought, which is
    invaluable for debugging why a particular query got a low faithfulness
    score.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvalSample(BaseModel):
    """One row in the evaluation dataset."""

    id: str
    question: str
    ground_truth_answer: str
    relevant_doc_ids: list[str]  # used for context_recall computation
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalDataset(BaseModel):
    """Collection of evaluation samples with provenance info."""

    name: str
    description: str = ""
    samples: list[EvalSample]


class MetricScore(BaseModel):
    """Score for one metric on one sample."""

    metric_name: str
    score: float          # normalised to [0, 1]
    reasoning: str = ""   # LLM judge explanation or formula derivation


class PipelineConfig(BaseModel):
    """
    Describes one pipeline configuration for A/B comparison.

    overrides is a dict of dotted-path settings, e.g.:
        {"reranker.top_k": 10, "retrieval.top_k": 30}
    The runner merges these over the base Settings before each run.
    """

    name: str
    description: str = ""
    overrides: dict[str, Any] = Field(default_factory=dict)


class SampleResult(BaseModel):
    """Full evaluation output for one sample."""

    sample_id: str
    question: str
    generated_answer: str
    retrieved_chunk_ids: list[str]
    metrics: list[MetricScore]


class EvalResult(BaseModel):
    """Aggregated results for one pipeline run over the full eval set."""

    pipeline_config: PipelineConfig
    sample_results: list[SampleResult]
    aggregate_scores: dict[str, float]  # metric_name → mean score
    total_tokens_used: int = 0
    duration_seconds: float = 0.0
