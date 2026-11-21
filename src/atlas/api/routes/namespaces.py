"""GET /namespaces — the corpora the caller may read."""

from __future__ import annotations

from fastapi import APIRouter, Request

from atlas.api import tenancy
from atlas.api.authz import access_unavailable, authorize
from atlas.api.dependencies import get_principal, get_registry
from atlas.api.schemas import (
    NamespaceInfo,
    NamespaceListResponse,
    SourceInfo,
    SourceListResponse,
)

router = APIRouter()


@router.get("/namespaces", response_model=NamespaceListResponse)
async def list_namespaces(request: Request) -> NamespaceListResponse:
    """
    The workspaces the caller may read, and nothing else.

    This used to list every Atlas collection in Qdrant to anyone, which on a
    shared deployment is every company's set names. Now it lists the caller's
    own organisation's workspaces that it holds a role on (a keyless visitor:
    the demo sheet). Public-organisation collections that predate the
    migration have no workspace record yet and are listed from Qdrant.

    Returns an empty list when Qdrant is unavailable rather than raising an error,
    so the console can still render with the namespace picker disabled.
    """
    registry = get_registry(request)
    try:
        found = await tenancy.readable_workspaces(
            get_principal(request), await registry.list_namespaces())
    except tenancy.TenancyUnavailable as exc:
        raise access_unavailable() from exc
    namespaces = [NamespaceInfo(name=w.name, collection=w.collection) for w in found]
    return NamespaceListResponse(namespaces=namespaces, total=len(namespaces))


@router.get("/namespaces/{namespace}/sources", response_model=SourceListResponse)
async def list_sources(namespace: str, request: Request) -> SourceListResponse:
    """
    Inventory of one namespace: every indexed source and its chunk count.

    The rows come from the in-memory BM25 corpus, the only half that carries
    per-chunk metadata. It is persisted separately from Qdrant — the image
    bakes the sparse index while the dense half lives in Qdrant Cloud — so the
    two can disagree, and this endpoint used to advertise whatever the sparse
    side held. The dense point count is now read alongside it (one cheap
    collection-info call) and any disagreement is reported rather than hidden.

    `writable` rides on this response rather than on `/namespaces` because
    the console refetches it per corpus, and because `/namespaces` only lists
    corpora Qdrant already holds -- a corpus the user has just named exists
    in the picker before it exists in Qdrant, and still needs an answer.

    The dense count is read first and then handed to the reconciler, so this
    endpoint brings the sparse half up to date for free -- it was paying for
    that number anyway. That matters because the console refetches this after
    every upload: it is the request most likely to be the first one an
    instance sees for a corpus another instance just wrote.

    Needs reader on the workspace. `writable` also says whether this caller
    may add to it, so a reader's drop zone is disabled before a file is chosen.
    """
    ws = await authorize(request, namespace, "read")
    may_write = get_principal(request).can(ws, "write")
    namespace = tenancy.registry_namespace(ws)
    registry = get_registry(request)
    dense_chunks = await registry.dense_chunk_count(namespace)
    await registry.reconcile_sparse(namespace, dense_chunks=dense_chunks)

    components = registry.get(namespace)
    rows = components.sparse_index.sources() if components.sparse_index else []
    sources = [SourceInfo(**row) for row in rows]
    total_chunks = sum(s.chunks for s in sources)

    consistent = None if dense_chunks is None else dense_chunks == total_chunks

    warning: str | None = None
    if dense_chunks is None:
        warning = (
            "Vector store unreachable — these counts come from the keyword "
            "index alone and may not match what a query can retrieve."
        )
    elif not consistent:
        warning = (
            f"Index mismatch: {total_chunks} chunks listed here, "
            f"{dense_chunks} in the vector store. Queries search the vector "
            f"store, so some sources listed may return nothing."
        )

    described = registry.settings.router.describes(namespace)
    return SourceListResponse(
        namespace=ws.name,
        sources=sources,
        total_sources=len(sources),
        total_chunks=total_chunks,
        dense_chunks=dense_chunks,
        consistent=consistent,
        warning=warning,
        writable=may_write and not described,
        description=registry.settings.router.domain if described else None,
    )
