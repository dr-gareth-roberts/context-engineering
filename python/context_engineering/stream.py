"""Stream module: async generator variant of pack.

Yields items one at a time as they are selected, useful for large item sets.
"""

from __future__ import annotations

from typing import AsyncGenerator, List, Optional

from .core import (
    Budget,
    ContextItem,
    ScoringWeights,
    _apply_compression,
    calculate_weighted_score,
    estimate_tokens,
    validate_budget,
)


async def pack_stream(
    items: List[ContextItem],
    budget: Budget,
    weights: Optional[ScoringWeights] = None,
    provider: Optional[str] = None,
    *,
    allow_compression: bool = True,
) -> AsyncGenerator[ContextItem, None]:
    """Stream-pack context items, yielding each selected item as chosen.

    Same greedy algorithm as pack() but yields items one at a time via
    async generator. Useful for large item sets where you want to start
    processing selected items before packing completes. Like pack(), an
    explicit ``item.score`` is honoured and oversized items are compressed
    to fit when ``allow_compression`` is set (the default).

    Args:
        items: Context items to pack.
        budget: Token budget.
        weights: Optional scoring weights.
        provider: Optional provider for token estimation.
        allow_compression: Try item compressions when an item is too large.

    Yields:
        Selected ContextItems in score order.

    Raises:
        ValidationError: If budget.maxTokens <= 0 or budget.reserveTokens < 0.
        BudgetExceededError: If reserveTokens >= maxTokens.
    """
    validate_budget(budget)

    max_tokens = budget.max_tokens - (budget.reserve_tokens or 0)

    scored = []
    for item in items:
        tokens = (
            item.tokens
            if item.tokens is not None
            else estimate_tokens(item.content, provider=provider)
        )
        score = item.score if item.score is not None else calculate_weighted_score(item, weights)
        scored.append(item.model_copy(update={"tokens": tokens, "score": score}))

    scored.sort(key=lambda x: (x.score or 0, x.recency or 0), reverse=True)

    remaining = max(0, max_tokens)

    for item in scored:
        if (item.tokens or 0) <= remaining:
            remaining -= item.tokens or 0
            yield item
            continue
        if allow_compression:
            compressed = _apply_compression(item, remaining, provider)
            if compressed is not None:
                remaining -= compressed.tokens or 0
                yield compressed
