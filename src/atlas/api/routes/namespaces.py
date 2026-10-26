"""GET /namespaces — list available corpora."""

from __future__ import annotations

from fastapi import APIRouter, Request

from atlas.api.dependencies import get_registry
from atlas.api.namespaces import namespace_to_collection
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
    List all Atlas-managed corpora (Qdrant collections prefixed with atlas_).

    Returns an empty list when Qdrant is unavailable rather than raising an error,
    so the console can still render with the namespace picker disabled.
    """
    registry = get_registry(request)
    names = await registry.list_namespaces()
    namespaces = [
        NamespaceInfo(name=n, collection=namespace_to_collection(n))
        for n in names
    ]
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
    """
    registry = get_registry(request)
    components = registry.get(namespace)
    rows = components.sparse_index.sources() if components.sparse_index else []
    sources = [SourceInfo(**row) for row in rows]
    total_chunks = sum(s.chunks for s in sources)

    dense_chunks = await registry.dense_chunk_count(namespace)
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
        namespace=namespace,
        sources=sources,
        total_sources=len(sources),
        total_chunks=total_chunks,
        dense_chunks=dense_chunks,
        consistent=consistent,
        warning=warning,
        writable=not described,
        description=registry.settings.router.domain if described else None,
    )
