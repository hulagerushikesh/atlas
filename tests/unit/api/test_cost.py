"""Tests for cost estimation."""

from atlas.api.cost import estimate_cost


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
