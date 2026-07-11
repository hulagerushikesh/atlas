"""
OpenAI LLM provider with retry and automatic fallback.

Design rationale:
    All five orchestration components (router, decomposer, grader, generator,
    faithfulness checker) call one method: generate(). This single provider
    class handles:

    Retry: tenacity retries on RateLimitError with exponential back-off. We
    distinguish rate-limit (retriable) from auth/validation errors (not
    retriable) and re-raise the latter immediately — no point burning retries
    on a misconfigured API key.

    Fallback: if the primary model is unavailable (overloaded, deprecated, or
    returning a server error after retries), we transparently retry on
    fallback_model and set GenerationResponse.fallback_triggered=True so Module
    E can track how often fallback fires. This is an important production
    safety net — gpt-4o outages have happened, and falling back to gpt-3.5-turbo
    beats a 500 to the end user.

    JSON mode: when request.json_mode=True we set response_format={"type":
    "json_object"}. This instructs the API to guarantee valid JSON output, which
    all structured components (router, grader, etc.) rely on. Without this,
    occasional markdown code fences or prose wrapping breaks json.loads().

    Streaming: stream() yields text deltas as they arrive from the SSE stream.
    Module E's /query endpoint uses this for real-time response streaming. The
    streaming path does NOT support json_mode (OpenAI limitation) — only the
    generator uses streaming and it produces prose, not structured JSON.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import structlog
from openai import AsyncOpenAI, APIStatusError, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from atlas.config import OpenAIConfig
from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, GenerationResponse, Message

logger = structlog.get_logger(__name__)


def _to_openai_messages(messages: list[Message]) -> list[dict]:  # type: ignore[type-arg]
    return [{"role": m.role, "content": m.content} for m in messages]


class OpenAILLMProvider(BaseLLMProvider):
    """OpenAI chat completions with retry, fallback, and optional JSON mode."""

    def __init__(self, config: OpenAIConfig) -> None:
        self._config = config
        self._client = AsyncOpenAI(api_key=config.api_key.get_secret_value())

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        model = request.model or self._config.primary_model
        fallback = request.fallback_model or self._config.fallback_model

        try:
            return await self._generate_with_model(request, model, fallback_triggered=False)
        except Exception as primary_err:
            if fallback and fallback != model:
                logger.warning(
                    "llm_primary_failed_using_fallback",
                    primary=model,
                    fallback=fallback,
                    error=str(primary_err),
                )
                return await self._generate_with_model(request, fallback, fallback_triggered=True)
            raise

    async def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        model = request.model or self._config.primary_model
        kwargs: dict = {
            "model": model,
            "messages": _to_openai_messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        async with await self._client.chat.completions.create(**kwargs) as stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

    # ── Private ───────────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(RateLimitError),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(4),
    )
    async def _generate_with_model(
        self,
        request: GenerationRequest,
        model: str,
        fallback_triggered: bool,
    ) -> GenerationResponse:
        kwargs: dict = {
            "model": model,
            "messages": _to_openai_messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except APIStatusError as e:
            # 4xx errors (auth, invalid request) — don't retry
            if 400 <= e.status_code < 500 and e.status_code != 429:
                raise
            raise  # 5xx or 429 — tenacity will retry if applicable

        content = response.choices[0].message.content or ""
        usage = response.usage

        logger.debug(
            "llm_generate",
            model=model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            fallback=fallback_triggered,
        )

        return GenerationResponse(
            content=content,
            model_used=model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            fallback_triggered=fallback_triggered,
        )


def parse_json_response(content: str) -> dict:  # type: ignore[type-arg]
    """
    Parse JSON from an LLM response, stripping markdown code fences if present.

    Even with json_mode=True, some model versions wrap JSON in ```json fences.
    This is a belt-and-suspenders guard so callers don't need to handle it.
    """
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Drop first line (```json or ```) and last line (```)
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(text)
