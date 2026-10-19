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

    The classifier uses a one-shot JSON prompt. We include examples in the
    system prompt rather than going zero-shot because empirically it cuts
    misclassification of borderline complex queries ~40%.

    The out-of-scope examples are a *pair*, on purpose. Until 2026-10-19 the
    only one was "What is the capital of France?", which teaches that a query
    about something else entirely is out of scope and nothing else. The case
    that actually failed is the near miss: a query that names the domain and
    then asks about a third-party product the corpus does not document.
    `fq-016` ("verify a Stripe webhook signature in FastAPI") was classified
    `simple`, and the model's own reasoning said the pattern was "documented in
    the FastAPI ecosystem" — the ecosystem, not the corpus. The QuickBooks
    example reuses the subject of the first simple example so the contrast is
    the scope rule and not the topic, and it names no product that appears in
    any eval row, so the probe measures the rule rather than recall of an
    answer. Measured: scope accuracy 19/21 → 21/21 on `scripts/probe_router.py`,
    with the over-refusal count staying at 0.

    The "when in doubt prefer simple" tie-break is kept but split in two. It
    exists for a real failure — on 2026-10-13 a corpus uploaded through the
    console was refused at the router before retrieval ever ran — so removing
    it to fix under-refusal would trade one direction of error for the worse
    one. It now applies to a subject the domain plausibly owns, and separately
    to the simple/complex choice, rather than to scope in general.

    We deliberately keep the LLM call cheap (low max_tokens, temperature=0)
    because the router is on the critical path of every request. The structured
    JSON output (json_mode=True) makes parsing deterministic.
"""

from __future__ import annotations

from typing import Literal

import structlog

from atlas.config import RouterConfig
from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, Message
from atlas.orchestration.llm import parse_json_response

logger = structlog.get_logger(__name__)

QueryClass = Literal["simple", "complex", "out_of_scope"]

_SYSTEM_PROMPT = """\
You are a query classifier for a knowledge base about: {domain}

Classify the user's query into exactly one of three categories and respond with \
valid JSON only.

Categories:
- "simple": Single factual question answerable from one passage of the knowledge base.
- "complex": Requires comparing, synthesising, or reasoning across multiple \
distinct facts or documents in the knowledge base.
- "out_of_scope": Answering it would need knowledge the knowledge base does not \
hold — personal advice, small talk, general knowledge, or a specific third-party \
product, service or protocol it does not document.

Deciding scope:
Ask what a correct answer would have to be *about*, not which words the query \
uses. A query that names the domain and then asks how to integrate some other \
product is a question about that other product, and the domain's own \
documentation cannot answer it. Naming the domain does not put a query in scope, \
and the domain's wider ecosystem is not the domain.
When you are genuinely unsure whether the knowledge base covers a subject, prefer \
"simple" and let retrieval decide. That tie-break is for a subject the domain \
plausibly owns; it does not apply when the subject is plainly someone else's \
product.

Examples:
User: "What is the retention policy for financial records?"
Response: {{"classification": "simple", "reasoning": "Single policy lookup."}}

User: "How does our Q3 revenue compare to Q2, and what drove the change?"
Response: {{"classification": "complex", "reasoning": "Requires two data points and causal reasoning."}}

User: "How do I export our financial records into QuickBooks?"
Response: {{"classification": "out_of_scope", "reasoning": "Answering needs QuickBooks' documentation; naming a subject the knowledge base covers does not make this in scope."}}

User: "What is the capital of France?"
Response: {{"classification": "out_of_scope", "reasoning": "General knowledge, unrelated to the domain."}}

Respond ONLY with JSON containing "classification" and "reasoning" keys."""


class QueryRouter:
    """Classify a query before routing it to the appropriate pipeline branch."""

    def __init__(self, llm: BaseLLMProvider, config: RouterConfig | None = None) -> None:
        self._llm = llm
        domain = (config or RouterConfig()).domain
        self._system_prompt = _SYSTEM_PROMPT.format(domain=domain)

    async def classify(self, query: str) -> QueryClass:
        request = GenerationRequest(
            messages=[
                Message(role="system", content=self._system_prompt),
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
