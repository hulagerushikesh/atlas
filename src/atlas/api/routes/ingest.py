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

Both endpoints refuse a *described* namespace — see `_writable`. The HTTP
API is not how a described corpus is built; `scripts/ingest.py` drives the
indexer directly and is unaffected, which is how the FastAPI corpus this
deployment describes was produced in the first place.
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
from atlas.config import RouterConfig
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


def _writable(namespace: str, cfg: RouterConfig) -> None:
    """
    Refuse a write into the namespace `ROUTER_DOMAIN` describes.

    The router is handed one prose sentence per namespace and decides, before
    retrieval runs, whether a question belongs to the corpus that sentence
    describes. For a described namespace that sentence is a claim about the
    contents — "the FastAPI web framework documentation" — and it stops being
    true the moment a document that is not that lands there.

    The failure this prevents is not an error; it is silence three steps
    later. On 2026-10-25 a PDF uploaded into `default` indexed cleanly,
    reported its chunks, and then every question about it came back
    `Routed out of scope` in 987 ms with nothing retrieved. The upload was
    accepted and the corpus was unusable, which is the worst of both.

    `domain_namespace` exists to spare every *other* namespace this, and it
    works; the hole was always the one namespace it names, which is also the
    console's default target. So the refusal is here, at the write, where the
    cause can still be named — rather than at the query, where all that is
    left is an unexplained refusal.

    A namespace with no specific description cannot be contradicted, so
    `RouterConfig.describes` says no and this is a no-op: on a laptop with no
    ROUTER_DOMAIN set, ingesting into `default` works exactly as before.
    """
    if not cfg.describes(namespace):
        return
    raise HTTPException(
        status_code=409,
        detail=(
            f"'{namespace}' is a described corpus: the router is told it holds "
            f"{cfg.domain}, and judges every question against that sentence "
            "before retrieval runs. A document indexed here that does not fit "
            "the description would be stored and then refused as out of scope "
            "at query time. Ingest into another corpus — every namespace but "
            f"'{namespace}' is routed neutrally."
        ),
    )


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
    _writable(body.namespace, get_registry(request).settings.router)
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

    The temp directory is also the `source_root`, and `relative_sources` makes
    it govern the stored source as well as the context header, so both read
    `notes.md` and not `/var/folders/T/tmpXXXX/notes.md`. Without the first,
    every upload carries a machine-specific prefix into the index and
    disagrees with the same file ingested any other way; without the second,
    that prefix is also what citations show the user and what
    `/namespaces/{namespace}/sources` lists back.

    Refusals are reported, not dropped: unsupported extension, empty file,
    oversized file, too many files, or a total over the request cap. A caller
    that sent ten files and sees `documents_processed: 7` cannot otherwise
    tell which three are missing, and a corpus that is quietly short is worse
    than one that failed loudly.
    """
    app_state = get_app_state(request)
    limits = app_state.ingest
    # Before the budget check and before a byte is read: a write that cannot
    # be accepted should not spend, and should not make the caller wait for
    # an upload first.
    _writable(namespace, get_registry(request).settings.router)

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
            result = await indexer.index_directory(
                tmpdir, source_root=tmpdir, relative_sources=True
            )
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
