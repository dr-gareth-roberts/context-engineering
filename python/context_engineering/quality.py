"""Quality module: heuristic context quality metrics.

Computes density, diversity, freshness, and redundancy without LLM calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set

from .core import ContextItem, ContextPack, estimate_tokens


@dataclass
class ContextQuality:
    """Quality metrics for a context pack or item set."""

    item_count: int
    total_tokens: int
    density: float
    diversity: float
    freshness: float
    redundancy: float
    overall: float


def analyze_context(items: List[ContextItem]) -> ContextQuality:
    """Analyze the quality of a set of context items.

    Computes density, diversity, freshness, and redundancy metrics
    without requiring an LLM call.

    Args:
        items: Context items to analyze.

    Returns:
        ContextQuality with all metrics computed.
    """
    if not items:
        return ContextQuality(
            item_count=0,
            total_tokens=0,
            density=0.0,
            diversity=0.0,
            freshness=0.0,
            redundancy=0.0,
            overall=0.0,
        )

    total_tokens = sum(item.tokens or estimate_tokens(item.content) for item in items)

    # Density: unique words / total tokens
    all_words: List[str] = []
    for item in items:
        words = [w for w in item.content.lower().split() if w]
        all_words.extend(words)
    unique_words: Set[str] = set(all_words)
    density = min(len(unique_words) / max(total_tokens, 1), 1.0)

    # Diversity: unique bigrams / total bigrams
    bigrams: Set[str] = set()
    total_bigram_count = 0
    for item in items:
        words = [w for w in item.content.lower().split() if w]
        for i in range(len(words) - 1):
            bigrams.add(f"{words[i]} {words[i + 1]}")
            total_bigram_count += 1
    diversity = min(len(bigrams) / total_bigram_count, 1.0) if total_bigram_count > 0 else 0.0

    # Freshness: fraction of items with recency > 5 (on 0-10 scale)
    fresh_count = sum(1 for item in items if (item.recency or 0) > 5)
    freshness = fresh_count / len(items)

    # Redundancy: pairwise Jaccard similarity
    item_word_sets = [
        set(w for w in item.content.lower().split() if len(w) > 2) for item in items
    ]
    total_overlap = 0.0
    pair_count = 0
    for i in range(len(item_word_sets)):
        for j in range(i + 1, len(item_word_sets)):
            a = item_word_sets[i]
            b = item_word_sets[j]
            intersection = len(a & b)
            union = len(a | b)
            if union > 0:
                total_overlap += intersection / union
                pair_count += 1
    redundancy = total_overlap / pair_count if pair_count > 0 else 0.0

    # Overall: weighted combination
    overall = round(
        density * 0.25 + diversity * 0.25 + freshness * 0.20 + (1 - redundancy) * 0.30,
        2,
    )

    return ContextQuality(
        item_count=len(items),
        total_tokens=total_tokens,
        density=round(density, 3),
        diversity=round(diversity, 3),
        freshness=round(freshness, 3),
        redundancy=round(redundancy, 3),
        overall=overall,
    )


def analyze_context_pack(pack: ContextPack) -> ContextQuality:
    """Analyze a ContextPack directly."""
    return analyze_context(pack.selected)
