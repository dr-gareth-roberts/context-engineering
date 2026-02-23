"""
Cost Estimation with Cache Savings

Estimates actual API costs for context packs, with special support
for prefix caching savings. Given a CacheAwarePack, shows concrete
dollar amounts saved by cache-topology-aware packing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .cache_topology import CacheAwarePack


@dataclass
class ModelPricing:
    """Pricing per million tokens for a model."""
    input_per_million: float
    cached_input_per_million: float
    output_per_million: float


@dataclass
class CostEstimate:
    """Cost estimate for a single request."""
    model: str
    input_tokens: int
    cached_tokens: int
    uncached_tokens: int
    output_tokens: int
    cost_without_cache: float
    cost_with_cache: float
    savings: float
    savings_percent: float
    cache_efficiency: float


@dataclass
class MonthlyEstimate:
    requests_per_day: int
    monthly_cost_without_cache: float
    monthly_cost_with_cache: float
    monthly_savings: float


@dataclass
class CostProjection:
    """Cost projection over multiple requests."""
    per_request: CostEstimate
    request_count: int
    total_without_cache: float
    total_with_cache: float
    total_savings: float
    monthly_estimate: Optional[MonthlyEstimate] = None


MODEL_PRICING: Dict[str, ModelPricing] = {
    # Anthropic
    "claude-opus-4-6": ModelPricing(15, 1.5, 75),
    "claude-sonnet-4-6": ModelPricing(3, 0.3, 15),
    "claude-haiku-4-5": ModelPricing(0.8, 0.08, 4),
    # OpenAI
    "gpt-4.1": ModelPricing(2, 0.5, 8),
    "gpt-4.1-mini": ModelPricing(0.4, 0.1, 1.6),
    "gpt-4o": ModelPricing(2.5, 1.25, 10),
    "o3": ModelPricing(2, 0.5, 8),
    "o4-mini": ModelPricing(1.1, 0.275, 4.4),
}


def estimate_cost(
    pack: CacheAwarePack,
    model: str,
    output_tokens: int = 500,
    pricing: Optional[ModelPricing] = None,
) -> CostEstimate:
    """Estimate the cost of a single API request using a cache-aware pack.

    Args:
        pack: Cache-aware pack result from pack_with_cache_topology
        model: Model name for pricing lookup
        output_tokens: Estimated output tokens (default: 500)
        pricing: Custom pricing (overrides MODEL_PRICING lookup)

    Example:
        pack = pack_with_cache_topology(items, budget)
        cost = estimate_cost(pack, "claude-sonnet-4-6")
        print(f"Saving ${cost.savings:.4f} per request ({cost.savings_percent:.1f}%)")
    """
    price = pricing or MODEL_PRICING.get(model)
    if not price:
        models = ", ".join(MODEL_PRICING.keys())
        raise ValueError(f'Unknown model "{model}". Pass custom pricing or use one of: {models}')

    cached = pack.cacheable_tokens
    uncached = pack.volatile_tokens

    cost_without = (
        (pack.total_tokens / 1_000_000) * price.input_per_million
        + (output_tokens / 1_000_000) * price.output_per_million
    )
    cost_with = (
        (cached / 1_000_000) * price.cached_input_per_million
        + (uncached / 1_000_000) * price.input_per_million
        + (output_tokens / 1_000_000) * price.output_per_million
    )

    savings = cost_without - cost_with

    return CostEstimate(
        model=model,
        input_tokens=pack.total_tokens,
        cached_tokens=cached,
        uncached_tokens=uncached,
        output_tokens=output_tokens,
        cost_without_cache=round(cost_without, 6),
        cost_with_cache=round(cost_with, 6),
        savings=round(savings, 6),
        savings_percent=round((savings / cost_without) * 100, 1) if cost_without > 0 else 0,
        cache_efficiency=pack.cache_efficiency,
    )


def project_costs(
    pack: CacheAwarePack,
    model: str,
    request_count: int,
    output_tokens: int = 500,
    requests_per_day: Optional[int] = None,
    pricing: Optional[ModelPricing] = None,
) -> CostProjection:
    """Project costs over multiple requests.

    Args:
        pack: Cache-aware pack result
        model: Model name
        request_count: Number of requests to project
        output_tokens: Estimated output tokens per request
        requests_per_day: If set, includes monthly projection
        pricing: Custom pricing

    Example:
        projection = project_costs(pack, "claude-sonnet-4-6", 1000, requests_per_day=500)
        print(f"Monthly savings: ${projection.monthly_estimate.monthly_savings:.2f}")
    """
    per_request = estimate_cost(pack, model, output_tokens, pricing)

    total_without = per_request.cost_without_cache * request_count
    total_with = per_request.cost_with_cache * request_count

    monthly = None
    if requests_per_day is not None:
        monthly_requests = requests_per_day * 30
        monthly = MonthlyEstimate(
            requests_per_day=requests_per_day,
            monthly_cost_without_cache=round(per_request.cost_without_cache * monthly_requests, 2),
            monthly_cost_with_cache=round(per_request.cost_with_cache * monthly_requests, 2),
            monthly_savings=round(per_request.savings * monthly_requests, 2),
        )

    return CostProjection(
        per_request=per_request,
        request_count=request_count,
        total_without_cache=round(total_without, 2),
        total_with_cache=round(total_with, 2),
        total_savings=round(total_without - total_with, 2),
        monthly_estimate=monthly,
    )
