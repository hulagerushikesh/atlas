"""
Who the current search is for: the access tokens retrieval filters on (E2).

Design rationale (docs/e2-permissions.md §3):
    Every passage carries an access list (`acl`), copied from its document.
    A caller may read a passage when the two share a token. The filter runs
    inside both searches, so a forbidden passage is never fetched, reranked,
    graded, quoted, cached or cited.

    The caller's tokens travel in a context variable, set once per request by
    the auth middleware from the principal, and read by the dense and keyword
    retrievers at the point they search. Passing them as an argument would
    have to thread through the pipeline's every path (plain, decomposed,
    HyDE, grader retries, streaming), and the one path a later change forgot
    would search unfiltered. Here there is no path to forget: any search made
    while serving a request is filtered.

    None means "not serving a request" (eval and ingest scripts on the
    laptop) and searches unfiltered. Inside a request the value is always a
    set, and an empty set reads nothing. A passage with no access list is
    readable by no request: fail closed, so a passage the E2 migration missed
    disappears instead of leaking.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextvars import ContextVar

ACL_FIELD = "acl"

_reader_access: ContextVar[frozenset[str] | None] = ContextVar("atlas_reader_access",
                                                               default=None)


def set_reader_access(tokens: Iterable[str]) -> None:
    """Scope every search made from here on, in this request, to *tokens*."""
    _reader_access.set(frozenset(tokens))


def reader_access() -> frozenset[str] | None:
    """The current request's tokens; None outside a request."""
    return _reader_access.get()


def readable(acl: Iterable[str] | None, access: frozenset[str] | None) -> bool:
    """May a caller holding *access* read a passage whose access list is *acl*?"""
    if access is None:
        return True
    return not access.isdisjoint(acl or ())
