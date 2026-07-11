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
"""

from __future__ import annotations

import structlog

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

    def __init__(self, llm: BaseLLMProvider, threshold: float = _THRESHOLD) -> None:
        self._llm = llm
        self._threshold = threshold

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

        context = _format_context(chunks[:5])  # grade on top-5 only; more adds noise
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
        )
        return bool(sufficient), score, reformulated
