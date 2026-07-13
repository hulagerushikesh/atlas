"""GET /namespaces — list available corpora."""

from __future__ import annotations

from fastapi import APIRouter, Request

from atlas.api.dependencies import get_registry
from atlas.api.namespaces import namespace_to_collection
from atlas.api.schemas import NamespaceInfo, NamespaceListResponse

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
