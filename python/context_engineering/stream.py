"""Stream module: async generator variant of pack.

Yields items one at a time as they are selected, useful for large item sets.
"""
from __future__ import annotations

from typing import AsyncGenerator, List, Optional

from .core import Budget, ContextItem, estimate_tokens, calculate_weighted_score, ScoringWeights


async def pack_stream(
    items: List[ContextItem],
    budget: Budget,
    weights: Optional[ScoringWeights] = None,
    provider: Optional[str] = None,
) -> AsyncGenerator[ContextItem, None]:
    """Stream-pack context items, yielding each selected item as chosen.

    Same greedy algorithm as pack() but yields items one at a time via
    async generator. Useful for large item sets where you want to start
    processing selected items before packing completes.

    Args:
        items: Context items to pack.
        budget: Token budget.
        weights: Optional scoring weights.
        provider: Optional provider for token estimation.

    Yields:
        Selected ContextItems in score order.

    Raises:
        ValueError: If budget is invalid.
    """
    if budget.max_tokens <= 0:
        raise ValueError(f"maxTokens must be positive, got {budget.max_tokens}")
    if budget.reserve_tokens is not None and budget.reserve_tokens >= budget.max_tokens:
        raise ValueError(
            f"reserveTokens ({budget.reserve_tokens}) must be less than "
            f"maxTokens ({budget.max_tokens})"
        )

    max_tokens = budget.max_tokens - (budget.reserve_tokens or 0)

    scored = []
    for item in items:
        tokens = item.tokens or estimate_tokens(item.content, provider=provider)
        score = calculate_weighted_score(item, weights)
        scored.append(item.model_copy(update={"tokens": tokens, "score": score}))

    scored.sort(key=lambda x: (x.score or 0, x.recency or 0), reverse=True)

    remaining = max(0, max_tokens)

    for item in scored:
        if (item.tokens or 0) <= remaining:
            remaining -= item.tokens or 0
            yield item
