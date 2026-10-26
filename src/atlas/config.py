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

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file (src/atlas/config.py → project root)
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class QdrantConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QDRANT_", env_file=_ENV_FILE, extra="ignore")

    url: str = "http://localhost:6333"
    collection_name: str = "atlas_chunks"
    api_key: SecretStr | None = None
    # qdrant-client passes no timeout to httpx unless given one, so the
    # default was httpx's 5s. An upsert batch is 100 points of 1536 floats,
    # several documents go at once, and Qdrant Cloud is a region away: 5s is
    # under the honest round trip, not a margin over it. 37 of 155 files
    # failed that way on 2026-09-28.
    timeout_seconds: int = 60


class RedisConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_", env_file=_ENV_FILE, extra="ignore")

    url: str = "redis://localhost:6379"
    cache_ttl_seconds: int = 3600


class OpenAIConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENAI_", env_file=_ENV_FILE, extra="ignore")

    api_key: SecretStr = Field(..., description="API key for the OpenAI-compatible provider")
    # Any OpenAI-compatible endpoint. None = api.openai.com. Gemini:
    # https://generativelanguage.googleapis.com/v1beta/openai/
    base_url: str | None = None
    primary_model: str = "gpt-4o-mini"
    fallback_model: str = "gpt-3.5-turbo"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    # Inputs per embeddings request. OpenAI allows 2048; Gemini caps at 100.
    embedding_batch_size: int = 100


class ChunkingConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHUNK_", env_file=_ENV_FILE, extra="ignore")

    strategy: Literal["fixed", "recursive", "semantic"] = "recursive"
    size: int = 512
    overlap: int = 64
    # Prepend each chunk's source path and heading trail to its indexed text.
    # A flag rather than unconditional because turning it off is the only way
    # to reproduce a pre-2026-09-27 index, and because it changes every
    # content_hash in the corpus — flipping it means paying for a re-ingest.
    context_headers: bool = True


class RetrievalConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RETRIEVAL_", env_file=_ENV_FILE, extra="ignore")

    top_k: int = 20  # candidates from each retriever before fusion

    # How long a process may trust its own keyword index without re-checking
    # it against the vector store.
    #
    # The two halves of a namespace live in different places: the dense half
    # in Qdrant, which every instance shares, and the sparse half on the
    # instance's own filesystem, which Cloud Run discards on recycle. So an
    # upload served by one instance was invisible to the other until this
    # existed. The reconciler compares counts and rebuilds the sparse half
    # from Qdrant when they disagree; this is how stale that comparison is
    # allowed to get, and therefore the worst-case delay before every
    # instance can keyword-retrieve a document any one of them indexed.
    #
    # 0 re-checks on every request -- correct, and one extra Qdrant round
    # trip per query (~0.7 s from asia-south1 to a us-west-1 cluster), which
    # is why it is not the default.
    sparse_sync_ttl_seconds: float = 60.0


# What the router is told when nothing describes the corpus. Deliberately
# contentless: it says "whatever was ingested", so the classifier judges the
# question on its own terms rather than against someone else's corpus.
GENERIC_DOMAIN = "the documents that have been ingested into this knowledge base"


class RouterConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROUTER_", env_file=_ENV_FILE, extra="ignore")

    # What the knowledge base covers, in one sentence. The router uses it to
    # decide what is out of scope; without it a generic prompt rejected every
    # FastAPI question as "general coding help" on the first live run.
    domain: str = GENERIC_DOMAIN
    # Which namespace `domain` describes. A namespace is a separate corpus, so
    # one prose description cannot be true of all of them -- and the failure is
    # silent in the worst way: on 2026-10-13 a corpus uploaded through the
    # console was refused at the router ("not concepts defined by the FastAPI
    # framework") before retrieval ever ran, and the console then told the user
    # the sheet had no references covering it. It had exactly those references.
    # Every other namespace gets GENERIC_DOMAIN unless this names it.
    domain_namespace: str = "default"

    def domain_for(self, namespace: str) -> str:
        """The domain sentence to classify against for *namespace*."""
        return self.domain if namespace == self.domain_namespace else GENERIC_DOMAIN

    def describes(self, namespace: str) -> bool:
        """
        Whether `domain` makes a specific claim about what *namespace* holds.

        `domain_namespace` alone is not enough to answer this. It is "default"
        out of the box, so on a laptop with no ROUTER_DOMAIN set it names a
        namespace whose description is GENERIC_DOMAIN -- a sentence that
        claims nothing and therefore cannot be contradicted by anything
        written into the corpus. Only a *specific* description can be made
        false by an upload, and only then is there anything to protect.

        This is what separates a deployment where ingesting into `default`
        is ordinary from one where it silently breaks routing.
        """
        return namespace == self.domain_namespace and self.domain != GENERIC_DOMAIN


class GraderConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRADER_", env_file=_ENV_FILE, extra="ignore")

    threshold: float = 0.5
    # How many retrieved chunks the grader is shown. None means all of them.
    #
    # 5, against a 15-chunk window, and deliberately. The obvious reading is
    # that this is a bug — the generator is handed all 15, so the grader is
    # answering "is the top 5 sufficient?" while the pipeline treats the
    # answer as "is the context sufficient?". It was changed to None on that
    # reasoning on 2026-09-28 and the A/B put it straight back:
    #
    #     window          precision   recall   faithfulness
    #     5  (this)          0.4667   0.9378         1.0000
    #     15 (all)           0.4622   0.8778         0.9667
    #
    # Recall -0.060, three times the significance floor, and all of it two
    # rows: fq-006 1.000 -> 0.500 and fq-012 0.400 -> 0.000. Both are the
    # multi-document questions, which is the mechanism. A grader shown a
    # slice is pessimistic; pessimism triggers a retry; and since the retry
    # union shipped on 2026-09-27 a retry *accumulates* context instead of
    # replacing it. So the narrow window is how a question whose answer
    # spans five pages ever collects five pages. Widening it suppressed the
    # retries and the union never formed.
    #
    # Keep this at 5 unless the retry union changes. `--set
    # grader.context_chunks=15` re-runs the experiment.
    context_chunks: int | None = 5

    @field_validator("context_chunks", mode="before")
    @classmethod
    def _blank_means_all(cls, value: object) -> object:
        """`GRADER_CONTEXT_CHUNKS=` in a .env is "no cap", not a parse error.

        Blank is how every other optional in .env.example says "unset"
        (`QDRANT_API_KEY=`), and an int field rejects it outright — so a line
        copied from the example crashed `get_settings()` at import, before
        anything could report which variable was at fault.
        """
        return None if isinstance(value, str) and not value.strip() else value


class RerankerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RERANKER_", env_file=_ENV_FILE, extra="ignore")

    # False skips the cross-encoder entirely (RRF order is final). Mainly an
    # eval knob: `--set reranker.enabled=false` for the reranker-off A/B.
    enabled: bool = True
    # 15, not 5. Measured 2026-09-23: context recall 0.778 -> 0.900 end to end
    # with faithfulness unchanged at 1.000. The three documents that survived
    # every M1 miss were already in the candidate set, just below rank 5.
    # Context precision falls to 0.302, which is mostly the denominator: one
    # relevant document per question over a 15-slot window caps it low.
    top_k: int = 15
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    # How many (query, document) pairs go through the model at once. Peak
    # memory scales with this times the sequence length, and the sequence
    # length is not ours to control: HyDE concatenates a hypothesis of up to
    # 220 tokens onto every query, which lengthens every pair in the batch.
    # On 2026-10-17 a HyDE eval on an 18 GB laptop died on two samples with
    # "MPS backend out of memory" while the same corpus and the same reranker
    # had just completed the baseline, and the run still rendered as 16 clean
    # samples. 16 rather than sentence-transformers' default 32, because the
    # measured cost of halving it is latency this pipeline already spends
    # seconds of elsewhere, and the cost of guessing high is a dead sample.
    batch_size: int = 16
    # None lets sentence-transformers choose (MPS on Apple silicon, CUDA on a
    # GPU box, CPU otherwise). Set it to "cpu" to take the reranker out of a
    # contended GPU: unified memory means a browser can evict a model.
    # Changing it changes which arithmetic runs, so an A/B must not change it
    # between arms.
    device: str | None = None


class HyDEConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HYDE_", env_file=_ENV_FILE, extra="ignore")

    # Hypothetical Document Embeddings: write a passage that would answer the
    # query, then retrieve with that instead of (or alongside) the question.
    #
    # Off by default, and this is the third intervention aimed at the same
    # row. `fq-012` asks how to add string validation to a query parameter.
    # The pages that answer it say `Query`, `Annotated`, `min_length`,
    # `Pydantic` — and the question says none of those words. Retrieval
    # ranked pages by how often they happen to mention "pydantic": 15 on
    # `tutorial/body` (retrieved), 0 on `tutorial/path-params-numeric-
    # validations` (not retrieved). That is a vocabulary gap, not a ranking
    # one.
    #
    # Context headers were the first attempt and bought precision, not this
    # row. Decomposition was the second, and a ₹0.023 probe on 2026-09-29
    # settled it: the decomposer splits a question, it does not translate
    # one, so all three shards led with "Pydantic" and scored what the live
    # run already scored. HyDE is the only remaining candidate that changes
    # the words being searched with rather than how many searches happen.
    enabled: bool = False
    # "concat" keeps the question in front of the hypothesis; "replace" sends
    # the hypothesis alone, which is what the HyDE paper does.
    #
    # Default is concat because this retriever is hybrid. The paper assumes a
    # dense index, where replacing costs nothing; here BM25 sees the same
    # string, and a bare hypothesis strips the question's own rare terms out
    # of the sparse query. Concat is the conservative version — everything
    # BM25 matched before is still in the text — and `--set hyde.mode=replace`
    # runs the paper's.
    mode: Literal["concat", "replace"] = "concat"
    # A cap, not a target. A long hypothesis is a long BM25 query, and BM25
    # has no way to tell a probe's padding from its content.
    max_tokens: int = 220


class BudgetConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BUDGET_", env_file=_ENV_FILE, extra="ignore")

    # Hard cap on estimated API spend per UTC day, in USD. 0 disables it.
    # Requests past the cap get 429 until midnight UTC. See atlas.api.budget.
    daily_usd: float = 0.0
    # Where the day's total lives. "auto" = Redis if connected, else in-process
    # (per-instance, so it resets on a Cloud Run cold start). "firestore" makes
    # it durable without a Redis. See atlas.api.spendstore.
    store: Literal["auto", "memory", "redis", "firestore"] = "auto"


class APIConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="API_", env_file=_ENV_FILE, extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1


class IngestConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INGEST_", env_file=_ENV_FILE, extra="ignore")

    # The only directory `POST /ingest` will read a caller-supplied path from.
    # That endpoint takes a path on the *server*, so without this an authorised
    # caller could name any file the process can read and then retrieve it
    # through /query -- the index is a read-back channel. Confined to the
    # corpus directory by default; set INGEST_ROOT="" to allow any path, which
    # is only reasonable when the API is a single-user process on a laptop.
    root: str = "data"

    # Upload limits. The console cannot send a server path, so uploads are how
    # a corpus is built from a browser; these bound what one request can cost.
    # A rejected file is reported by name rather than dropped, because a
    # partial ingest that reports success is how a corpus goes quietly short.
    max_upload_files: int = 50
    max_upload_bytes: int = 20 * 1024 * 1024
    max_upload_total_bytes: int = 100 * 1024 * 1024


class Settings(BaseSettings):
    """Top-level settings aggregating all sub-configs."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    log_level: str = "INFO"
    enable_prometheus: bool = True
    sentry_dsn: str = ""             # optional: set to enable Sentry error tracking

    # Auth (disabled by default — set AUTH_ENABLED=true in .env to require keys)
    auth_enabled: bool = False
    admin_secret: str = ""           # required to call POST /keys when auth is enabled
    # Where API keys live: "sqlite" (data/atlas.db, one box) or "firestore"
    # (Cloud Run — the disk is ephemeral). Firestore uses the runtime's
    # service account; AUTH_FIRESTORE_PROJECT only when it differs from ADC.
    auth_store: Literal["sqlite", "firestore"] = "sqlite"
    auth_firestore_project: str = ""

    # Sub-configs are instantiated here; in tests you can pass them directly.
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)  # type: ignore[arg-type]
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    grader: GraderConfig = Field(default_factory=GraderConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    hyde: HyDEConfig = Field(default_factory=HyDEConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    ingest: IngestConfig = Field(default_factory=IngestConfig)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Cached singleton — safe to call at module level.
    Clear with get_settings.cache_clear() in tests to pick up overrides.
    """
    return Settings()
