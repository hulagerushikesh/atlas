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

    How much context it grades: all of it, by default. This was a hardcoded
    `chunks[:5]` carrying the comment "more adds noise", which was true when
    `reranker.top_k` was 5 and the slice was the whole window. `top_k` became
    15 on 2026-09-23 and the slice stayed at 5, so for five days the grader
    answered "is the top 5 sufficient?" while the pipeline acted on the answer
    as if it were "is the context sufficient?" — and the generator was handed
    all 15 either way.

    A grader that sees less than the generator can only be wrong in one
    direction. It cannot call a window sufficient that is not, because
    everything it saw is really there. It calls a window insufficient whenever
    the answer sits below the slice, which is a retry the pipeline did not
    need: `fq-005` triggered one while `tutorial/body` was already in the
    window. Since 2026-09-27 a retry can no longer discard context, so the
    consequence is a wasted round trip rather than a lost document — cost and
    latency, not correctness.

    `grader.context_chunks` caps it for anyone who wants the old behaviour or
    something between. Widening the window is not free: at this corpus's mean
    chunk length it adds roughly 1,200 prompt tokens per grade call, against
    a saving of one retrieval plus one grade call for every retry it prevents.
    Which way that nets out is an empirical question and has to be measured,
    not argued: `--set grader.context_chunks=5` reproduces the old default.
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
