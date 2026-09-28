"""
Shared retry predicates for the two services Atlas cannot run without.

Design rationale:
    OpenAI returns HTTP 429 for two very different conditions, and the SDK
    raises RateLimitError for both:

      - genuine backpressure (too many requests/tokens per minute), which is
        transient and worth retrying with back-off;
      - an exhausted account balance, which is a billing state. It will still
        be true after every back-off, so retrying only delays a guaranteed
        failure — and does so silently.

    Retrying the second case turned a fast, clear error into a multi-minute
    hang: each embedding batch burned its full back-off ladder, and the LLM
    provider then repeated the whole ladder against its fallback model.

    Matching on the right field matters. A real exhausted-credit response is:

        type = "insufficient_quota"          # stable, documented
        code = "credit_balance_exhausted"    # narrower, has changed over time

    so `type` is the primary signal and `code` is a secondary safety net.
    The payload is also inconsistently shaped: SDK exceptions expose `.body`
    as the inner error dict, while raw HTTP JSON nests it under "error".
    Both are handled below.
"""

from __future__ import annotations

from typing import Any

import httpx
from openai import RateLimitError
from qdrant_client.http.exceptions import (
    ResponseHandlingException,
    UnexpectedResponse,
)

_FATAL_TYPES = {"insufficient_quota"}
_FATAL_CODES = {
    "insufficient_quota",
    "credit_balance_exhausted",
    "billing_hard_limit_reached",
}


def _error_fields(exc: RateLimitError) -> tuple[str | None, str | None]:
    """Return (type, code) from an OpenAI error, tolerating payload shapes."""
    err_type = getattr(exc, "type", None)
    err_code = getattr(exc, "code", None)

    body: Any = getattr(exc, "body", None)
    if isinstance(body, dict):
        # Raw HTTP JSON nests the detail under "error"; the SDK does not.
        nested = body.get("error")
        inner: dict[str, Any] = nested if isinstance(nested, dict) else body
        inner_type = inner.get("type")
        inner_code = inner.get("code")
        if err_type is None and isinstance(inner_type, str):
            err_type = inner_type
        if err_code is None and isinstance(inner_code, str):
            err_code = inner_code

    return (
        err_type if isinstance(err_type, str) else None,
        err_code if isinstance(err_code, str) else None,
    )


def is_retryable_rate_limit(exc: BaseException) -> bool:
    """True for transient throttling; False for quota/billing exhaustion."""
    if not isinstance(exc, RateLimitError):
        return False
    err_type, err_code = _error_fields(exc)
    return err_type not in _FATAL_TYPES and err_code not in _FATAL_CODES


# ── Qdrant ────────────────────────────────────────────────────────────────────
#
# A network fault talking to Qdrant Cloud used to lose a whole document. The
# 2026-09-28 ingest failed 37 of 155 files on WriteTimeout, ReadTimeout,
# ConnectTimeout and DNS resolution, embedded them anyway, and wrote neither
# index — paid for, discarded, and reported only as a warning line.
#
# Three shapes reach the caller and all three are the same event:
#   - ResponseHandlingException, which wraps an httpx transport error;
#   - httpx.TransportError raised straight through;
#   - OSError, which is what socket.gaierror ("nodename nor servname
#     provided") is, when the resolver gives out under concurrent connections.
#
# UnexpectedResponse means the server answered, so it is judged on its status:
# a 4xx is a bug in the request and will fail identically forever.

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def is_transient_qdrant_error(exc: BaseException) -> bool:
    """True for a Qdrant failure that a later attempt could plausibly survive."""
    if isinstance(exc, UnexpectedResponse):
        return exc.status_code in _RETRYABLE_STATUS
    return isinstance(exc, ResponseHandlingException | httpx.TransportError | OSError)
