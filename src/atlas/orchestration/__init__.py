"""
Module C — Agentic orchestration.

Submodules:
    router      — LLM-based query classifier (simple / complex / out-of-scope)
    decomposer  — Breaks complex queries into sub-queries
    grader      — Scores retrieved context sufficiency; triggers re-query if weak
    generator   — Produces answers with inline citations
    faithfulness — Verifies answer is grounded in retrieved context
    pipeline    — End-to-end orchestration pipeline wiring all of the above
    llm         — OpenAI LLM provider implementation with retry + fallback
"""

from atlas.orchestration.decomposer import QueryDecomposer
from atlas.orchestration.faithfulness import FaithfulnessChecker
from atlas.orchestration.generator import AnswerGenerator
from atlas.orchestration.grader import RetrievalGrader
from atlas.orchestration.llm import OpenAILLMProvider
from atlas.orchestration.pipeline import PipelineResult, RAGPipeline
from atlas.orchestration.router import QueryRouter

__all__ = [
    "OpenAILLMProvider",
    "QueryRouter",
    "QueryDecomposer",
    "RetrievalGrader",
    "AnswerGenerator",
    "FaithfulnessChecker",
    "RAGPipeline",
    "PipelineResult",
]
