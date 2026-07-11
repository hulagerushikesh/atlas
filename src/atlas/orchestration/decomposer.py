"""
Query decomposer: break a complex query into atomic sub-queries.

Design rationale:
    Multi-hop questions (e.g. "How did our pricing change after the acquisition
    and what was the revenue impact?") embed several distinct retrieval needs.
    Issuing the original composite query as-is tends to retrieve chunks that
    match one part but not the other, diluting the context.

    Decomposition improves recall: sub-query 1 ("pricing change after
    acquisition") finds the relevant pricing document; sub-query 2 ("revenue
    impact of acquisition") finds the finance document. The generator then
    synthesises across both. This is the "query decomposition + parallel
    retrieval" strategy from the FLARE and Least-to-Most papers.

    We cap sub-queries at 4. Empirically, genuine enterprise queries rarely
    require more than 3 independent retrievals, and more sub-queries amplify
    latency and token cost without proportional quality gain.

    The original query is always included as sub-query 0 so the generator has
    the full context even if decomposition produces imperfect sub-queries.
    (Belt-and-suspenders: if a sub-query misses a crucial fact, the original
    might still retrieve it.)
"""

from __future__ import annotations

import structlog

from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, Message
from atlas.orchestration.llm import parse_json_response

logger = structlog.get_logger(__name__)

_MAX_SUB_QUERIES = 4

_SYSTEM_PROMPT = """\
You are a search query decomposer for a RAG system. Given a complex question, \
break it into a list of simpler, independent sub-queries that can each be \
answered by a single retrieved passage.

Rules:
1. Produce between 2 and 4 sub-queries.
2. Each sub-query must be self-contained (no pronouns referencing other sub-queries).
3. Sub-queries should together cover all aspects of the original question.
4. Return valid JSON: {"sub_queries": ["...", "..."]}

Example:
Question: "What is the refund policy, and how long does processing take?"
Response: {"sub_queries": ["What is the refund policy?", \
"How long does refund processing take?"]}"""


class QueryDecomposer:
    """Decompose a complex query into parallel-retrievable sub-queries."""

    def __init__(self, llm: BaseLLMProvider) -> None:
        self._llm = llm

    async def decompose(self, query: str) -> list[str]:
        """
        Return a list of sub-queries. Always includes the original query as the
        first element so callers can safely iterate over the full list.
        """
        request = GenerationRequest(
            messages=[
                Message(role="system", content=_SYSTEM_PROMPT),
                Message(role="user", content=f"Question: {query}"),
            ],
            temperature=0.0,
            max_tokens=256,
            json_mode=True,
        )
        response = await self._llm.generate(request)
        parsed = parse_json_response(response.content)
        sub_queries: list[str] = parsed.get("sub_queries", [])

        # Guard: if decomposition fails or returns nothing useful, fall back
        if not sub_queries or len(sub_queries) < 2:
            logger.warning("decomposition_fallback", query=query[:60])
            return [query]

        # Cap and prepend original
        limited = sub_queries[:_MAX_SUB_QUERIES]
        logger.info(
            "query_decomposed",
            query=query[:60],
            sub_query_count=len(limited),
        )
        return limited
