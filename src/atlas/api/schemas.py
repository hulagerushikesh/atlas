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

from pydantic import BaseModel, Field

# ── /query ────────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096, description="User question")
    namespace: str = Field(
        "default", min_length=1, max_length=64, description="Corpus namespace to query"
    )
    stream: bool = Field(False, description="Enable token-by-token streaming response")
    top_k: int = Field(5, ge=1, le=50, description="Max chunks to retrieve")


class CitationResponse(BaseModel):
    number: int
    chunk_id: str
    source: str
    page_number: int | None = None


class EvidenceResponse(BaseModel):
    """
    One retrieved chunk with its full score trail.

    This is what lets a client show *why* an answer cites what it cites:
    where each chunk came from, how every retrieval stage scored it, and
    whether it reached the generator at all. `scores` keys are stage labels
    (dense, bm25, rrf, rerank); a stage the chunk never reached is absent.
    """

    chunk_id: str
    source: str
    chunk_index: int
    start_char: int
    end_char: int
    page_number: int | None = None
    excerpt: str
    scores: dict[str, float]
    # Survived the rerank cut and was passed to the generator.
    selected: bool
    # Citation number in the answer, when the generator cited it.
    citation: int | None = None


class StageTimings(BaseModel):
    routing_ms: float | None = None
    decompose_ms: float | None = None
    # None unless HyDE is on. Reported apart from retrieval_ms because it is
    # an LLM call, and folding it in would make enabling HyDE read as the
    # vector store having slowed down.
    hyde_ms: float | None = None
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
    # Both null when no verdict was reached — check off, or a refusal, which
    # asserts nothing to ground. Null is not false: nothing was found wrong,
    # nothing was checked. Clients render it as "unchecked".
    is_faithful: bool | None
    faithfulness_score: float | None
    retrieved_chunk_ids: list[str]
    timings: StageTimings
    token_usage: TokenUsage
    grader_retries: int = 0
    cached: bool = False
    sub_queries: list[str] = []
    grader_score: float | None = None
    unsupported_claims: list[str] = []
    evidence: list[EvidenceResponse] = []
    # The hypothetical passages retrieval searched with, when HyDE is on.
    # Empty otherwise. Exposed because a search run on text the caller never
    # wrote is not debuggable from the query alone.
    hypotheses: list[str] = []


class TokenUsage(BaseModel):
    """Every token this request spent, not just the answer's.

    Before 2026-09-28 these were the generation call's counts alone, so a
    response understated its own cost by roughly half — the router, the
    grader, the faithfulness check and the query embedding were all missing —
    and `estimated_cost_usd` was what the daily spend cap was charged. The cap
    was therefore admitting about twice the spend it was configured for.
    Embedding tokens are counted in `prompt_tokens`; an embedding has no
    completion.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


# ── /ingest ───────────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    path: str = Field(..., description="Absolute path or directory to index")
    namespace: str = Field(
        "default", min_length=1, max_length=64, description="Corpus namespace to index into"
    )
    glob: str = Field("**/*", description="Glob pattern when path is a directory")
    source_root: str | None = Field(
        None,
        description=(
            "Prefix stripped from each chunk's context header. Defaults to the "
            "directory itself, or a single file's parent. Set it explicitly when "
            "adding to a corpus that was ingested from a higher directory, so the "
            "new chunks get the same headers as the ones already indexed."
        ),
    )


class IngestResponse(BaseModel):
    documents_processed: int
    documents_skipped: int
    chunks_indexed: int
    total_tokens: int
    duration_seconds: float


class RejectedUpload(BaseModel):
    """One file the upload would not index, and why."""

    filename: str
    reason: str


class UploadIngestResponse(IngestResponse):
    """
    An upload's result, plus what it refused.

    `rejected` is the reason this is not just IngestResponse. A request that
    drops three of its ten files and reports a cheerful `documents_processed:
    7` is how a corpus goes quietly short -- the caller has no way to tell
    that number from a complete one. Every refusal is named here, and
    `namespace` is echoed because the console lets you type a new one and
    should be able to show what it actually created.
    """

    namespace: str
    accepted: list[str] = []
    rejected: list[RejectedUpload] = []


# ── /health ───────────────────────────────────────────────────────────────────

class ComponentHealth(BaseModel):
    status: str          # "ok" | "degraded" | "down"
    latency_ms: float | None = None
    detail: str = ""


class BudgetStatus(BaseModel):
    daily_usd: float
    spent_today_usd: float


class HealthResponse(BaseModel):
    status: str          # "ok" | "degraded" | "down"
    version: str
    components: dict[str, ComponentHealth]
    budget: BudgetStatus | None = None   # present only when BUDGET_DAILY_USD > 0


# ── /namespaces ───────────────────────────────────────────────────────────────

class NamespaceInfo(BaseModel):
    name: str
    collection: str


class NamespaceListResponse(BaseModel):
    namespaces: list[NamespaceInfo]
    total: int


class SourceInfo(BaseModel):
    source: str
    doc_type: str
    chunks: int


class SourceListResponse(BaseModel):
    namespace: str
    sources: list[SourceInfo]
    total_sources: int
    # The sparse side's count. The BM25 corpus is persisted separately from
    # Qdrant, so it can list documents the vector store cannot answer from;
    # dense_chunks reports the other half rather than letting this one speak
    # for both.
    total_chunks: int
    dense_chunks: int | None = None     # None = Qdrant unreachable, not zero
    consistent: bool | None = None      # None = unknown, not "fine"
    warning: str | None = None
    # False for the one namespace ROUTER_DOMAIN describes, which the ingest
    # endpoints refuse. Carried here because the console reloads this response
    # on every corpus change, so it is the one place that already knows which
    # corpus the user is looking at -- and a drop zone that is going to return
    # 409 should be disabled before the file is chosen, not after.
    writable: bool = True
    # The sentence the router is told, when there is a specific one. Shown as
    # the reason a corpus is read-only, because "read-only" without the claim
    # it is protecting reads as an arbitrary restriction.
    description: str | None = None


# ── /keys + /usage ────────────────────────────────────────────────────────────

class KeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Human label for this key")
    email: str = Field("", description="Owner email (optional)")
    rate_limit_rpm: int = Field(60, ge=1, le=10000, description="Requests per minute")


class KeyCreateResponse(BaseModel):
    key: str          # shown once — never retrievable again
    key_id: int | str
    name: str
    rate_limit_rpm: int


class KeyRecordResponse(BaseModel):
    key_id: int | str
    name: str
    email: str
    is_active: bool
    rate_limit_rpm: int
    created_at: float | None
    total_queries: int
    last_query_at: float | None


class KeyListResponse(BaseModel):
    keys: list[KeyRecordResponse]


class KeyActiveRequest(BaseModel):
    is_active: bool = Field(..., description="False revokes the key; True restores it")


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
