"""POST /ingest — trigger document indexing."""

from __future__ import annotations

import time
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException

from atlas.api.dependencies import get_indexer
from atlas.api.schemas import IngestRequest, IngestResponse
from atlas.ingestion.indexer import DocumentIndexer

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    body: IngestRequest,
    indexer: DocumentIndexer = Depends(get_indexer),
) -> IngestResponse:
    """
    Index a file or directory.

    The indexer handles idempotency — files whose content has not changed since
    the last run are skipped without re-embedding or re-uploading. This makes
    it safe to call /ingest on a watch loop.
    """
    path = Path(body.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {body.path}")

    logger.info("ingest_request", path=body.path, glob=body.glob)
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
