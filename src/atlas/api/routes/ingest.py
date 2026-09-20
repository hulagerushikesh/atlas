"""POST /ingest — trigger document indexing."""

from __future__ import annotations

import time
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Request

from atlas.api.budget import BudgetExceeded, seconds_until_utc_midnight
from atlas.api.cost import estimate_cost
from atlas.api.dependencies import get_app_state, get_registry
from atlas.api.schemas import IngestRequest, IngestResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    body: IngestRequest,
    request: Request,
) -> IngestResponse:
    """
    Index a file or directory into a named namespace (corpus).

    The indexer handles idempotency — files whose content has not changed since
    the last run are skipped without re-embedding or re-uploading. This makes
    it safe to call /ingest on a watch loop.
    """
    path = Path(body.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {body.path}")

    app_state = get_app_state(request)
    try:
        await app_state.spend.check()
    except BudgetExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(seconds_until_utc_midnight())},
        ) from exc

    indexer = get_registry(request).get(body.namespace).indexer
    logger.info("ingest_request", path=body.path, namespace=body.namespace, glob=body.glob)
    start = time.perf_counter()

    try:
        if path.is_dir():
            result = await indexer.index_directory(path, glob=body.glob)
        else:
            result = await indexer.index_path(path)
    except Exception as exc:
        logger.error("ingest_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    duration = round(time.perf_counter() - start, 2)
    await app_state.spend.add(estimate_cost(
        model="",
        prompt_tokens=0,
        completion_tokens=0,
        embedding_model=app_state.embedding_model,
        embedding_tokens=result.total_tokens,
    ))
    logger.info(
        "ingest_complete",
        docs_processed=result.documents_processed,
        chunks=result.chunks_indexed,
        duration_s=duration,
    )
    return IngestResponse(
        documents_processed=result.documents_processed,
        documents_skipped=result.documents_skipped,
        chunks_indexed=result.chunks_indexed,
        total_tokens=result.total_tokens,
        duration_seconds=duration,
    )
