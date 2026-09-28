"""
Retrieval grader: assess whether retrieved context is sufficient to answer the query.

Design rationale:
    Not every retrieval succeeds. Chunks may be topically adjacent but not
    actually contain the answer — common when the query touches a topic the
    knowledge base covers superficially, or when rare terminology isn't in the
    index. The grader catches this before generation, preventing the generator
    from hallucinating an answer from weak context.

    The grader returns:
      - sufficient (bool): whether to proceed to generation
      - score (float 0–1): a continuous measure for logging/monitoring
      - reformulated_query (str): an alternative query to try on retry

    Reformulation strategy: the LLM is asked to produce a query that uses
    different vocabulary (synonyms, broader terms, or a more specific angle)
    rather than just repeating the original. This matters because BM25 is
    vocabulary-exact — a single synonym swap can recover missing documents.

    Retry cap: we limit to MAX_RETRIES=2 (enforced by the pipeline, not here).
    Beyond 2 retries, the grader accepts the best context seen rather than
    looping indefinitely — a retrieval failure is better communicated as low
    confidence in the answer than as an HTTP timeout to the end user.

    How much context it grades: the top 5 of a 15-chunk window, on purpose,
    and this is the part of the file most likely to look like a bug.

    The generator is handed all 15. So the grader answers "is the top 5
    sufficient?" while the pipeline acts on the answer as if it were "is the
    context sufficient?", and it will call a window insufficient whenever the
    answer sits at rank 6 or below. That reads as an oversight left behind
    when `reranker.top_k` went 5 -> 15 on 2026-09-23, and on 2026-09-28 it
    was changed to grade the whole window for exactly that reason.

    The A/B put it straight back:

        window          precision   recall   faithfulness
        5  (this)          0.4667   0.9378         1.0000
        15 (all)           0.4622   0.8778         0.9667

    The entire recall loss was two rows — fq-006 1.000 -> 0.500 and fq-012
    0.400 -> 0.000 — and both are the multi-document questions. That is the
    mechanism, which the "fix" had backwards: a grader shown a slice is
    pessimistic, pessimism triggers a retry, and since the retry union
    shipped on 2026-09-27 a retry *accumulates* context rather than replacing
    it. The narrow window is how a question whose answer spans five pages
    ever ends up with five pages in front of the generator. Widening the
    grader suppressed the retries, the union never formed, and fq-012 went
    to zero.

    This is load-bearing by accident rather than by design, and therefore
    fragile: it stops being true the moment the retry union stops
    accumulating. `grader.context_chunks` exists so the experiment can be
    re-run in one flag — `--set grader.context_chunks=15` — rather than
    re-argued from the shape of the code, which is how it got changed once
    already.
"""

from __future__ import annotations

import structlog

from atlas.config import GraderConfig
from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, Message
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.llm import parse_json_response

logger = structlog.get_logger(__name__)

_THRESHOLD = 0.5  # below this score → trigger re-query

_SYSTEM_PROMPT = """\
You are a retrieval quality grader for a RAG pipeline. Given a query and a set \
of retrieved context passages, assess whether the context is sufficient to \
answer the query accurately.

Respond with valid JSON containing:
- "sufficient": true if the context contains enough information to answer the query
- "score": a float from 0.0 (completely irrelevant) to 1.0 (perfectly sufficient)
- "reasoning": one sentence explaining your score
- "reformulated_query": a rephrased version of the original query using different \
vocabulary that might retrieve better results (always provide this, even if sufficient=true)

Be strict: if key facts are missing or the context is only tangentially related, \
set sufficient=false."""


def _format_context(chunks: list[RetrievedChunk]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, 1):
        parts.append(f"[{i}] (source: {chunk.metadata.source})\n{chunk.content}")
    return "\n\n".join(parts)


class RetrievalGrader:
    """LLM-based judge: is the retrieved context good enough to generate from?"""

    def __init__(self, llm: BaseLLMProvider, config: GraderConfig | None = None) -> None:
        self._llm = llm
        self._config = config or GraderConfig()
        self._threshold = self._config.threshold

    async def grade(
        self, query: str, chunks: list[RetrievedChunk]
    ) -> tuple[bool, float, str]:
        """
        Returns:
            (sufficient, score, reformulated_query)

        sufficient=True means proceed to generation.
        reformulated_query is always populated for retry use.
        """
        if not chunks:
            return False, 0.0, query

        # Judge what the generator will be handed, unless told otherwise.
        cap = self._config.context_chunks
        graded = chunks if cap is None else chunks[:cap]
        context = _format_context(graded)
        request = GenerationRequest(
            messages=[
                Message(role="system", content=_SYSTEM_PROMPT),
                Message(
                    role="user",
                    content=f"Query: {query}\n\nContext:\n{context}",
                ),
            ],
            temperature=0.0,
            max_tokens=256,
            json_mode=True,
        )
        response = await self._llm.generate(request)
        parsed = parse_json_response(response.content)

        score = float(parsed.get("score", 0.5))
        sufficient = parsed.get("sufficient", score >= self._threshold)
        reformulated = parsed.get("reformulated_query", query)

        logger.info(
            "retrieval_graded",
            query=query[:60],
            score=score,
            sufficient=sufficient,
            # Both, because a verdict from a slice is a different claim from
            # a verdict on the window, and only the pair says which it was.
            graded_chunks=len(graded),
            available_chunks=len(chunks),
        )
        return bool(sufficient), score, reformulated
