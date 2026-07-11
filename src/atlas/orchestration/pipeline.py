"""
End-to-end orchestration pipeline — the public entry point for Module C.

Design rationale:
    RAGPipeline is the single class Module E's /query endpoint calls. It
    encapsulates the full decision tree:

        query
          │
          ▼
        Router ──→ out_of_scope ──→ return fixed message (no LLM call)
          │
          ├──→ simple ──→ retrieve once
          │
          └──→ complex ──→ decompose → retrieve per sub-query → merge & deduplicate
          │
          ▼
        Grader ──→ insufficient ──→ retrieve with reformulated query (≤ MAX_RETRIES)
          │
          ▼
        Generator → answer + citations
          │
          ▼
        FaithfulnessChecker → flag if answer contains unsupported claims

    PipelineResult carries full provenance at every stage so Module D's eval
    harness can inspect intermediate state (e.g. which reformulation fired,
    what the grader score was) without re-running the pipeline.

    Deduplication after sub-query retrieval: the same chunk can surface in
    multiple sub-query results. We deduplicate by chunk_id before grading and
    generation to avoid inflating context with repeated text — which confuses
    the generator's citation numbering.

    The retriever dependency is typed as a protocol-like duck type via
    HybridRetriever, but any object with a compatible retrieve() method works.
    This keeps Module C unit-testable with a simple mock retriever.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import structlog

from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.decomposer import QueryDecomposer
from atlas.orchestration.faithfulness import FaithfulnessChecker, FaithfulnessResult
from atlas.orchestration.generator import AnswerGenerator, GeneratorResult
from atlas.orchestration.grader import RetrievalGrader
from atlas.orchestration.router import QueryRouter

logger = structlog.get_logger(__name__)

_MAX_RETRIES = 2
_OUT_OF_SCOPE_MSG = (
    "This question appears to be outside the scope of the knowledge base. "
    "Please ask a question related to the available documentation."
)


@dataclass
class PipelineResult:
    """Full output and provenance from one pipeline run."""

    query: str
    classification: str
    sub_queries: list[str]
    retrieved_chunks: list[RetrievedChunk]
    grader_score: float
    grader_retries: int
    generation: GeneratorResult | None
    faithfulness: FaithfulnessResult | None
    # Convenience accessors
    answer: str = field(init=False)
    is_faithful: bool = field(init=False)

    def __post_init__(self) -> None:
        self.answer = self.generation.answer if self.generation else _OUT_OF_SCOPE_MSG
        self.is_faithful = self.faithfulness.is_faithful if self.faithfulness else True


class RAGPipeline:
    """Orchestrate routing → retrieval → grading → generation → faithfulness."""

    def __init__(
        self,
        retriever: object,            # HybridRetriever or any duck-typed equivalent
        router: QueryRouter,
        decomposer: QueryDecomposer,
        grader: RetrievalGrader,
        generator: AnswerGenerator,
        faithfulness: FaithfulnessChecker,
    ) -> None:
        self._retriever = retriever
        self._router = router
        self._decomposer = decomposer
        self._grader = grader
        self._generator = generator
        self._faithfulness = faithfulness

    async def run(self, query: str) -> PipelineResult:
        log = logger.bind(query=query[:80])

        # ── Step 1: Route ──────────────────────────────────────────────────────
        classification = await self._router.classify(query)

        if classification == "out_of_scope":
            log.info("pipeline_out_of_scope")
            return PipelineResult(
                query=query,
                classification=classification,
                sub_queries=[],
                retrieved_chunks=[],
                grader_score=0.0,
                grader_retries=0,
                generation=None,
                faithfulness=None,
            )

        # ── Step 2: Decompose (complex only) ───────────────────────────────────
        if classification == "complex":
            sub_queries = await self._decomposer.decompose(query)
        else:
            sub_queries = [query]

        # ── Step 3: Retrieve (with grader-driven retry loop) ───────────────────
        chunks, grader_score, retries = await self._retrieve_with_retry(
            query, sub_queries
        )

        # ── Step 4: Generate ───────────────────────────────────────────────────
        generation = await self._generator.generate(query, chunks)

        # ── Step 5: Faithfulness check ─────────────────────────────────────────
        faithfulness = await self._faithfulness.check(generation.answer, chunks)

        if not faithfulness.is_faithful:
            log.warning(
                "pipeline_faithfulness_flag",
                score=faithfulness.score,
                unsupported=faithfulness.unsupported_claims,
            )

        log.info(
            "pipeline_complete",
            classification=classification,
            chunks=len(chunks),
            retries=retries,
            faithful=faithfulness.is_faithful,
        )
        return PipelineResult(
            query=query,
            classification=classification,
            sub_queries=sub_queries,
            retrieved_chunks=chunks,
            grader_score=grader_score,
            grader_retries=retries,
            generation=generation,
            faithfulness=faithfulness,
        )

    async def _retrieve_with_retry(
        self,
        original_query: str,
        sub_queries: list[str],
    ) -> tuple[list[RetrievedChunk], float, int]:
        """
        Retrieve for all sub-queries, fuse, grade. Retry up to MAX_RETRIES
        times with reformulated query if context is insufficient.
        Returns (chunks, grader_score, retry_count).
        """
        current_queries = sub_queries
        retries = 0

        while True:
            chunks = await self._retrieve_all(current_queries)
            sufficient, score, reformulated = await self._grader.grade(
                original_query, chunks
            )

            if sufficient or retries >= _MAX_RETRIES:
                return chunks, score, retries

            logger.info(
                "retrieval_retry",
                attempt=retries + 1,
                score=score,
                reformulated=reformulated[:60],
            )
            current_queries = [reformulated]
            retries += 1

    async def _retrieve_all(self, queries: list[str]) -> list[RetrievedChunk]:
        """Retrieve for each sub-query concurrently, deduplicate by chunk_id."""
        # Each call returns a HybridRetrievalResult (or duck-typed equivalent)
        results = await asyncio.gather(
            *[self._retriever.retrieve(q) for q in queries]
        )
        seen: set[str] = set()
        merged: list[RetrievedChunk] = []
        for result in results:
            for chunk in result.chunks:
                if chunk.chunk_id not in seen:
                    seen.add(chunk.chunk_id)
                    merged.append(chunk)
        return merged
