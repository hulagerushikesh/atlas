"""
HyDE: retrieve with a passage that would answer the query, not the query.

Design rationale:
    A question and the passage that answers it are written by different
    people for different purposes, and they do not share vocabulary. `fq-012`
    asks "how do I add string validation to a query parameter"; the pages
    that answer it are `tutorial/query-params-str-validations`,
    `tutorial/path-params-numeric-validations` and three others, and they
    talk about `Query`, `Annotated`, `min_length` and `Pydantic`. Measured on
    2026-09-29, how often a page says "pydantic" predicted whether it was
    retrieved, exactly:

        tutorial/body                      15 mentions   retrieved
        tutorial/query-params-str-…         5 mentions   retrieved
        tutorial/body-multiple-params       2 mentions   not retrieved
        tutorial/query-params               0 mentions   not retrieved
        tutorial/path-params-numeric-…      0 mentions   not retrieved

    Neither a reranker nor a decomposer can close that. A reranker reorders
    candidates the query already found; the decomposer splits the question
    into shards that inherit its words — probed for ₹0.023, all three shards
    led with "Pydantic" and scored what the live run scored. HyDE changes the
    words being searched with, which is the thing that is wrong.

    So: ask the model to write the passage, then search with that. The
    passage is a probe, not an answer. It is never shown to the user, never
    reaches the generator, and is not required to be true — its imagined
    `Annotated[str, Query(min_length=3)]` retrieves the real page whether or
    not the signature is right. The generator still answers from retrieved
    text alone, so a wrong hypothesis costs a worse search, never a wrong
    answer. That asymmetry is the whole reason this is safe to try.

    Deterministic at temperature 0.0, against the paper, which samples
    several hypotheses and averages their embeddings. Two reasons. Averaging
    embeddings has no sparse equivalent, and half of this retriever is BM25.
    And a sampled probe makes two runs of the same eval incomparable for a
    reason that has nothing to do with the knob being tested — this repo has
    already lost one baseline that way.

    Failure is a fallback, never an error. If the call raises or comes back
    empty, the original query is used. HyDE off and HyDE broken then produce
    the same retrieval, which is the only sane behaviour for something that
    sits in front of every search.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog

from atlas.config import HyDEConfig
from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, Message

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
You write short passages of reference documentation.

Given a question, write the passage of documentation that would answer it — \
as an excerpt from the manual itself, in its voice, naming the classes, \
functions, parameters, decorators and imports that such a page would name.

The passage is used as a search probe and is never shown to anyone. Being \
plausible and specific matters; being correct does not, and is not checked. \
A confident passage using the right technical vocabulary is worth more than \
a cautious one that avoids it.

Rules:
1. Three to five sentences. No preamble, no heading, no code fence, no \
markdown list.
2. Name concrete identifiers wherever a real page would.
3. Never say you are unsure, and never mention the question.
4. Output the passage and nothing else."""


@dataclass(frozen=True)
class Expansion:
    """One query, the passage written for it, and what gets searched with."""

    query: str
    # "" when the call failed or returned nothing — `text` is then the query.
    hypothesis: str
    text: str


class HyDEExpander:
    """Turn retrieval queries into hypothetical-answer probes."""

    def __init__(self, llm: BaseLLMProvider, config: HyDEConfig | None = None) -> None:
        self._llm = llm
        self._config = config or HyDEConfig()

    async def expand(self, queries: list[str]) -> list[Expansion]:
        """Expand every query concurrently, in the order given.

        Deduplicated by text before the calls go out: the pipeline prepends
        the original query to its sub-queries, and a decomposer that echoes
        the question back as one of its shards would otherwise be paid for
        twice for one probe.
        """
        unique = list(dict.fromkeys(queries))
        results = await asyncio.gather(*[self._one(q) for q in unique])
        by_query = dict(zip(unique, results, strict=True))
        return [by_query[q] for q in queries]

    async def _one(self, query: str) -> Expansion:
        request = GenerationRequest(
            messages=[
                Message(role="system", content=_SYSTEM_PROMPT),
                Message(role="user", content=query),
            ],
            temperature=0.0,
            max_tokens=self._config.max_tokens,
        )
        try:
            response = await self._llm.generate(request)
            hypothesis = response.content.strip()
        except Exception as exc:
            # Never fatal. A search that is merely no better than before beats
            # a 500 on a feature that is off by default everywhere else.
            logger.warning("hyde_failed", query=query[:60], error=str(exc))
            return Expansion(query=query, hypothesis="", text=query)

        if not hypothesis:
            logger.warning("hyde_empty", query=query[:60])
            return Expansion(query=query, hypothesis="", text=query)

        text = hypothesis if self._config.mode == "replace" else f"{query}\n\n{hypothesis}"
        logger.info(
            "hyde_expanded",
            query=query[:60],
            mode=self._config.mode,
            hypothesis_chars=len(hypothesis),
        )
        return Expansion(query=query, hypothesis=hypothesis, text=text)
