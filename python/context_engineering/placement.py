"""Placement module: position-aware context ordering.

Reorders selected items so highest-scored ones land at positions where
the model pays most attention (typically start and end of context).

Based on "Lost in the Middle" (Liu et al. 2023) and attention research.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

from .core import ContextItem


@dataclass
class AttentionProfile:
    """Attention profile for a model family."""

    name: str
    effective_capacity: float
    position_weights: List[float]


ATTENTION_PROFILES: Dict[str, AttentionProfile] = {
    "claude": AttentionProfile(
        name="claude",
        effective_capacity=0.70,
        position_weights=[1.0, 0.85, 0.65, 0.55, 0.50, 0.50, 0.55, 0.65, 0.80, 0.95],
    ),
    "gpt4": AttentionProfile(
        name="gpt4",
        effective_capacity=0.65,
        position_weights=[0.90, 0.75, 0.60, 0.50, 0.45, 0.45, 0.50, 0.60, 0.80, 1.0],
    ),
    "default": AttentionProfile(
        name="default",
        effective_capacity=0.70,
        position_weights=[0.95, 0.80, 0.65, 0.55, 0.50, 0.50, 0.55, 0.65, 0.80, 0.95],
    ),
}


def place_items(
    items: List[ContextItem],
    strategy: str = "score-order",
    model: Optional[str] = None,
    profile: Optional[AttentionProfile] = None,
) -> List[ContextItem]:
    """Reorder selected items for optimal attention placement.

    With "attention-optimized": places highest-priority items at positions
    where the model pays most attention (start and end), and lower-priority
    items in the middle.

    Args:
        items: Items already selected by pack(), in score order.
        strategy: "score-order" (default) or "attention-optimized".
        model: Model family for attention profile.
        profile: Custom attention profile (overrides model).

    Returns:
        Items reordered for optimal attention.
    """
    if strategy == "score-order" or len(items) <= 2:
        return list(items)

    prof = profile or ATTENTION_PROFILES.get(model or "default") or ATTENTION_PROFILES["default"]

    n = len(items)
    bucket_count = len(prof.position_weights)

    sorted_by_score = sorted(
        enumerate(items),
        key=lambda pair: pair[1].score or 0,
        reverse=True,
    )

    position_attention = []
    for i in range(n):
        bucket_index = min(int((i / n) * bucket_count), bucket_count - 1)
        position_attention.append((i, prof.position_weights[bucket_index]))

    position_attention.sort(key=lambda pa: pa[1], reverse=True)

    result: List[Optional[ContextItem]] = [None] * n
    for rank, (orig_idx, item) in enumerate(sorted_by_score):
        target_pos = position_attention[rank][0]
        result[target_pos] = item

    return [item for item in result if item is not None]


def effective_budget(advertised_tokens: int, model: Optional[str] = None) -> int:
    """Get the effective token budget, accounting for context degradation.

    Args:
        advertised_tokens: The model's advertised context window.
        model: Model family name ("claude", "gpt4", etc.).

    Returns:
        Recommended effective token limit.
    """
    prof = ATTENTION_PROFILES.get(model or "default") or ATTENTION_PROFILES["default"]
    return math.floor(advertised_tokens * prof.effective_capacity)
