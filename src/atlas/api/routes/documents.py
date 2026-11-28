"""
One document's access, and removing it (E2.3, docs/e2-permissions.md §4).

    GET    /namespaces/{ns}/documents/access?source=  who may read it now
    PUT    /namespaces/{ns}/documents/access   change who may read it
    DELETE /namespaces/{ns}/documents?source=  take it out of the sheet

Both need editor on the sheet, and both answer "not found" for a document
the caller cannot read itself, exactly as for one that does not exist: an
editor outside a document's group cannot learn its name by trying.

The change lands in Qdrant first (what every server searches), then in this
server's keyword copy, then the sheet's version moves on so the other
server rebuilds its copy and nobody's cached answers are found again.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query, Request

from atlas.access import reader_access
from atlas.api import audit, tenancy
from atlas.api.authz import access_unavailable, authorize
from atlas.api.dependencies import get_app_state, get_principal, get_registry
from atlas.api.routes.ingest import _writable
from atlas.api.schemas import (
    DocumentAccessRequest,
    DocumentAccessResponse,
    DocumentRemovedResponse,
)
from atlas.api.sheets import bring_keyword_copy_up_to_date, sheet_changed, sheet_version
from atlas.interfaces.document import document_id

logger = structlog.get_logger(__name__)
router = APIRouter()


def _not_found(source: str) -> HTTPException:
    return HTTPException(status_code=404, detail={
        "code": "document_not_found",
        "message": f"No document '{source}' that you can open in this sheet."})


def _bad(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code, "message": message})


async def _open(request: Request, namespace: str, source: str) -> tuple[
        tenancy.Workspace, str, str]:
    """The sheet, its registry name and the document's id, once the caller is
    known to be an editor who can read the document."""
    ws = await authorize(request, namespace, "write")
    corpus = tenancy.registry_namespace(ws)
    registry = get_registry(request)
    _writable(corpus, registry.settings.router)
    await bring_keyword_copy_up_to_date(registry, corpus, await sheet_version(ws))
    doc_id = document_id(source)
    access = reader_access() or frozenset()
    if await registry.get(corpus).indexer.readable_passages(doc_id, access) == 0:
        raise _not_found(source)
    return ws, corpus, doc_id


async def _acl(principal: tenancy.Principal, body: DocumentAccessRequest) -> list[str]:
    if body.everyone:
        return [tenancy.ACCESS_ALL]
    tokens: list[str] = []
    store = tenancy.get_tenancy()
    try:
        groups = ({g.name: g.id for g in await store.list_groups(principal.org_id)}
                  if principal.org_id else {})
        people = {}
        for email in body.people:
            user = await store.find_user(tenancy.normalise_email(email))
            if user is not None and user.org_id == principal.org_id:
                people[email] = user.id
    except Exception as exc:
        raise access_unavailable() from exc
    unknown = sorted(set(body.groups) - set(groups))
    if unknown:
        raise _bad("unknown_group",
                   f"Your organisation has no group called {', '.join(unknown)}.")
    strangers = sorted(set(body.people) - set(people))
    if strangers:
        raise _bad("unknown_person", f"{', '.join(strangers)} is not in your organisation.")
    tokens += [f"group:{groups[n]}" for n in sorted(set(body.groups))]
    tokens += [f"user:{people[e]}" for e in sorted(set(body.people))]
    if not tokens:
        raise _bad("no_readers", "Choose everyone on the sheet, or at least one group or person.")
    return tokens


async def _view(principal: tenancy.Principal, source: str, acl: list[str],
                passages: int) -> DocumentAccessResponse:
    """A document's access list in the names an editor knows: groups by name,
    people by email. Tokens that resolve to nothing in the caller's
    organisation are counted, not shown."""
    store = tenancy.get_tenancy()
    try:
        groups = ({g.id: g.name for g in await store.list_groups(principal.org_id)}
                  if principal.org_id else {})
        names: list[str] = []
        people: list[str] = []
        others = 0
        for token in acl:
            kind, _, ident = token.partition(":")
            if token == tenancy.ACCESS_ALL:
                continue
            if kind == "group" and ident in groups:
                names.append(groups[ident])
            elif kind == "user" and (user := await store.get_user(ident)) is not None \
                    and user.org_id == principal.org_id:
                people.append(user.email)
            else:
                others += 1
    except Exception as exc:
        raise access_unavailable() from exc
    return DocumentAccessResponse(
        source=source, everyone=tenancy.ACCESS_ALL in acl, groups=sorted(names),
        people=sorted(people), passages=passages, others=others,
        choices=sorted(groups.values()))


@router.get("/namespaces/{namespace}/documents/access",
            response_model=DocumentAccessResponse)
async def get_document_access(namespace: str, request: Request,
                              source: str = Query(..., min_length=1, max_length=1024),
                              ) -> DocumentAccessResponse:
    _ws, corpus, doc_id = await _open(request, namespace, source)
    indexer = get_registry(request).get(corpus).indexer
    acl = await indexer.document_acl(doc_id) or []
    passages = await indexer.readable_passages(doc_id, reader_access() or frozenset())
    return await _view(get_principal(request), source, acl, passages)


@router.put("/namespaces/{namespace}/documents/access",
            response_model=DocumentAccessResponse)
async def set_document_access(namespace: str, body: DocumentAccessRequest,
                              request: Request) -> DocumentAccessResponse:
    audit.note(request, "document.access", sheet=namespace, source=body.source)
    ws, corpus, doc_id = await _open(request, namespace, body.source)
    acl = await _acl(get_principal(request), body)
    registry = get_registry(request)
    passages = await registry.get(corpus).indexer.set_document_acl(doc_id, acl)
    await sheet_changed(registry, corpus, ws, get_app_state(request).cache)
    logger.info("document_access_changed", workspace_id=ws.id, doc_id=doc_id,
                everyone=body.everyone, groups=len(body.groups), people=len(body.people))
    return await _view(get_principal(request), body.source, acl, passages)


@router.delete("/namespaces/{namespace}/documents", response_model=DocumentRemovedResponse)
async def remove_document(namespace: str, request: Request,
                          source: str = Query(..., min_length=1, max_length=1024),
                          ) -> DocumentRemovedResponse:
    audit.note(request, "document.remove", sheet=namespace, source=source)
    ws, corpus, doc_id = await _open(request, namespace, source)
    registry = get_registry(request)
    removed = await registry.get(corpus).indexer.delete_document(doc_id)
    await sheet_changed(registry, corpus, ws, get_app_state(request).cache)
    logger.info("document_removed", workspace_id=ws.id, doc_id=doc_id, passages=removed)
    return DocumentRemovedResponse(source=source, passages_removed=removed)
