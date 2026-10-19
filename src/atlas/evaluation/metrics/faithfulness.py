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

    Refusals are excluded, not scored. The generator is instructed to emit one
    exact sentence when the context cannot support an answer; that sentence has
    no factual claims, so the judge dutifully found one claim, marked it
    unsupported and returned 0.0. On the 2026-09-24 run that single sample took
    the headline faithfulness from 1.000 to 0.933 — the harness punishing the
    pipeline for the most honest thing it can do. The refusal count is reported
    separately so the exclusion cannot quietly flatter the score.

    A judge that returns no verdict fails the sample; it does not pass it.
    Until 2026-10-19 a missing `faithfulness_score` key defaulted to 1.0 and
    an empty claims list was scored at face value, so the two ways the judge
    can answer without auditing anything both landed in the headline mean as
    perfect. Both now go to the harness's existing honest paths — a raised
    error (counted as failed, printed in bold) and `applicable=False`
    (counted as skipped) respectively.

    Judge prompt temperature=0.0: faithfulness is a factual determination,
    not a creative judgement. Zero temperature minimises inter-run variance,
    making scores reproducible across eval runs.
"""

from __future__ import annotations

import structlog

from atlas.evaluation.metrics.base import BaseMetric
from atlas.interfaces.evaluator import MetricScore
from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, Message
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.generator import is_refusal
from atlas.orchestration.llm import parse_json_response

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
        if is_refusal(generated_answer):
            # Nothing to audit: the generator declined rather than asserted.
            # Scored 1.0 so a stray reader sees "not unfaithful", but marked
            # inapplicable so it never reaches the mean in either direction.
            return MetricScore(
                metric_name=self.name,
                score=1.0,
                reasoning="Answer is the refusal sentence; no claims to verify.",
                applicable=False,
            )

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
            # Long answers yield 10+ claims; 512 truncated the JSON mid-list on
            # the first live eval and the parse failed the whole sample.
            max_tokens=2048,
            json_mode=True,
        )
        response = await self._llm.generate(request)
        parsed = parse_json_response(response.content)

        if "faithfulness_score" not in parsed:
            # Raise, don't default. This was `parsed.get("faithfulness_score",
            # 1.0)`: a judge that answered with JSON but omitted the one number
            # it was asked for scored the sample perfect, and a perfect score
            # went into the headline mean indistinguishable from an audited
            # one. The runner turns this exception into `score=-1.0,
            # applicable=True`, which the mean drops and `_failed_counts`
            # prints in bold — the harness already has a word for "this sample
            # did not produce a verdict" and it is not 1.0.
            raise ValueError(
                f"faithfulness judge returned no faithfulness_score; keys={sorted(parsed)}"
            )

        claims = parsed.get("claims", [])
        if not claims:
            # The judge was asked for supported/total and returned a score
            # over an empty list, so whatever number it gave was not computed
            # from anything. Inapplicable rather than taken at face value —
            # same shape as AnswerCorrectnessMetric's no-facts branch, and
            # `_inapplicable_counts` publishes it so the exclusion is visible.
            return MetricScore(
                metric_name=self.name,
                score=0.0,
                reasoning="Judge listed no claims; its score was computed over nothing.",
                applicable=False,
            )

        score = float(parsed["faithfulness_score"])
        unsupported = [c["claim"] for c in claims if c.get("verdict") == "unsupported"]

        reasoning = (
            f"Score {score:.2f} over {len(claims)} claims."
            + (f" Unsupported: {unsupported}" if unsupported else " All claims supported.")
        )
        logger.debug("faithfulness_metric", score=score, claims=len(claims))
        return MetricScore(metric_name=self.name, score=round(score, 4), reasoning=reasoning)
