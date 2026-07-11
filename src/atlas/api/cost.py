"""
Token cost estimation.

Design rationale:
    Cost estimation is intentionally a best-effort lookup rather than an exact
    figure — prices change and multi-model pipelines make exact accounting
    complex. We surface estimated_cost_usd in the API response and Prometheus
    so operators can budget and alert, not to invoice end users.

    Prices are per 1 million tokens (OpenAI's billing unit as of mid-2025).
    Using a frozen dict at module level means no I/O on the hot path.

    Embedding cost is tracked separately because embedding_model differs from
    the chat model. The embedder returns total_tokens in EmbeddingResult, which
    the dependency layer passes to estimate_cost() alongside chat token counts.
"""

from __future__ import annotations

# (input_per_1M_usd, output_per_1M_usd)
_CHAT_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o":               (5.00,  15.00),
    "gpt-4o-mini":          (0.15,   0.60),
    "gpt-4-turbo":         (10.00,  30.00),
    "gpt-3.5-turbo":        (0.50,   1.50),
}

# Per 1M tokens (no output for embeddings)
_EMBEDDING_PRICES: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}

_DEFAULT_CHAT_PRICE = (1.00, 3.00)   # conservative fallback for unknown models
_DEFAULT_EMBED_PRICE = 0.10


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    embedding_model: str = "",
    embedding_tokens: int = 0,
) -> float:
    """Return estimated cost in USD for one pipeline invocation."""
    inp, out = _CHAT_PRICES.get(model, _DEFAULT_CHAT_PRICE)
    chat_cost = (prompt_tokens * inp + completion_tokens * out) / 1_000_000

    embed_price = _EMBEDDING_PRICES.get(embedding_model, _DEFAULT_EMBED_PRICE)
    embed_cost = embedding_tokens * embed_price / 1_000_000

    return round(chat_cost + embed_cost, 8)
