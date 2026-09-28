"""
Tests for the retry predicates.

OpenAI returns 429 both for genuine throttling and for an exhausted account
balance, and the SDK raises RateLimitError for each. Retrying the second case
turned a fast failure into a multi-minute silent hang, so the distinction is
load-bearing rather than cosmetic.

The exhausted-credit payload below is copied verbatim from a real API response
rather than invented. An earlier version of this test used a guessed shape,
passed, and still let the bug through — the predicate was matching on `code`
when the stable signal is `type`.
"""

from __future__ import annotations

import socket
from typing import Any

import httpx
import pytest
from openai import APIStatusError, RateLimitError
from qdrant_client.http.exceptions import (
    ResponseHandlingException,
    UnexpectedResponse,
)

from atlas.retry_policy import is_retryable_rate_limit, is_transient_qdrant_error

# Verbatim from a live 429 against api.openai.com with no credit remaining.
REAL_EXHAUSTED_BODY = {
    "message": (
        "You have no credits remaining. Add credits to continue using the API "
        "at https://platform.openai.com/settings/organization/billing/."
    ),
    "type": "insufficient_quota",
    "param": None,
    "code": "credit_balance_exhausted",
}


def _rate_limit_error(body: dict[str, Any]) -> RateLimitError:
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    response = httpx.Response(429, request=request, json={"error": body})
    return RateLimitError("429", response=response, body=body)


def test_real_exhausted_credit_payload_is_not_retried() -> None:
    """The exact response that caused the original multi-minute hang."""
    err = _rate_limit_error(REAL_EXHAUSTED_BODY)
    # Guard the premise: if the SDK stops surfacing these, the test is moot.
    assert err.type == "insufficient_quota"
    assert err.code == "credit_balance_exhausted"
    assert is_retryable_rate_limit(err) is False


@pytest.mark.parametrize(
    "body",
    [
        {"type": "insufficient_quota", "code": None},
        {"type": None, "code": "credit_balance_exhausted"},
        {"type": None, "code": "billing_hard_limit_reached"},
    ],
)
def test_quota_exhaustion_detected_from_either_field(body: dict[str, Any]) -> None:
    assert is_retryable_rate_limit(_rate_limit_error(body)) is False


@pytest.mark.parametrize(
    "body",
    [
        {"type": "requests", "code": "rate_limit_exceeded"},
        {"type": "tokens", "code": "rate_limit_exceeded"},
        {"type": None, "code": None},
    ],
)
def test_genuine_throttling_is_retried(body: dict[str, Any]) -> None:
    assert is_retryable_rate_limit(_rate_limit_error(body)) is True


def test_non_rate_limit_errors_are_not_retried() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    response = httpx.Response(401, request=request, json={"error": {}})
    assert is_retryable_rate_limit(APIStatusError("401", response=response, body={})) is False
    assert is_retryable_rate_limit(ValueError("nope")) is False


# ── Qdrant ────────────────────────────────────────────────────────────────────
#
# The 2026-09-28 ingest lost 37 of 155 files to network faults that nothing
# retried. The four exception shapes below are the ones that actually came
# back from Qdrant Cloud that morning, constructed the way the client
# constructs them rather than as bare stand-ins, because the point of the
# predicate is to recognise what the client really raises.


def _response_handling(source: Exception) -> ResponseHandlingException:
    return ResponseHandlingException(source=source)


def _unexpected(status: int) -> UnexpectedResponse:
    return UnexpectedResponse(
        status_code=status,
        reason_phrase="",
        content=b"",
        headers=httpx.Headers(),
    )


@pytest.mark.parametrize(
    "exc",
    [
        _response_handling(httpx.WriteTimeout("")),
        _response_handling(httpx.ReadTimeout("")),
        _response_handling(httpx.ConnectTimeout("")),
        # DNS gave out under concurrent connections. This one arrives bare,
        # not wrapped, which is why OSError is in the predicate at all.
        socket.gaierror(8, "nodename nor servname provided, or not known"),
        httpx.ConnectError("[Errno 8] nodename nor servname provided"),
    ],
)
def test_transport_faults_are_retried(exc: BaseException) -> None:
    assert is_transient_qdrant_error(exc) is True


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_server_side_statuses_are_retried(status: int) -> None:
    assert is_transient_qdrant_error(_unexpected(status)) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_client_side_statuses_are_not_retried(status: int) -> None:
    """The server answered and will answer the same way forever. 409 in
    particular is `ensure_collection` racing itself, which the caller
    already handles by carrying on."""
    assert is_transient_qdrant_error(_unexpected(status)) is False


def test_unrelated_errors_are_not_retried() -> None:
    assert is_transient_qdrant_error(ValueError("bad vector size")) is False
    assert is_transient_qdrant_error(KeyError("content_hash")) is False
