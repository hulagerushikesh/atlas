"""
Shared retry predicates for OpenAI calls.

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

from openai import RateLimitError

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
