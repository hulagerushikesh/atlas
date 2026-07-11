"""
Answer Relevance: does the generated answer actually address the question?

Design rationale:
    An answer can be perfectly faithful (every claim is in the context) but
    still irrelevant — e.g. it answers a related but different question, or
    buries the direct answer under excessive caveats. Answer relevance catches
    this orthogonal failure mode.

    Evaluation approach (reverse-question technique from RAGAS):
      1. Ask the LLM to generate N synthetic questions that the answer would
         be a good response to.
      2. Embed those synthetic questions and the original question.
      3. Score = mean cosine similarity(synthetic_question_i, original_question).

    Rationale: if the answer is highly relevant to the question, the synthetic
    questions derived from it should be semantically close to the original. If
    the answer drifts off-topic, the synthetic questions will diverge.

    We generate N=3 synthetic questions (good coverage/cost tradeoff). The
    embedding similarity is more robust than asking "is this relevant? (0-1)"
    directly because it avoids the LLM's calibration biases for numeric scores.

    The embedder is injected at construction so this metric can be tested with
    a mock embedder and mock LLM without any API calls.
"""

from __future__ import annotations

import numpy as np

import structlog

from atlas.interfaces.embedder import BaseEmbedder
from atlas.interfaces.evaluator import MetricScore
from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, Message
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.llm import parse_json_response
from atlas.evaluation.metrics.base import BaseMetric

logger = structlog.get_logger(__name__)

_N_SYNTHETIC = 3

_JUDGE_PROMPT = f"""\
Given the following answer, generate {_N_SYNTHETIC} distinct questions that this \
answer directly and completely addresses. The questions should be self-contained \
and not reference "the answer" or "the text".

Return valid JSON: {{"questions": ["...", "...", "..."]}}"""


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


class AnswerRelevanceMetric(BaseMetric):
    """Reverse-question cosine similarity metric for answer relevance."""

    def __init__(self, llm: BaseLLMProvider, embedder: BaseEmbedder) -> None:
        self._llm = llm
        self._embedder = embedder

    @property
    def name(self) -> str:
        return "answer_relevance"

    async def score(
        self,
        question: str,
        ground_truth_answer: str,
        generated_answer: str,
        retrieved_chunks: list[RetrievedChunk],
        relevant_doc_ids: list[str],
    ) -> MetricScore:
        # Step 1: generate synthetic questions from the answer
        request = GenerationRequest(
            messages=[
                Message(role="system", content=_JUDGE_PROMPT),
                Message(role="user", content=f"Answer:\n{generated_answer}"),
            ],
            temperature=0.7,   # some diversity in synthetic questions
            max_tokens=256,
            json_mode=True,
        )
        response = await self._llm.generate(request)
        parsed = parse_json_response(response.content)
        synthetic_questions: list[str] = parsed.get("questions", [])

        if not synthetic_questions:
            return MetricScore(
                metric_name=self.name, score=0.0,
                reasoning="LLM returned no synthetic questions.",
            )

        # Step 2: embed original + synthetic questions in one batch
        all_texts = [question] + synthetic_questions
        embed_result = await self._embedder.embed_texts(all_texts)
        vectors = np.array(embed_result.vectors, dtype=np.float32)

        orig_vec = vectors[0]
        synth_vecs = vectors[1:]

        # Step 3: mean cosine similarity
        sims = [_cosine_sim(orig_vec, sv) for sv in synth_vecs]
        relevance = float(np.mean(sims))

        reasoning = (
            f"Mean cosine similarity {relevance:.3f} over {len(sims)} synthetic questions. "
            f"Synthetic questions: {synthetic_questions}"
        )
        logger.debug("answer_relevance_metric", score=relevance, n_synthetic=len(sims))
        return MetricScore(
            metric_name=self.name,
            score=round(max(0.0, min(1.0, relevance)), 4),
            reasoning=reasoning,
        )
