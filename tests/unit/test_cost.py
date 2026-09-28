"""Tests for cost estimation."""

from atlas.cost import estimate_cost, estimate_usage_cost
from atlas.usage import ModelUsage


class TestEstimateCost:
    def test_zero_tokens_zero_cost(self) -> None:
        cost = estimate_cost("gpt-4o-mini", 0, 0)
        assert cost == 0.0

    def test_known_model_uses_correct_price(self) -> None:
        # gpt-4o-mini: $0.15/1M input, $0.60/1M output
        cost = estimate_cost("gpt-4o-mini", 1_000_000, 0)
        assert abs(cost - 0.15) < 1e-6

    def test_unknown_model_uses_fallback(self) -> None:
        cost_known = estimate_cost("gpt-4o-mini", 100_000, 0)
        cost_unknown = estimate_cost("some-future-model", 100_000, 0)
        # The fallback input price ($1.00/1M) is deliberately more conservative
        # than gpt-4o-mini's ($0.15/1M), so an unknown model must cost more.
        assert cost_unknown > cost_known
        assert abs(cost_unknown - 0.10) < 1e-6

    def test_embedding_cost_added(self) -> None:
        cost_no_embed = estimate_cost("gpt-4o-mini", 1000, 500)
        cost_with_embed = estimate_cost(
            "gpt-4o-mini", 1000, 500,
            embedding_model="text-embedding-3-small",
            embedding_tokens=100_000,
        )
        assert cost_with_embed > cost_no_embed

    def test_completion_tokens_more_expensive_than_input(self) -> None:
        input_cost = estimate_cost("gpt-4o", 1_000_000, 0)
        output_cost = estimate_cost("gpt-4o", 0, 1_000_000)
        assert output_cost > input_cost  # output is 3× input for gpt-4o


class TestEstimateUsageCost:
    def test_empty_usage_is_free(self) -> None:
        assert estimate_usage_cost({}) == 0.0

    def test_matches_the_per_call_estimate(self) -> None:
        """The two functions have to agree, or the API response and the eval
        report would price the same tokens differently."""
        usage = {"gpt-4o-mini": ModelUsage(calls=3, prompt_tokens=9000, completion_tokens=800)}
        assert estimate_usage_cost(usage) == estimate_cost("gpt-4o-mini", 9000, 800)

    def test_sums_across_models(self) -> None:
        usage = {
            "gpt-4o-mini": ModelUsage(calls=1, prompt_tokens=1_000_000),
            "text-embedding-3-small": ModelUsage(
                kind="embedding", calls=1, prompt_tokens=1_000_000
            ),
        }
        # $0.15 chat input + $0.02 embedding.
        assert abs(estimate_usage_cost(usage) - 0.17) < 1e-6

    def test_kind_not_the_name_decides_the_price_table(self) -> None:
        """An unrecognised embedding model priced from the chat fallback
        costs 10x what it should; `kind` is stored so the guess is never
        made."""
        unknown_embed = {
            "some-future-embedder": ModelUsage(kind="embedding", calls=1, prompt_tokens=1_000_000)
        }
        unknown_chat = {
            "some-future-chat": ModelUsage(kind="chat", calls=1, prompt_tokens=1_000_000)
        }
        assert abs(estimate_usage_cost(unknown_embed) - 0.10) < 1e-6   # embed fallback
        assert abs(estimate_usage_cost(unknown_chat) - 1.00) < 1e-6    # chat fallback

    def test_embedding_completion_tokens_are_not_charged(self) -> None:
        """An embedding has no completion. If one were ever recorded, it must
        not be silently priced at an output rate."""
        usage = {
            "text-embedding-3-small": ModelUsage(
                kind="embedding", calls=1, prompt_tokens=1_000_000, completion_tokens=1_000_000
            )
        }
        assert abs(estimate_usage_cost(usage) - 0.02) < 1e-6
