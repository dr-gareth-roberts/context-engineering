"""Tests for cost estimation with cache savings."""
import pytest
from context_engineering.core import Budget, ContextItem
from context_engineering.cache_topology import CacheAwarePack
from context_engineering.cost import (
    ModelPricing,
    MODEL_PRICING,
    estimate_cost,
    project_costs,
)


def make_pack(total_tokens: int, cacheable_tokens: int) -> CacheAwarePack:
    return CacheAwarePack(
        budget=Budget(max_tokens=total_tokens + 1000),
        selected=[],
        dropped=[],
        total_tokens=total_tokens,
        stats={},
        cache_key="test",
        cacheable_tokens=cacheable_tokens,
        volatile_tokens=total_tokens - cacheable_tokens,
        cache_efficiency=cacheable_tokens / total_tokens if total_tokens > 0 else 0,
        partition_boundaries=[0, 0],
    )


class TestEstimateCost:
    def test_sonnet(self):
        pack = make_pack(4000, 3000)
        cost = estimate_cost(pack, "claude-sonnet-4-6", output_tokens=500)

        assert cost.model == "claude-sonnet-4-6"
        assert cost.input_tokens == 4000
        assert cost.cached_tokens == 3000
        assert cost.uncached_tokens == 1000
        assert abs(cost.cost_without_cache - 0.0195) < 0.001
        assert abs(cost.cost_with_cache - 0.0114) < 0.001
        assert cost.savings > 0

    def test_opus(self):
        pack = make_pack(8000, 6000)
        cost = estimate_cost(pack, "claude-opus-4-6", output_tokens=1000)

        assert abs(cost.cost_without_cache - 0.195) < 0.001
        assert abs(cost.cost_with_cache - 0.114) < 0.001
        assert cost.savings_percent > 40

    def test_zero_cache(self):
        pack = make_pack(4000, 0)
        cost = estimate_cost(pack, "claude-sonnet-4-6")
        assert cost.savings == 0
        assert cost.cache_efficiency == 0

    def test_full_cache(self):
        pack = make_pack(4000, 4000)
        cost = estimate_cost(pack, "claude-sonnet-4-6")
        assert cost.savings > 0
        assert cost.cache_efficiency == 1.0

    def test_custom_pricing(self):
        pack = make_pack(1000, 500)
        cost = estimate_cost(pack, "custom", pricing=ModelPricing(10, 1, 30))
        assert cost.model == "custom"
        assert cost.savings > 0

    def test_unknown_model(self):
        pack = make_pack(1000, 500)
        with pytest.raises(ValueError, match="Unknown model"):
            estimate_cost(pack, "unknown-model")

    def test_known_models(self):
        assert "claude-opus-4-6" in MODEL_PRICING
        assert "claude-sonnet-4-6" in MODEL_PRICING
        assert "gpt-4.1" in MODEL_PRICING
        assert "gpt-4o" in MODEL_PRICING


class TestProjectCosts:
    def test_projects(self):
        pack = make_pack(4000, 3000)
        proj = project_costs(pack, "claude-sonnet-4-6", 1000)

        assert proj.request_count == 1000
        assert proj.total_without_cache > 0
        assert proj.total_with_cache > 0
        assert proj.total_savings > 0

    def test_monthly_estimate(self):
        pack = make_pack(4000, 3000)
        proj = project_costs(pack, "claude-sonnet-4-6", 1000, requests_per_day=500)

        assert proj.monthly_estimate is not None
        assert proj.monthly_estimate.requests_per_day == 500
        assert proj.monthly_estimate.monthly_savings > 0

    def test_zero_cache(self):
        pack = make_pack(4000, 0)
        proj = project_costs(pack, "claude-sonnet-4-6", 100)
        assert proj.total_savings == 0

    def test_large_scale_opus(self):
        pack = make_pack(8000, 6000)
        proj = project_costs(pack, "claude-opus-4-6", 10000, output_tokens=1000, requests_per_day=1000)
        assert proj.total_savings > 500
        assert proj.monthly_estimate.monthly_savings > 1000
