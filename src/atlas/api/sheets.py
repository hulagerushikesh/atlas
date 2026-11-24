"""
A sheet's version, so every server notices a change to its documents (E2.3).

Design rationale (docs/e2-permissions.md §4):
    Live runs up to two servers, and each holds its own keyword copy and its
    own answer cache. Removing a document or narrowing who may read it must
    reach both at once: a server that kept the old keyword copy would still
    search the passage as everyone's, and one that kept a cached answer
    would still serve it.

    Shared Redis would cost money every month; a second server switched off
    would cost capacity. Instead each sheet has a version in the tenancy
    store (one more Firestore read per question, inside the free tier).
    Every change writes a new version. A server that sees a version it has
    not seen rebuilds its keyword copy from Qdrant before searching, and the
    version is part of every cache key, so answers from before the change
    are never found again.

    Reading the version fails closed, like every tenancy read: a request
    that cannot learn whether the sheet changed is refused, not answered
    from a copy that may be stale.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import HTTPException

from atlas.api import tenancy
from atlas.api.authz import access_unavailable
from atlas.api.cache import QueryCache
from atlas.api.namespaces import KeywordIndexStale, NamespaceRegistry, SparseSync

logger = structlog.get_logger(__name__)

_UNREAD: Any = object()


async def sheet_version(ws: tenancy.Workspace) -> str:
    try:
        return await tenancy.get_tenancy().get_generation(ws.id)
    except Exception as exc:
        logger.warning("sheet_version_unreadable", workspace_id=ws.id, error=str(exc))
        raise access_unavailable() from exc


async def bring_keyword_copy_up_to_date(
    registry: NamespaceRegistry, corpus: str, version: str, dense_chunks: Any = _UNREAD,
) -> SparseSync:
    """Reconcile this server's keyword copy, rebuilding it if *version* is new."""
    try:
        if dense_chunks is _UNREAD:
            return await registry.reconcile_sparse(corpus, generation=version)
        return await registry.reconcile_sparse(corpus, dense_chunks=dense_chunks,
                                               generation=version)
    except KeywordIndexStale as exc:
        raise HTTPException(status_code=503, detail={
            "code": "sheet_updating",
            "message": "This sheet changed a moment ago and is still updating. "
                       "Try again in a few seconds.",
        }, headers={"Retry-After": "5"}) from exc


async def sheet_changed(registry: NamespaceRegistry, corpus: str,
                        ws: tenancy.Workspace, cache: QueryCache) -> str:
    """Record that *ws*'s documents changed, here and for every other server.

    Called after the change is in Qdrant. This server's own keyword copy was
    already updated by the change, so it is marked current rather than
    rebuilt; its cached answers are dropped now rather than left to age out.
    """
    try:
        version = await tenancy.get_tenancy().bump_generation(ws.id)
    except Exception as exc:
        # The change itself is done. Without a new version other servers
        # would keep their copies, so say so loudly; the caller answers 503
        # and the editor retries, which writes a version then.
        logger.error("sheet_version_not_written", workspace_id=ws.id, error=str(exc))
        raise access_unavailable() from exc
    registry.mark_generation(corpus, version)
    await cache.invalidate_namespace(ws.id)
    logger.info("sheet_changed", workspace_id=ws.id)
    return version
