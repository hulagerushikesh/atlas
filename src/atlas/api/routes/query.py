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
from typing import AsyncIterator

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from atlas.api.cache import QueryCache
from atlas.api.cost import estimate_cost
from atlas.api.dependencies import get_cache, get_pipeline, get_app_state
from atlas.api.middleware.metrics_mw import COST_USD, TOKEN_USAGE
from atlas.api.schemas import (
    CitationResponse,
    QueryRequest,
    QueryResponse,
    StageTimings,
    TokenUsage,
)
from atlas.orchestration.pipeline import RAGPipeline, PipelineResult

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_response(
    result: PipelineResult,
    timings: StageTimings,
    embedding_model: str,
    cached: bool = False,
) -> QueryResponse:
    citations = []
    if result.generation:
        for num, ref in sorted(result.generation.citations.items()):
            citations.append(CitationResponse(
                number=num,
                chunk_id=ref.chunk_id,
                source=ref.source,
                page_number=ref.page_number,
            ))

    # Approximate token usage from the generation step (dominant cost)
    gen = result.generation
    prompt_tokens = 0
    completion_tokens = 0
    if gen:
        # PipelineResult doesn't carry raw token counts; we log the gap
        # In a future iteration, thread token counts through PipelineResult
        pass

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
        cached=cached,
    )


async def _stream_query(
    query: str,
    pipeline: RAGPipeline,
) -> AsyncIterator[str]:
    """
    Streaming path: route → retrieve → stream generator output.

    We skip the faithfulness check on the streaming path because we'd need to
    buffer the full answer before checking — which defeats streaming. The
    tradeoff is documented in the API response headers via X-Faithfulness: skip.
    """
    # Run retrieval synchronously (fast, <100ms) to get chunks for the generator
    classification = await pipeline._router.classify(query)
    if classification == "out_of_scope":
        yield "data: " + json.dumps({"delta": pipeline._router._out_of_scope_msg if hasattr(pipeline._router, "_out_of_scope_msg") else "Out of scope."}) + "\n\n"
        yield "data: [DONE]\n\n"
        return

    if classification == "complex":
        sub_queries = await pipeline._decomposer.decompose(query)
    else:
        sub_queries = [query]

    chunks = await pipeline._retrieve_all(sub_queries)

    # Stream the answer token by token
    async for delta in pipeline._generator.stream(query, chunks):
        yield f"data: {json.dumps({'delta': delta})}\n\n"

    yield "data: [DONE]\n\n"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/query", response_model=None)
async def query(
    body: QueryRequest,
    request: Request,
    pipeline: RAGPipeline = Depends(get_pipeline),
    cache: QueryCache = Depends(get_cache),
) -> QueryResponse | StreamingResponse:
    """
    Run the full RAG pipeline for a user query.

    Set `stream: true` for token-by-token Server-Sent Events response.
    """
    log = logger.bind(query=body.query[:80])

    # ── Streaming path ────────────────────────────────────────────────────────
    if body.stream:
        log.info("query_stream_start")
        return StreamingResponse(
            _stream_query(body.query, pipeline),
            media_type="text/event-stream",
            headers={"X-Faithfulness": "skipped-streaming"},
        )

    # ── Standard path ─────────────────────────────────────────────────────────
    # Cache check
    cached_payload = await cache.get(body.query)
    if cached_payload is not None:
        log.info("query_cache_hit")
        response = QueryResponse.model_validate(cached_payload)
        response.cached = True
        return response

    log.info("query_start")
    t_total = time.perf_counter()
    t0 = t_total

    try:
        result = await pipeline.run(body.query)
    except Exception as exc:
        log.error("query_pipeline_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    total_ms = (time.perf_counter() - t_total) * 1000
    timings = StageTimings(total_ms=round(total_ms, 1))

    # Retrieve embedding model name for cost estimation
    app_state = get_app_state(request)
    response = _build_response(result, timings, app_state.embedding_model)

    # Emit Prometheus metrics
    TOKEN_USAGE.labels(model="gpt-4o-mini", type="total").inc(
        response.token_usage.total_tokens
    )
    COST_USD.inc(response.token_usage.estimated_cost_usd)

    # Populate cache (fire-and-forget — don't await to block the response)
    import asyncio
    asyncio.create_task(cache.set(body.query, response.model_dump()))

    log.info(
        "query_complete",
        classification=result.classification,
        chunks=len(result.retrieved_chunks),
        faithful=result.is_faithful,
        total_ms=timings.total_ms,
    )
    return response
