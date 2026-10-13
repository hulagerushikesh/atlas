"""
POST /ingest — index a path the server can already see.
POST /ingest/upload — index files sent by a browser.

Two endpoints because a browser cannot hand the server a path. The console
runs on someone's laptop and the API may be a container in asia-south1, so
"ingest my notes" from the UI has to put the bytes on the wire; `/ingest`
remains for a path the server genuinely has, which is the local-dev and
cron case.

`/ingest` is confined to `settings.ingest.root`. It takes a path on the
server, and whatever it indexes can be read back out through `/query` — so
unconfined it let any authorised caller turn the index into a file-read
channel for anything the process could open. The confinement is a resolved
prefix check, so `..` and symlinks out of the root are both refused.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from atlas.api.budget import BudgetExceeded, seconds_until_utc_midnight
from atlas.api.dependencies import get_app_state, get_registry
from atlas.api.schemas import (
    IngestRequest,
    IngestResponse,
    RejectedUpload,
    UploadIngestResponse,
)
from atlas.cost import estimate_cost
from atlas.ingestion.loaders import is_supported

logger = structlog.get_logger(__name__)
router = APIRouter()


def _confined(path: Path, root: str) -> Path:
    """
    Resolve *path* and refuse it unless it sits under *root*.

    An empty root disables the check, for a single-user API on a laptop where
    the caller and the filesystem owner are the same person. Resolution
    happens before the comparison so that `../../etc` and a symlink pointing
    out of the root are both caught; comparing the unresolved strings would
    catch neither.
    """
    resolved = path.resolve()
    if not root:
        return resolved
    allowed = Path(root).resolve()
    if resolved != allowed and allowed not in resolved.parents:
        raise HTTPException(
            status_code=403,
            detail=(
                f"path is outside the permitted ingest root ({root}). "
                "Upload the files instead, or set INGEST_ROOT."
            ),
        )
    return resolved


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
    app_state = get_app_state(request)
    # Confinement before existence: a 404 on a path outside the root would
    # answer "does this file exist on the server?" for any path at all.
    path = _confined(Path(body.path), app_state.ingest.root)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {body.path}")

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

    # A single file's parent, not None. None puts the whole path into every
    # context header, so re-indexing one file of a corpus gave it headers its
    # neighbours did not have and quietly re-embedded it out of agreement.
    source_root = Path(body.source_root) if body.source_root else None

    try:
        if path.is_dir():
            result = await indexer.index_directory(
                path, glob=body.glob, source_root=source_root
            )
        else:
            result = await indexer.index_path(path, source_root or path.parent)
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


@router.post("/ingest/upload", response_model=UploadIngestResponse)
async def ingest_upload(
    request: Request,
    files: list[UploadFile] = File(..., description="Documents to index"),
    namespace: str = Form("default"),
) -> UploadIngestResponse:
    """
    Index uploaded files into *namespace*, creating the corpus if it is new.

    This is the browser's path in. `/ingest` names a file on the server, which
    a console running on someone's laptop cannot do, so the bytes travel with
    the request and land in a temp directory that is deleted in a `finally`
    whatever happens.

    The temp directory is also the `source_root`, so a chunk's context header
    reads `notes.md` and not `/var/folders/T/tmpXXXX/notes.md` -- without that
    every upload would carry a machine-specific prefix into the index and
    disagree with the same file ingested any other way.

    Refusals are reported, not dropped: unsupported extension, empty file,
    oversized file, too many files, or a total over the request cap. A caller
    that sent ten files and sees `documents_processed: 7` cannot otherwise
    tell which three are missing, and a corpus that is quietly short is worse
    than one that failed loudly.
    """
    app_state = get_app_state(request)
    limits = app_state.ingest

    try:
        await app_state.spend.check()
    except BudgetExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(seconds_until_utc_midnight())},
        ) from exc

    rejected: list[RejectedUpload] = []
    accepted: list[str] = []
    tmpdir = Path(tempfile.mkdtemp(prefix="atlas-upload-"))
    total = 0

    try:
        for i, upload in enumerate(files):
            # `filename` is attacker-controlled: take the basename only, so
            # "../../etc/cron.d/x" cannot escape the temp directory.
            name = Path(upload.filename or f"file-{i}").name
            if i >= limits.max_upload_files:
                rejected.append(RejectedUpload(
                    filename=name,
                    reason=f"over the {limits.max_upload_files}-file limit for one request",
                ))
                continue
            if not is_supported(Path(name)):
                # Asked of the loader registry rather than a list kept here,
                # which would drift the moment a loader is added.
                rejected.append(RejectedUpload(
                    filename=name, reason=f"no loader handles '{Path(name).suffix}'"
                ))
                continue

            body = await upload.read()
            if not body:
                rejected.append(RejectedUpload(filename=name, reason="file is empty"))
                continue
            if len(body) > limits.max_upload_bytes:
                rejected.append(RejectedUpload(
                    filename=name,
                    reason=f"{len(body)} bytes is over the "
                           f"{limits.max_upload_bytes}-byte file limit",
                ))
                continue
            if total + len(body) > limits.max_upload_total_bytes:
                rejected.append(RejectedUpload(
                    filename=name,
                    reason="would take the request over its "
                           f"{limits.max_upload_total_bytes}-byte total",
                ))
                continue

            (tmpdir / name).write_bytes(body)
            total += len(body)
            accepted.append(name)

        if not accepted:
            # Nothing to do, and the reasons are the whole answer. 422 rather
            # than 200, because every file the caller sent was refused.
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "no uploaded file could be indexed",
                    "rejected": [r.model_dump() for r in rejected],
                },
            )

        indexer = get_registry(request).get(namespace).indexer
        logger.info("ingest_upload_request", namespace=namespace,
                    files=len(accepted), bytes=total)
        start = time.perf_counter()
        try:
            result = await indexer.index_directory(tmpdir, source_root=tmpdir)
        except Exception as exc:
            logger.error("ingest_upload_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        duration = round(time.perf_counter() - start, 2)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    await app_state.spend.add(estimate_cost(
        model="",
        prompt_tokens=0,
        completion_tokens=0,
        embedding_model=app_state.embedding_model,
        embedding_tokens=result.total_tokens,
    ))
    logger.info(
        "ingest_upload_complete",
        namespace=namespace,
        docs_processed=result.documents_processed,
        chunks=result.chunks_indexed,
        rejected=len(rejected),
        duration_s=duration,
    )
    return UploadIngestResponse(
        namespace=namespace,
        documents_processed=result.documents_processed,
        documents_skipped=result.documents_skipped,
        chunks_indexed=result.chunks_indexed,
        total_tokens=result.total_tokens,
        duration_seconds=duration,
        accepted=accepted,
        rejected=rejected,
    )
