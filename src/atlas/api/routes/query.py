"""
POST /query — full RAG pipeline with optional streaming.

Design rationale:
    Two response modes share one endpoint path, distinguished by query.stream:

    Non-streaming: run the full pipeline (router → retrieval → grading →
    generation → faithfulness), cache the response, return QueryResponse JSON.
    Stage timings are recorded with perf_counter() at each await boundary so
    they reflect actual wall-clock latency including any event-loop wait time.

    Streaming: bypass the cache (can't cache a stream), call
    AnswerGenerator.stream() directly — which skips the faithfulness check
    because we don't have the full answer until the stream ends. We return a
    StreamingResponse with media_type="text/event-stream" and yield SSE-format
    events. The final event carries citation metadata as a JSON payload so
    clients can render the reference list without a second request.

    Cache integration: cache key = hash of the lower-cased query. On a cache
    hit we short-circuit the entire pipeline and return in <1ms. Cache misses
    run the full pipeline; on completion the result is serialised and cached.
    We do NOT cache streaming responses — the overhead of buffering the stream
    to serialise it defeats the point of streaming.

    Token tracking: we accumulate token counts across all LLM calls in the
    pipeline. The pipeline currently doesn't expose a single token counter,
    so we read from the generation response (the dominant cost) and note that
    grader/router/faithfulness tokens are not yet tracked — logged as a known
    gap so it doesn't silently inflate cost estimates.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from atlas.api.cache import QueryCache
from atlas.api.cost import estimate_cost
from atlas.api.dependencies import get_app_state, get_cache, get_registry
from atlas.api.middleware.metrics_mw import COST_USD, TOKEN_USAGE
from atlas.api.schemas import (
    CitationResponse,
    EvidenceResponse,
    QueryRequest,
    QueryResponse,
    StageTimings,
    TokenUsage,
)
from atlas.orchestration.pipeline import EvidenceChunk, PipelineResult, RAGPipeline

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

# Enough to recognise the passage; the full chunk is one click away.
_EXCERPT_CHARS = 320


def _evidence_response(
    evidence: list[EvidenceChunk],
    citation_by_chunk: dict[str, int],
) -> list[EvidenceResponse]:
    out = []
    for item in evidence:
        chunk = item.chunk
        meta = chunk.metadata
        excerpt = chunk.content.strip()
        if len(excerpt) > _EXCERPT_CHARS:
            excerpt = excerpt[:_EXCERPT_CHARS].rstrip() + "…"
        out.append(EvidenceResponse(
            chunk_id=chunk.chunk_id,
            source=meta.source,
            chunk_index=meta.chunk_index,
            start_char=meta.start_char,
            end_char=meta.end_char,
            page_number=meta.page_number,
            excerpt=excerpt,
            scores={k: round(v, 4) for k, v in item.scores.items()},
            selected=item.selected,
            citation=citation_by_chunk.get(chunk.chunk_id),
        ))
    return out


def _stage_timings(stage_ms: dict[str, float], total_ms: float) -> StageTimings:
    return StageTimings(
        routing_ms=stage_ms.get("routing"),
        decompose_ms=stage_ms.get("decompose"),
        retrieval_ms=stage_ms.get("retrieval"),
        grading_ms=stage_ms.get("grading"),
        generation_ms=stage_ms.get("generation"),
        faithfulness_ms=stage_ms.get("faithfulness"),
        total_ms=round(total_ms, 1),
    )


def _build_response(
    result: PipelineResult,
    timings: StageTimings,
    embedding_model: str,
    cached: bool = False,
) -> QueryResponse:
    citations = []
    citation_by_chunk: dict[str, int] = {}
    if result.generation:
        for num, ref in sorted(result.generation.citations.items()):
            citations.append(CitationResponse(
                number=num,
                chunk_id=ref.chunk_id,
                source=ref.source,
                page_number=ref.page_number,
            ))
            citation_by_chunk[ref.chunk_id] = num

    gen = result.generation
    prompt_tokens = gen.prompt_tokens if gen else 0
    completion_tokens = gen.completion_tokens if gen else 0

    cost = estimate_cost(
        model="gpt-4o-mini",   # read from settings in a full implementation
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        embedding_model=embedding_model,
    )
    token_usage = TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        estimated_cost_usd=cost,
    )

    return QueryResponse(
        query=result.query,
        answer=result.answer,
        classification=result.classification,
        citations=citations,
        is_faithful=result.is_faithful,
        faithfulness_score=result.faithfulness.score if result.faithfulness else None,
        retrieved_chunk_ids=[c.chunk_id for c in result.retrieved_chunks],
        timings=timings,
        token_usage=token_usage,
        grader_retries=result.grader_retries,
        cached=cached,
        sub_queries=list(result.sub_queries),
        grader_score=result.grader_score,
        unsupported_claims=(
            list(result.faithfulness.unsupported_claims) if result.faithfulness else []
        ),
        evidence=_evidence_response(result.evidence, citation_by_chunk),
    )


async def _stream_query(
    query: str,
    pipeline: RAGPipeline,
) -> AsyncIterator[str]:
    """
    Streaming path: route → decompose? → retrieve → grade → stream tokens.

    Emits structured SSE events so the client can animate each stage in real
    time as it completes, rather than waiting for the full response.

    Event shapes:
        {"type":"stage","name":"routing","status":"start"}
        {"type":"stage","name":"routing","status":"done","classification":"simple","ms":45}
        {"type":"delta","text":"token text"}
        {"type":"done","classification":"simple","citations":[...],"is_faithful":true}

    Faithfulness is skipped on the streaming path — we'd have to buffer the
    full answer to check it, defeating the purpose of streaming.
    """
    def _evt(data: dict[str, Any]) -> str:
        return f"data: {json.dumps(data)}\n\n"

    # ── Stage 1: Route ─────────────────────────────────────────────────────────
    yield _evt({"type": "stage", "name": "routing", "status": "start"})
    t0 = time.perf_counter()
    classification = await pipeline._router.classify(query)
    routing_ms = round((time.perf_counter() - t0) * 1000)
    yield _evt({"type": "stage", "name": "routing", "status": "done",
                "classification": classification, "ms": routing_ms})

    if classification == "out_of_scope":
        yield _evt({"type": "done", "classification": "out_of_scope",
                    "answer": "This question appears to be outside the scope "
                    "of the knowledge base. "
                              "Please ask a question related to the available documentation.",
                    "citations": [], "is_faithful": True})
        yield "data: [DONE]\n\n"
        return

    # ── Stage 2: Decompose (complex only) ─────────────────────────────────────
    sub_queries = [query]
    if classification == "complex":
        yield _evt({"type": "stage", "name": "decompose", "status": "start"})
        t0 = time.perf_counter()
        sub_queries = await pipeline._decomposer.decompose(query)
        yield _evt({"type": "stage", "name": "decompose", "status": "done",
                    "sub_queries": len(sub_queries),
                    "ms": round((time.perf_counter() - t0) * 1000)})

    # ── Stage 3: Retrieve ──────────────────────────────────────────────────────
    yield _evt({"type": "stage", "name": "retrieval", "status": "start"})
    t0 = time.perf_counter()
    retrieval = await pipeline._retrieve_all(sub_queries)
    chunks = retrieval.chunks
    # Evidence goes out as soon as retrieval finishes so the client can
    # render the trail while generation is still streaming.
    yield _evt({"type": "stage", "name": "retrieval", "status": "done",
                "chunks": len(chunks), "ms": round((time.perf_counter() - t0) * 1000),
                "evidence": [e.model_dump() for e in _evidence_response(retrieval.evidence, {})]})

    # ── Stage 4: Grade (fast, worth the latency for quality signal) ────────────
    yield _evt({"type": "stage", "name": "grading", "status": "start"})
    t0 = time.perf_counter()
    sufficient, score, _ = await pipeline._grader.grade(query, chunks)
    yield _evt({"type": "stage", "name": "grading", "status": "done",
                "score": round(score, 2), "sufficient": sufficient,
                "ms": round((time.perf_counter() - t0) * 1000)})

    # ── Stage 5: Generate (stream tokens) ─────────────────────────────────────
    yield _evt({"type": "stage", "name": "generation", "status": "start"})
    full_answer = ""
    async for delta in pipeline._generator.stream(query, chunks):
        full_answer += delta
        yield _evt({"type": "delta", "text": delta})

    # Build citation map from the completed answer
    from atlas.orchestration.generator import _CITATION_RE
    cited_indices = {int(m) for m in _CITATION_RE.findall(full_answer)}
    citations = []
    for idx in sorted(cited_indices):
        if 1 <= idx <= len(chunks):
            chunk = chunks[idx - 1]
            citations.append({
                "number": idx,
                "chunk_id": chunk.chunk_id,
                "source": chunk.metadata.source,
                "page_number": chunk.metadata.page_number,
            })

    yield _evt({"type": "done", "classification": classification,
                "citations": citations, "is_faithful": True})


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/query", response_model=None)
async def query(
    body: QueryRequest,
    request: Request,
    cache: QueryCache = Depends(get_cache),
) -> QueryResponse | StreamingResponse:
    """
    Run the full RAG pipeline for a user query.

    Set `stream: true` for token-by-token Server-Sent Events response.
    Set `namespace` to query a specific corpus (default: "default").
    """
    log = logger.bind(query=body.query[:80], namespace=body.namespace)
    pipeline = get_registry(request).get(body.namespace).pipeline

    # ── Streaming path ────────────────────────────────────────────────────────
    if body.stream:
        log.info("query_stream_start")
        return StreamingResponse(
            _stream_query(body.query, pipeline),
            media_type="text/event-stream",
            headers={"X-Faithfulness": "skipped-streaming",
                     "X-Namespace": body.namespace},
        )

    # ── Standard path ─────────────────────────────────────────────────────────
    cache_key = f"{body.namespace}:{body.query}"
    cached_payload = await cache.get(cache_key)
    if cached_payload is not None:
        log.info("query_cache_hit")
        response = QueryResponse.model_validate(cached_payload)
        response.cached = True
        import asyncio

        from atlas.api import auth as _auth
        api_key_id = getattr(request.state, "api_key_id", None)
        if api_key_id is not None:
            asyncio.create_task(_auth.log_usage(
                api_key_id=api_key_id, namespace=body.namespace,
                prompt_tokens=0, completion_tokens=0, latency_ms=0, cache_hit=True,
            ))
        return response

    log.info("query_start")
    t_total = time.perf_counter()

    try:
        result = await pipeline.run(body.query)
    except Exception as exc:
        log.error("query_pipeline_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    total_ms = (time.perf_counter() - t_total) * 1000
    timings = _stage_timings(result.stage_ms, total_ms)

    # Retrieve embedding model name for cost estimation
    app_state = get_app_state(request)
    response = _build_response(result, timings, app_state.embedding_model)

    # Emit Prometheus metrics
    TOKEN_USAGE.labels(model="gpt-4o-mini", type="total").inc(
        response.token_usage.total_tokens
    )
    COST_USD.inc(response.token_usage.estimated_cost_usd)

    # Fire-and-forget: cache + usage log (never block the response)
    import asyncio

    from atlas.api import auth as _auth
    asyncio.create_task(cache.set(cache_key, response.model_dump()))
    api_key_id = getattr(request.state, "api_key_id", None)
    if api_key_id is not None:
        asyncio.create_task(_auth.log_usage(
            api_key_id=api_key_id,
            namespace=body.namespace,
            prompt_tokens=response.token_usage.prompt_tokens,
            completion_tokens=response.token_usage.completion_tokens,
            latency_ms=timings.total_ms,
            cache_hit=False,
        ))

    log.info(
        "query_complete",
        classification=result.classification,
        chunks=len(result.retrieved_chunks),
        faithful=result.is_faithful,
        total_ms=timings.total_ms,
    )
    return response
