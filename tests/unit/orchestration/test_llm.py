"""
Tests for OpenAILLMProvider and parse_json_response utility.

The OpenAI client is mocked via AsyncMock so no API calls are made.
We test: normal generation, json_mode flag, fallback trigger, and the
JSON parsing helper's code-fence stripping.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from atlas.config import OpenAIConfig
from atlas.interfaces.llm import GenerationRequest, Message
from atlas.orchestration.llm import OpenAILLMProvider, parse_json_response


def _config() -> OpenAIConfig:
    return OpenAIConfig(
        api_key="sk-test",
        primary_model="gpt-4o-mini",
        fallback_model="gpt-3.5-turbo",
    )


def _mock_response(content: str, model: str = "gpt-4o-mini") -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 20
    resp.usage.total_tokens = 30
    return resp


@pytest.fixture
def provider() -> OpenAILLMProvider:
    return OpenAILLMProvider(_config())


class TestParseJsonResponse:
    def test_plain_json(self) -> None:
        result = parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_strips_json_fence(self) -> None:
        result = parse_json_response('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_strips_plain_fence(self) -> None:
        result = parse_json_response('```\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_whitespace_stripped(self) -> None:
        result = parse_json_response('  {"a": 1}  ')
        assert result["a"] == 1


class TestOpenAILLMProvider:
    @pytest.mark.asyncio
    async def test_generate_returns_response(self, provider: OpenAILLMProvider) -> None:
        with patch.object(
            provider._client.chat.completions, "create",
            new=AsyncMock(return_value=_mock_response("Hello"))
        ):
            request = GenerationRequest(
                messages=[Message(role="user", content="hi")]
            )
            response = await provider.generate(request)
            assert response.content == "Hello"
            assert response.model_used == "gpt-4o-mini"
            assert response.total_tokens == 30

    @pytest.mark.asyncio
    async def test_json_mode_sets_response_format(self, provider: OpenAILLMProvider) -> None:
        mock_create = AsyncMock(return_value=_mock_response('{"a": 1}'))
        with patch.object(provider._client.chat.completions, "create", new=mock_create):
            request = GenerationRequest(
                messages=[Message(role="user", content="q")],
                json_mode=True,
            )
            await provider.generate(request)
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs.get("response_format") == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_fallback_triggered_on_primary_failure(
        self, provider: OpenAILLMProvider
    ) -> None:
        call_count = 0

        async def side_effect(**kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if kwargs.get("model") == "gpt-4o-mini":
                raise Exception("primary failed")
            return _mock_response("fallback answer", model="gpt-3.5-turbo")

        with patch.object(provider._client.chat.completions, "create", side_effect=side_effect):
            request = GenerationRequest(messages=[Message(role="user", content="q")])
            response = await provider.generate(request)
            assert response.fallback_triggered is True

    @pytest.mark.asyncio
    async def test_no_fallback_on_success(self, provider: OpenAILLMProvider) -> None:
        with patch.object(
            provider._client.chat.completions, "create",
            new=AsyncMock(return_value=_mock_response("ok"))
        ):
            request = GenerationRequest(messages=[Message(role="user", content="q")])
            response = await provider.generate(request)
            assert response.fallback_triggered is False
