"""
HTTP request and response schemas for the Atlas API.

Design rationale:
    These are separate from the internal interfaces (atlas.interfaces.*) by
    design. Internal models carry operational detail (chunk vectors, raw
    metadata dicts) that should never leak into the public API contract.
    Separating them lets us evolve the internal pipeline without breaking
    API consumers, and vice-versa.

    Citation is rendered as a flat list in the response rather than a dict
    keyed by citation number — more ergonomic for frontend consumers who want
    to render a numbered reference list without extra parsing.

    The streaming endpoint returns newline-delimited text/event-stream chunks,
    not JSON — streaming JSON is complex and provides no benefit for token-by-
    token delivery. Clients should concatenate deltas to reconstruct the full
    answer.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── /query ────────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096, description="User question")
    namespace: str = Field("default", min_length=1, max_length=64, description="Corpus namespace to query")
    stream: bool = Field(False, description="Enable token-by-token streaming response")
    top_k: int = Field(5, ge=1, le=50, description="Max chunks to retrieve")


class CitationResponse(BaseModel):
    number: int
    chunk_id: str
    source: str
    page_number: int | None = None


class StageTimings(BaseModel):
    routing_ms: float | None = None
    retrieval_ms: float | None = None
    grading_ms: float | None = None
    generation_ms: float | None = None
    faithfulness_ms: float | None = None
    total_ms: float


class QueryResponse(BaseModel):
    query: str
    answer: str
    classification: str
    citations: list[CitationResponse]
    is_faithful: bool
    faithfulness_score: float | None
    retrieved_chunk_ids: list[str]
    timings: StageTimings
    token_usage: TokenUsage
    grader_retries: int = 0
    cached: bool = False


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


# ── /ingest ───────────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    path: str = Field(..., description="Absolute path or directory to index")
    namespace: str = Field("default", min_length=1, max_length=64, description="Corpus namespace to index into")
    glob: str = Field("**/*", description="Glob pattern when path is a directory")


class IngestResponse(BaseModel):
    documents_processed: int
    documents_skipped: int
    chunks_indexed: int
    total_tokens: int
    duration_seconds: float


# ── /health ───────────────────────────────────────────────────────────────────

class ComponentHealth(BaseModel):
    status: str          # "ok" | "degraded" | "down"
    latency_ms: float | None = None
    detail: str = ""


class HealthResponse(BaseModel):
    status: str          # "ok" | "degraded" | "down"
    version: str
    components: dict[str, ComponentHealth]


# ── /namespaces ───────────────────────────────────────────────────────────────

class NamespaceInfo(BaseModel):
    name: str
    collection: str


class NamespaceListResponse(BaseModel):
    namespaces: list[NamespaceInfo]
    total: int


# ── /keys + /usage ────────────────────────────────────────────────────────────

class KeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Human label for this key")
    email: str = Field("", description="Owner email (optional)")
    rate_limit_rpm: int = Field(60, ge=1, le=10000, description="Requests per minute")


class KeyCreateResponse(BaseModel):
    key: str          # shown once — never retrievable again
    key_id: int
    name: str
    rate_limit_rpm: int


class NamespaceUsage(BaseModel):
    namespace: str
    queries: int


class UsageResponse(BaseModel):
    total_queries: int
    cache_hits: int
    total_prompt_tokens: int
    total_completion_tokens: int
    avg_latency_ms: float
    first_query_at: float | None
    last_query_at: float | None
    by_namespace: list[NamespaceUsage]


# ── Error ─────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    error: str
    detail: str = ""
    request_id: str = ""
