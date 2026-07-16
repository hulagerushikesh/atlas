"""
Central configuration via pydantic-settings.

Design rationale:
    A single Settings object is constructed once at import time (or lazily via
    get_settings()) and injected wherever needed. This gives us:
      - Type-safe, validated config with clear defaults.
      - Easy overrides in tests (Settings(openai_api_key="test")).
      - No scattered os.getenv() calls that are hard to grep.

    Nested sub-models (QdrantConfig, RedisConfig, …) group related settings so
    callers only import what they need without coupling modules.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file (src/atlas/config.py → project root)
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class QdrantConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QDRANT_", env_file=_ENV_FILE, extra="ignore")

    url: str = "http://localhost:6333"
    collection_name: str = "atlas_chunks"
    api_key: SecretStr | None = None


class RedisConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_", env_file=_ENV_FILE, extra="ignore")

    url: str = "redis://localhost:6379"
    cache_ttl_seconds: int = 3600


class OpenAIConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENAI_", env_file=_ENV_FILE, extra="ignore")

    api_key: SecretStr = Field(..., description="OpenAI API key")
    primary_model: str = "gpt-4o-mini"
    fallback_model: str = "gpt-3.5-turbo"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536


class ChunkingConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHUNK_", env_file=_ENV_FILE, extra="ignore")

    strategy: Literal["fixed", "recursive", "semantic"] = "recursive"
    size: int = 512
    overlap: int = 64


class RetrievalConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RETRIEVAL_", env_file=_ENV_FILE, extra="ignore")

    top_k: int = 20  # candidates from each retriever before fusion


class RerankerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RERANKER_", env_file=_ENV_FILE, extra="ignore")

    top_k: int = 5
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class APIConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="API_", env_file=_ENV_FILE, extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1


class Settings(BaseSettings):
    """Top-level settings aggregating all sub-configs."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    log_level: str = "INFO"
    enable_prometheus: bool = True

    # Auth (disabled by default — set AUTH_ENABLED=true in .env to require keys)
    auth_enabled: bool = False
    admin_secret: str = ""           # required to call POST /keys when auth is enabled

    # Sub-configs are instantiated here; in tests you can pass them directly.
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    api: APIConfig = Field(default_factory=APIConfig)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Cached singleton — safe to call at module level.
    Clear with get_settings.cache_clear() in tests to pick up overrides.
    """
    return Settings()
