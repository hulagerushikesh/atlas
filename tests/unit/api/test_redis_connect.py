"""
connect_redis — the seam between "Redis is absent" and "Redis is broken".

Both end with no client, but they are different facts: Cloud Run runs with
REDIS_URL empty on purpose, while a wrong URL is a misconfiguration worth a
warning. What matters to the rest of the app is that neither ever yields a
client object, because a half-dead client makes every cache call raise and
holds /health at "degraded".
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from atlas.api.app import connect_redis
from atlas.config import OpenAIConfig, RedisConfig, Settings


def _settings(url: str) -> Settings:
    return Settings(  # type: ignore[call-arg]
        openai=OpenAIConfig(api_key="test"),  # type: ignore[call-arg]
        redis=RedisConfig(url=url),
    )


class TestConnectRedis:
    async def test_empty_url_skips_connection_entirely(self) -> None:
        with patch("redis.asyncio.from_url") as from_url:
            assert await connect_redis(_settings("")) is None
        from_url.assert_not_called()

    async def test_live_client_is_returned(self) -> None:
        client = AsyncMock()
        with patch("redis.asyncio.from_url", return_value=client):
            assert await connect_redis(_settings("redis://localhost:6379")) is client
        client.ping.assert_awaited_once()

    async def test_failed_ping_discards_the_client(self) -> None:
        client = AsyncMock()
        client.ping.side_effect = ConnectionError("Connection refused")
        with patch("redis.asyncio.from_url", return_value=client):
            assert await connect_redis(_settings("redis://nope:6379")) is None

    @pytest.mark.parametrize("exc", [ImportError("no redis"), ValueError("bad url")])
    async def test_construction_failure_is_not_fatal(self, exc: Exception) -> None:
        with patch("redis.asyncio.from_url", side_effect=exc):
            assert await connect_redis(_settings("redis://localhost:6379")) is None
