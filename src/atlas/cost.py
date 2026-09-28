"""
Token cost estimation.

Lives at the top level rather than under `atlas.api` because the eval
reporter prices a run too, and importing `atlas.api.cost` pulls in
`atlas/api/__init__`, which builds the FastAPI app. Prices are not an API
concern; they are what a token costs.

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

from collections.abc import Mapping

from atlas.usage import ModelUsage

# (input_per_1M_usd, output_per_1M_usd)
_CHAT_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o":               (5.00,  15.00),
    "gpt-4o-mini":          (0.15,   0.60),
    "gpt-4-turbo":         (10.00,  30.00),
    "gpt-3.5-turbo":        (0.50,   1.50),
    # Gemini via the OpenAI-compatible endpoint
    "gemini-3.1-flash-lite": (0.25,  1.50),
}

# Per 1M tokens (no output for embeddings)
_EMBEDDING_PRICES: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
    "gemini-embedding-001": 0.15,
}

_DEFAULT_CHAT_PRICE = (1.00, 3.00)   # conservative fallback for unknown models
_DEFAULT_EMBED_PRICE = 0.10

# For the second figure on a report only. Prices are quoted in USD and that
# is the number derived from them; this is a convenience for a budget that is
# kept in rupees, at a rate noted on the day it was written (2026-09-28) and
# never read by anything that decides whether to spend.
USD_TO_INR = 88.0


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


def estimate_usage_cost(usage: Mapping[str, ModelUsage]) -> float:
    """Price a whole run or request from its per-model token counts.

    The per-model breakdown is what makes this answerable at all: a run's
    tokens are split across a chat model and an embedding model whose prices
    differ by more than an order of magnitude, so one total cannot be priced.
    `ModelUsage.kind` decides which table to read, rather than the model name,
    which would send an unrecognised embedding model to the chat fallback
    price and overstate it ~10x.
    """
    total = 0.0
    for model, entry in usage.items():
        if entry.kind == "embedding":
            price = _EMBEDDING_PRICES.get(model, _DEFAULT_EMBED_PRICE)
            total += entry.prompt_tokens * price / 1_000_000
        else:
            inp, out = _CHAT_PRICES.get(model, _DEFAULT_CHAT_PRICE)
            total += (entry.prompt_tokens * inp + entry.completion_tokens * out) / 1_000_000
    return round(total, 8)
