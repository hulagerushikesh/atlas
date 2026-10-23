"""
Answer generator with inline citations.

Design rationale:
    Citations are the difference between a RAG answer and a hallucination. We
    use bracket notation [1], [2], ... where each number maps to the chunk index
    in the context window. The generator is explicitly instructed to cite only
    facts that appear verbatim or are directly inferable from the context — this
    is the primary hallucination guard at the generation stage (the faithfulness
    checker is the secondary guard).

    Citation format choice: bracket numbers rather than (Author, Year) or
    footnotes because they're:
      1. Parseable by a regex without NLP — [\\d+] extracts all citations.
      2. Natural in the output (LLMs have seen this pattern heavily).
      3. Easily linked to chunk metadata in the API response.

    We pass the full source path in the context header so the model can
    optionally surface filenames in the prose ("According to policy.pdf, …")
    without being instructed to do so — a natural behaviour that improves
    perceived trustworthiness.

    GeneratorResult bundles the answer with a resolved citation map so Module
    E can return structured provenance in the API response:
        [1] → {chunk_id, source, page_number}
    without the caller needing to parse the answer text.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import structlog

from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, Message
from atlas.interfaces.retriever import RetrievedChunk

logger = structlog.get_logger(__name__)

_CITATION_RE = re.compile(r"\[(\d+)\]")

# The exact sentence the generator is told to produce when the context does not
# support an answer. It is a constant rather than prose inside the prompt because
# two downstream readers have to recognise it: the faithfulness checker, which
# would otherwise audit it as an unsupported claim, and the eval metric, which
# would otherwise average that 0.0 into the headline score.
REFUSAL = "I don't have sufficient information to answer this question"

# Rule 6 measured at exactly zero on every metric in the suite, and is here
# anyway. The reason it was tried — that dating a changelog claim would move
# `fq-002`'s stale Python floor from *contradicted* to *missing* — turned out
# to be wrong: the judge reads "As of 0.104.0 (2023-10-18), FastAPI requires
# Python 3.8 or above" and still scores it against "FastAPI currently requires
# Python 3.10 or later" as a contradiction, with byte-identical reasoning. What
# it does do is the half nothing in `eval_data` scores: the deployed site stops
# stating a three-year-old fact in the present tense. Kept on that ground
# alone, with faithfulness unmoved at 1.0 and cost per query +1.5%, inside its
# allowance. See DECISIONS 2026-10-23.
_SYSTEM_PROMPT = f"""\
You are an expert assistant for an enterprise knowledge base. Answer the user's \
question using ONLY the provided context passages.

Rules:
1. Cite every factual claim with [N] where N is the passage number.
2. If the answer requires information not in the context, say "{REFUSAL}" \
— do NOT fabricate facts.
3. Be concise and precise. Use bullet points for multi-part answers.
4. If multiple passages support the same claim, cite all of them: [1][3].
5. Start the answer directly — no preamble like "Based on the context...".
6. When a passage's header names a release — a version number, usually with a \
date — what you take from that passage was true at that release and may not be \
true now. Date the claim: "as of 0.104.0 (2023-10-18), ...". Passages whose \
header names no release are undated; do not invent a date for them."""

# Curly apostrophes, a trailing full stop and surrounding whitespace are all
# things the model varies between calls; none of them change what it said.
_REFUSAL_NORMALISED = REFUSAL.lower().strip(" .")


def _normalise(answer: str) -> str:
    return " ".join(answer.replace("\u2019", "'").lower().split()).strip(" .!\"'")


# The pipeline's own non-answer, emitted when the router classifies a query
# out of scope and no generation ever runs. It lived in pipeline.py as a
# private string for months, and the comment above REFUSAL — "two downstream
# readers have to recognise it" — was never true of this one. On 2026-10-19,
# the first run in which the router correctly refused an out-of-scope
# question, all three eval metrics read this message as a real answer:
# answer_correctness scored 0.000 with the reasoning "the pipeline answered
# instead of refusing", answer_relevance averaged 0.41 into the headline, and
# faithfulness audited "This question appears to be outside the scope..." as
# two supported claims and returned 1.0. Making the router more correct made
# three published numbers worse. One concept needs one test, so it lives here
# beside REFUSAL and both are checked by `is_non_answer`.
OUT_OF_SCOPE_MSG = (
    "This question appears to be outside the scope of the knowledge base. "
    "Please ask a question related to the available documentation."
)

_OUT_OF_SCOPE_NORMALISED = OUT_OF_SCOPE_MSG.lower().strip(" .")


def is_refusal(answer: str) -> bool:
    """True when the answer is the refusal sentence and nothing else.

    Deliberately an equality check, not a substring one: "I don't have
    sufficient information about the timeout, but the retry policy is ..."
    is a real answer that happens to open with a caveat, and treating it as a
    refusal would exempt its claims from every check that matters.
    """
    return _normalise(answer) == _REFUSAL_NORMALISED


def is_out_of_scope_message(answer: str) -> bool:
    """True when the answer is the pipeline's out-of-scope message.

    Equality for the same reason as `is_refusal`: an answer that mentions the
    knowledge base's scope and then answers the question is an answer.
    """
    return _normalise(answer) == _OUT_OF_SCOPE_NORMALISED


def is_non_answer(answer: str) -> bool:
    """True when the pipeline declined, by either of the two routes it has.

    The generator emits REFUSAL when the context cannot support an answer; the
    pipeline emits OUT_OF_SCOPE_MSG when the router refuses before retrieval.
    Every reader that skips a refusal — the faithfulness checker and three of
    the eval metrics — means this, not one of the two strings, and checking
    only one made the router's own refusals unmeasurable.
    """
    return is_refusal(answer) or is_out_of_scope_message(answer)


@dataclass
class CitationRef:
    chunk_id: str
    source: str
    page_number: int | None


@dataclass
class GeneratorResult:
    answer: str
    citations: dict[int, CitationRef] = field(default_factory=dict)
    # Chunks actually cited (subset of all retrieved chunks)
    cited_chunks: list[RetrievedChunk] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _build_context(chunks: list[RetrievedChunk]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, 1):
        header = f"[{i}] Source: {chunk.metadata.source}"
        if chunk.metadata.page_number is not None:
            header += f", page {chunk.metadata.page_number}"
        parts.append(f"{header}\n{chunk.content}")
    return "\n\n---\n\n".join(parts)


class AnswerGenerator:
    """Generate cited answers from retrieved context chunks."""

    def __init__(self, llm: BaseLLMProvider) -> None:
        self._llm = llm

    async def generate(
        self, query: str, chunks: list[RetrievedChunk]
    ) -> GeneratorResult:
        context = _build_context(chunks)
        request = GenerationRequest(
            messages=[
                Message(role="system", content=_SYSTEM_PROMPT),
                Message(
                    role="user",
                    content=f"Context:\n{context}\n\nQuestion: {query}",
                ),
            ],
            temperature=0.1,  # slight creativity for fluency, not enough to hallucinate
            max_tokens=1024,
        )
        response = await self._llm.generate(request)
        answer = response.content

        # Resolve which chunk each citation number refers to
        cited_indices = {int(m) for m in _CITATION_RE.findall(answer)}
        citations: dict[int, CitationRef] = {}
        cited_chunks: list[RetrievedChunk] = []

        for idx in sorted(cited_indices):
            if 1 <= idx <= len(chunks):
                chunk = chunks[idx - 1]
                citations[idx] = CitationRef(
                    chunk_id=chunk.chunk_id,
                    source=chunk.metadata.source,
                    page_number=chunk.metadata.page_number,
                )
                if chunk not in cited_chunks:
                    cited_chunks.append(chunk)

        logger.info(
            "answer_generated",
            query=query[:60],
            answer_len=len(answer),
            citations_used=sorted(citations),
            tokens=response.total_tokens,
        )
        return GeneratorResult(
            answer=answer,
            citations=citations,
            cited_chunks=cited_chunks,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )

    async def stream(
        self, query: str, chunks: list[RetrievedChunk]
    ) -> AsyncIterator[str]:
        """Streaming variant for the FastAPI /query endpoint."""
        context = _build_context(chunks)
        request = GenerationRequest(
            messages=[
                Message(role="system", content=_SYSTEM_PROMPT),
                Message(
                    role="user",
                    content=f"Context:\n{context}\n\nQuestion: {query}",
                ),
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        async for delta in self._llm.stream(request):
            yield delta
