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
from dataclasses import dataclass, field

import structlog

from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, Message
from atlas.interfaces.retriever import RetrievedChunk

logger = structlog.get_logger(__name__)

_CITATION_RE = re.compile(r"\[(\d+)\]")

_SYSTEM_PROMPT = """\
You are an expert assistant for an enterprise knowledge base. Answer the user's \
question using ONLY the provided context passages.

Rules:
1. Cite every factual claim with [N] where N is the passage number.
2. If the answer requires information not in the context, say "I don't have \
sufficient information to answer this question" — do NOT fabricate facts.
3. Be concise and precise. Use bullet points for multi-part answers.
4. If multiple passages support the same claim, cite all of them: [1][3].
5. Start the answer directly — no preamble like "Based on the context..."."""


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
        return GeneratorResult(answer=answer, citations=citations, cited_chunks=cited_chunks)

    async def stream(
        self, query: str, chunks: list[RetrievedChunk]
    ):  # type: ignore[return]  — AsyncIterator[str]
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
