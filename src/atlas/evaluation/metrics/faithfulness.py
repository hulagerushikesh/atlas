"""
Faithfulness metric: are the answer's claims grounded in the retrieved context?

Design rationale:
    Faithfulness is the most important RAG quality metric for enterprise use:
    a hallucinated fact in a legal or financial context is worse than "I don't
    know." We use LLM-as-judge because semantic faithfulness cannot be computed
    deterministically — a claim can be faithful even if the wording differs
    from the source.

    Evaluation protocol (same claim-decompose-then-verify pattern as Module C's
    FaithfulnessChecker):
      1. Ask the LLM to list distinct factual claims in the generated answer.
      2. For each claim, verify whether the retrieved context supports it.
      3. Score = supported_claims / total_claims.

    Why use a separate LLM call rather than reusing the FaithfulnessChecker
    from Module C?
    The eval harness must be independent of the pipeline under evaluation.
    If we reuse the same checker, we conflate pipeline faithfulness (was it
    faithful when generated?) with eval faithfulness (is it faithful now?).
    The eval metric is ground-truth agnostic — it judges the answer against
    the retrieved context only, which may differ between pipeline runs.

    Judge prompt temperature=0.0: faithfulness is a factual determination,
    not a creative judgement. Zero temperature minimises inter-run variance,
    making scores reproducible across eval runs.
"""

from __future__ import annotations

import structlog

from atlas.interfaces.evaluator import MetricScore
from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, Message
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.llm import parse_json_response
from atlas.evaluation.metrics.base import BaseMetric

logger = structlog.get_logger(__name__)

_JUDGE_PROMPT = """\
You are evaluating whether an AI-generated answer is faithful to the provided \
source context (i.e., does not contain hallucinations).

Steps:
1. List every distinct factual claim in the answer.
2. For each claim determine if it is:
   - "supported": directly stated or clearly inferable from the context
   - "unsupported": contradicts or goes beyond the context
   - "unverifiable": neither confirmed nor denied (count as supported)
3. Compute faithfulness_score = supported_count / total_claims (unverifiable counts as supported).

Return valid JSON:
{
  "claims": [{"claim": "...", "verdict": "supported|unsupported|unverifiable"}],
  "faithfulness_score": 0.0
}"""


class FaithfulnessMetric(BaseMetric):
    """LLM-as-judge: fraction of answer claims grounded in retrieved context."""

    def __init__(self, llm: BaseLLMProvider) -> None:
        self._llm = llm

    @property
    def name(self) -> str:
        return "faithfulness"

    async def score(
        self,
        question: str,
        ground_truth_answer: str,
        generated_answer: str,
        retrieved_chunks: list[RetrievedChunk],
        relevant_doc_ids: list[str],
    ) -> MetricScore:
        context = "\n\n".join(f"[{i}] {c.content}" for i, c in enumerate(retrieved_chunks, 1))
        request = GenerationRequest(
            messages=[
                Message(role="system", content=_JUDGE_PROMPT),
                Message(
                    role="user",
                    content=f"Context:\n{context}\n\nAnswer:\n{generated_answer}",
                ),
            ],
            temperature=0.0,
            max_tokens=512,
            json_mode=True,
        )
        response = await self._llm.generate(request)
        parsed = parse_json_response(response.content)

        score = float(parsed.get("faithfulness_score", 1.0))
        claims = parsed.get("claims", [])
        unsupported = [c["claim"] for c in claims if c.get("verdict") == "unsupported"]

        reasoning = (
            f"Score {score:.2f} over {len(claims)} claims."
            + (f" Unsupported: {unsupported}" if unsupported else " All claims supported.")
        )
        logger.debug("faithfulness_metric", score=score, claims=len(claims))
        return MetricScore(metric_name=self.name, score=round(score, 4), reasoning=reasoning)
