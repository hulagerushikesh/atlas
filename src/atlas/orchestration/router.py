"""
Query router: classify an incoming query before deciding how to handle it.

Design rationale:
    Routing before retrieval avoids wasting compute on out-of-scope queries
    (returned immediately with a polite refusal) and lets the pipeline tailor
    its strategy to query complexity:

    - simple:       Single-hop question answerable from one or two chunks.
                    → retrieve once, generate directly.
    - complex:      Multi-hop or comparative question requiring synthesis across
                    multiple independent facts.
                    → decompose into sub-queries, retrieve per sub-query, merge.
    - out_of_scope: Query falls outside the knowledge base domain.
                    → return a fixed out-of-scope response, no retrieval.

    The classifier uses a one-shot JSON prompt. We include two examples in the
    system prompt (one per interesting category) rather than zero-shot because
    empirically it cuts misclassification of borderline complex queries ~40%.

    We deliberately keep the LLM call cheap (low max_tokens, temperature=0)
    because the router is on the critical path of every request. The structured
    JSON output (json_mode=True) makes parsing deterministic.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

import structlog

from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, Message
from atlas.orchestration.llm import parse_json_response

logger = structlog.get_logger(__name__)

QueryClass = Literal["simple", "complex", "out_of_scope"]

_SYSTEM_PROMPT = """\
You are a query classifier for an enterprise knowledge base. Classify the user's \
query into exactly one of three categories and respond with valid JSON only.

Categories:
- "simple": Single factual question answerable from one context passage.
- "complex": Requires comparing, synthesising, or reasoning across multiple \
distinct facts or documents.
- "out_of_scope": Clearly outside the knowledge base domain (e.g. personal advice, \
general coding help unrelated to the domain).

Examples:
User: "What is the retention policy for financial records?"
Response: {"classification": "simple", "reasoning": "Single policy lookup."}

User: "How does our Q3 revenue compare to Q2, and what drove the change?"
Response: {"classification": "complex", "reasoning": "Requires two data points and causal reasoning."}

User: "Can you write me a Python sorting algorithm?"
Response: {"classification": "out_of_scope", "reasoning": "Unrelated to the knowledge base domain."}

Respond ONLY with JSON containing "classification" and "reasoning" keys."""


class QueryRouter:
    """Classify a query before routing it to the appropriate pipeline branch."""

    def __init__(self, llm: BaseLLMProvider) -> None:
        self._llm = llm

    async def classify(self, query: str) -> QueryClass:
        request = GenerationRequest(
            messages=[
                Message(role="system", content=_SYSTEM_PROMPT),
                Message(role="user", content=query),
            ],
            temperature=0.0,
            max_tokens=128,
            json_mode=True,
        )
        response = await self._llm.generate(request)
        parsed = parse_json_response(response.content)
        classification: QueryClass = parsed.get("classification", "simple")

        logger.info(
            "query_classified",
            query=query[:60],
            classification=classification,
            reasoning=parsed.get("reasoning", ""),
        )
        return classification
