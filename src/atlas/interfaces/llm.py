"""
Abstract LLM provider interface.

Design rationale:
    Module C (orchestration) needs an LLM for: query classification,
    decomposition, retrieval grading, answer generation, and faithfulness
    checking. All five use the same request/response shape, so one ABC covers
    them all.

    GenerationResponse carries token counts (prompt + completion) so Module E
    can compute per-request cost without instrumenting individual calls.

    The fallback_model field on GenerationRequest lets the provider
    implementation retry on a cheaper/faster model when the primary model
    times out or rate-limits, without any change to the caller.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Literal

from pydantic import BaseModel


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class GenerationRequest(BaseModel):
    messages: list[Message]
    model: str | None = None          # None → use provider default
    fallback_model: str | None = None # None → no fallback
    temperature: float = 0.0
    max_tokens: int = 2048
    json_mode: bool = False           # request structured JSON output


class GenerationResponse(BaseModel):
    content: str
    model_used: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    # If fallback was triggered, record it for observability
    fallback_triggered: bool = False


class BaseLLMProvider(ABC):
    """Generate text from a sequence of messages."""

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Non-streaming generation. Implements retry + fallback internally."""

    @abstractmethod
    async def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        """
        Streaming generation — yields text deltas as they arrive.
        Module E uses this for the /query endpoint's streaming response.
        """
