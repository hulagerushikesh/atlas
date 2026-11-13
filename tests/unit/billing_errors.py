"""The 429 Gemini returns when its prepaid credit is gone, built the SDK's way.

Not captured from a live response — that needs an empty account. The sentence
and RESOURCE_EXHAUSTED status are as reported on Google's developer forum;
the message format is the one the OpenAI SDK builds for any status error.
"""

from __future__ import annotations

from typing import Any

import httpx
from openai import RateLimitError

DEPLETED_MESSAGE = (
    "Your prepayment credits are depleted. Please go to AI Studio at "
    "https://ai.studio/projects to manage your project and billing."
)


def gemini_429(message: str = DEPLETED_MESSAGE) -> RateLimitError:
    body: list[dict[str, Any]] = [
        {"error": {"code": 429, "message": message, "status": "RESOURCE_EXHAUSTED"}}
    ]
    url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    response = httpx.Response(429, request=httpx.Request("POST", url), json=body)
    return RateLimitError(f"Error code: 429 - {body}", response=response, body=body)
