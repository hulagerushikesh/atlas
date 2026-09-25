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
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

from atlas.interfaces.reranker import BaseReranker
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
class EvidenceChunk:
    """
    One retrieved chunk with the score it earned at each retrieval stage.

    The hybrid retriever already computes all of this — per-retriever raw
    scores, the RRF fused score, the cross-encoder rerank score — and then
    hands back only the final list. Keeping the intermediate scores is what
    lets the console show *why* a chunk was chosen or cut, which is the
    product's whole point.

    `selected` is False for chunks that survived fusion but were cut by the
    reranker's top_k: they were candidates the generator never saw.
    """

    chunk: RetrievedChunk
    scores: dict[str, float] = field(default_factory=dict)
    selected: bool = True


@dataclass
class RetrievalPass:
    """Chunks handed to the generator, plus the evidence trail behind them."""

    chunks: list[RetrievedChunk]
    evidence: list[EvidenceChunk]


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
    # Selected chunks first, then rerank rejects, each with per-stage scores.
    evidence: list[EvidenceChunk] = field(default_factory=list)
    # Wall-clock per stage, keyed by stage name. Retrieval and grading
    # accumulate across grader-driven retries.
    stage_ms: dict[str, float] = field(default_factory=dict)
    # Convenience accessors
    answer: str = field(init=False)
    is_faithful: bool = field(init=False)

    def __post_init__(self) -> None:
        self.answer = self.generation.answer if self.generation else _OUT_OF_SCOPE_MSG
        self.is_faithful = self.faithfulness.is_faithful if self.faithfulness else True


class RetrievalLike(Protocol):
    """
    Anything exposing a final ranked chunk list. Declared as a read-only
    property so it matches both RetrievalResult (a pydantic field) and
    HybridRetrievalResult (a computed property).
    """

    @property
    def chunks(self) -> list[RetrievedChunk]: ...


class SupportsRetrieve(Protocol):
    """
    The slice of the retriever the pipeline actually depends on.

    A Protocol rather than the concrete class so alternative retrievers stay
    pluggable, and rather than `object` so the duck-typed contract is still
    checked instead of silently accepting anything.
    """

    async def retrieve(self, query: str) -> RetrievalLike: ...


class RAGPipeline:
    """Orchestrate routing → retrieval → grading → generation → faithfulness."""

    def __init__(
        self,
        retriever: SupportsRetrieve,
        router: QueryRouter,
        decomposer: QueryDecomposer,
        grader: RetrievalGrader,
        generator: AnswerGenerator,
        faithfulness: FaithfulnessChecker,
        reranker: BaseReranker | None = None,
    ) -> None:
        self._retriever = retriever
        self._router = router
        self._decomposer = decomposer
        self._grader = grader
        self._generator = generator
        self._faithfulness = faithfulness
        # Used only to re-rank the union of a retried retrieval against the
        # original query. Optional so a caller that builds a pipeline without
        # one keeps the old single-pass behaviour instead of failing.
        self._reranker = reranker

    async def run(self, query: str) -> PipelineResult:
        log = logger.bind(query=query[:80])
        stage_ms: dict[str, float] = {}

        # ── Step 1: Route ──────────────────────────────────────────────────────
        t0 = time.perf_counter()
        classification = await self._router.classify(query)
        stage_ms["routing"] = _elapsed_ms(t0)

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
                stage_ms=stage_ms,
            )

        # ── Step 2: Decompose (complex only) ───────────────────────────────────
        if classification == "complex":
            t0 = time.perf_counter()
            sub_queries = await self._decomposer.decompose(query)
            stage_ms["decompose"] = _elapsed_ms(t0)
        else:
            sub_queries = [query]

        # ── Step 3: Retrieve (with grader-driven retry loop) ───────────────────
        retrieval, grader_score, retries = await self._retrieve_with_retry(
            query, sub_queries, stage_ms
        )
        chunks = retrieval.chunks

        # ── Step 4: Generate ───────────────────────────────────────────────────
        t0 = time.perf_counter()
        generation = await self._generator.generate(query, chunks)
        stage_ms["generation"] = _elapsed_ms(t0)

        # ── Step 5: Faithfulness check ─────────────────────────────────────────
        t0 = time.perf_counter()
        faithfulness = await self._faithfulness.check(generation.answer, chunks)
        stage_ms["faithfulness"] = _elapsed_ms(t0)

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
            evidence=retrieval.evidence,
            stage_ms=stage_ms,
        )

    async def _retrieve_with_retry(
        self,
        original_query: str,
        sub_queries: list[str],
        stage_ms: dict[str, float],
    ) -> tuple[RetrievalPass, float, int]:
        """
        Retrieve for all sub-queries, fuse, grade. Retry up to MAX_RETRIES
        times with reformulated query if context is insufficient.
        Returns (retrieval, grader_score, retry_count). Retrieval and grading
        time accumulate into *stage_ms* across retries, so the trace shows the
        true cost of a retried query rather than only the final attempt.
        """
        current_queries = sub_queries
        retries = 0
        # Every chunk any attempt has seen, in first-seen order, and the width
        # of one window. A retry used to overwrite `retrieval`, so a grader
        # that wrongly called a window insufficient did not merely fail to
        # help — the next pass discarded documents the pipeline already had.
        # fq-005 lost `tutorial/body` that way: five chunks of it in the first
        # window, graded 0.4 because the grader only reads the top five, and
        # the replacement window had none.
        union: list[RetrievedChunk] = []
        seen: set[str] = set()
        window = 0

        while True:
            t0 = time.perf_counter()
            retrieval = await self._retrieve_all(current_queries)
            stage_ms["retrieval"] = stage_ms.get("retrieval", 0.0) + _elapsed_ms(t0)
            window = window or len(retrieval.chunks)
            for chunk in retrieval.chunks:
                if chunk.chunk_id not in seen:
                    seen.add(chunk.chunk_id)
                    union.append(chunk)

            t0 = time.perf_counter()
            sufficient, score, reformulated = await self._grader.grade(
                original_query, retrieval.chunks
            )
            stage_ms["grading"] = stage_ms.get("grading", 0.0) + _elapsed_ms(t0)

            if sufficient or retries >= _MAX_RETRIES:
                if retries:
                    retrieval = await self._merge_attempts(
                        original_query, retrieval, union, window, stage_ms
                    )
                return retrieval, score, retries

            logger.info(
                "retrieval_retry",
                attempt=retries + 1,
                score=score,
                reformulated=reformulated[:60],
            )
            current_queries = [reformulated]
            retries += 1

    async def _merge_attempts(
        self,
        original_query: str,
        latest: RetrievalPass,
        union: list[RetrievedChunk],
        window: int,
        stage_ms: dict[str, float],
    ) -> RetrievalPass:
        """Collapse every attempt's chunks back to one window.

        Scored against the *original* query, not the reformulation: attempt
        one's scores and attempt two's are each relative to a different
        question, so the two rankings cannot be interleaved as they stand, and
        what the caller asked is the only question both sets can be compared
        on. Without a reranker there is nothing to compare them with, so the
        latest attempt is returned unchanged — the old behaviour.
        """
        if self._reranker is None:
            return latest
        if len(union) <= window:
            return RetrievalPass(chunks=union, evidence=latest.evidence)
        t0 = time.perf_counter()
        merged = await self._reranker.rerank(original_query, union, window)
        stage_ms["retrieval"] = stage_ms.get("retrieval", 0.0) + _elapsed_ms(t0)
        logger.info("retry_union_reranked", union=len(union), kept=len(merged))
        return RetrievalPass(chunks=merged, evidence=latest.evidence)

    async def _retrieve_all(self, queries: list[str]) -> RetrievalPass:
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
        return RetrievalPass(chunks=merged, evidence=_collect_evidence(results, seen))


def _elapsed_ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


# Retriever names as reported by BaseRetriever.name, mapped to the short
# labels the console shows. Unknown retrievers keep their own name.
_SCORE_LABELS = {"qdrant_dense": "dense", "bm25_sparse": "bm25"}


def _collect_evidence(results: list[Any], selected_ids: set[str]) -> list[EvidenceChunk]:
    """
    Rebuild per-chunk score trails from HybridRetrievalResult provenance.

    Duck-typed on purpose: the pipeline accepts any retriever exposing
    `.chunks`, and a plain RetrievalResult has no fusion or rerank stages.
    In that case the evidence is just the final chunks with their one score.
    Across sub-queries the same chunk can appear more than once; the highest
    score per stage is kept, since that is the one that got it selected.
    """
    trails: dict[str, EvidenceChunk] = {}

    def _record(chunk: RetrievedChunk, label: str) -> None:
        trail = trails.get(chunk.chunk_id)
        if trail is None:
            trail = EvidenceChunk(chunk=chunk, selected=chunk.chunk_id in selected_ids)
            trails[chunk.chunk_id] = trail
        elif chunk.chunk_id in selected_ids:
            # Prefer the reranked copy: its .score is the final one the
            # generator saw and its content is identical.
            trail.chunk = chunk
        trail.scores[label] = max(trail.scores.get(label, float("-inf")), chunk.score)

    for result in results:
        per_retriever = getattr(result, "per_retriever", None)
        fused = getattr(result, "fused", None)
        reranked = getattr(result, "reranked", None)
        if not isinstance(per_retriever, list):
            # Not a hybrid result: only the final list and its score exist.
            for chunk in result.chunks:
                _record(chunk, "score")
            continue
        for sub in per_retriever:
            label = _SCORE_LABELS.get(sub.retriever_name, sub.retriever_name)
            for chunk in sub.chunks:
                _record(chunk, label)
        for chunk in fused or []:
            _record(chunk, "rrf")
        for chunk in reranked or []:
            _record(chunk, "rerank")

    # Selected first in their final rank order, then the rerank rejects.
    ordered = sorted(
        trails.values(),
        key=lambda e: (not e.selected, -e.scores.get("rerank", e.scores.get("rrf", 0.0))),
    )
    return ordered
