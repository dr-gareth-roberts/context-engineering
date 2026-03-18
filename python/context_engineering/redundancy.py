"""Redundancy elimination via embedding similarity or keyword overlap.

Supports two modes:
- Async embedding-based (via AsyncEmbeddingProvider + RedundancyEliminator)
- Sync keyword-based (via eliminate_redundancy_sync with Jaccard similarity)
"""

from __future__ import annotations

from typing import Callable, List, Literal, Optional, Protocol, runtime_checkable

from ._similarity import cosine_similarity
from .bm25 import unicode_tokenize
from .core import ContextItem


@runtime_checkable
class AsyncEmbeddingProvider(Protocol):
    """Protocol for async embedding providers used by RedundancyEliminator.

    This is distinct from ``providers.EmbeddingProvider`` which is sync.
    """

    async def embed(self, texts: List[str]) -> List[List[float]]: ...


class RedundancyConfig:
    def __init__(
        self,
        provider: Optional[AsyncEmbeddingProvider] = None,
        similarity_threshold: float = 0.92,
        strategy: Literal["recent", "summarize", "highest-priority"] = "recent",
        *,
        embedding_provider: Optional[AsyncEmbeddingProvider] = None,
        threshold: Optional[float] = None,
        tokenizer: Optional[Callable[[str], list[str]]] = None,
    ):
        # Support both old (provider/similarity_threshold) and new
        # (embedding_provider/threshold) parameter names.
        self.provider = embedding_provider or provider
        self.embedding_provider = self.provider
        self.similarity_threshold = threshold if threshold is not None else similarity_threshold
        self.threshold = self.similarity_threshold
        self.strategy = strategy
        self.tokenizer = tokenizer


def jaccard_similarity(
    tokens_a: set[str],
    tokens_b: set[str],
) -> float:
    """Compute Jaccard similarity between two token sets.

    Returns 0.0 when both sets are empty.
    """
    if not tokens_a and not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _resolve_survivor(
    cluster_items: list[ContextItem],
    strategy: str,
) -> ContextItem:
    """Pick the surviving item from a redundancy cluster."""
    if strategy == "highest-priority":
        return max(
            cluster_items,
            key=lambda x: (x.priority or 0.0, x.recency or 0.0),
        )
    # "recent" (default) and "summarize" fallback
    return max(
        cluster_items,
        key=lambda x: (x.recency or 0.0, x.priority or 0.0),
    )


def eliminate_redundancy_sync(
    items: list[ContextItem],
    *,
    threshold: float = 0.8,
    strategy: str = "recent",
    tokenizer: Callable[[str], list[str]] | None = None,
) -> list[ContextItem]:
    """Eliminate redundant items using Jaccard similarity on word tokens.

    This is a synchronous, embedding-free alternative to RedundancyEliminator.
    Items whose word-level Jaccard similarity meets or exceeds the threshold
    are clustered, and each cluster is resolved to a single survivor.

    Args:
        items: Context items to deduplicate.
        threshold: Jaccard similarity threshold (default 0.8).
        strategy: "recent" (highest recency wins) or "highest-priority".
        tokenizer: Custom tokenizer; defaults to unicode_tokenize.

    Returns:
        Deduplicated list preserving original order.
    """
    if len(items) <= 1:
        return list(items)

    tokenize = tokenizer or unicode_tokenize

    # Pre-tokenize all items
    token_sets = [set(tokenize(item.content)) for item in items]

    # Greedy agglomerative clustering
    clusters: list[list[int]] = []

    for i, tokens_i in enumerate(token_sets):
        added_to_cluster = False
        for cluster in clusters:
            first_idx = cluster[0]
            sim = jaccard_similarity(tokens_i, token_sets[first_idx])
            if sim >= threshold:
                cluster.append(i)
                added_to_cluster = True
                break

        if not added_to_cluster:
            clusters.append([i])

    # Resolve each cluster to a single survivor
    survivor_ids: set[str] = set()
    for cluster in clusters:
        if len(cluster) == 1:
            survivor_ids.add(items[cluster[0]].id)
            continue

        cluster_items = [items[idx] for idx in cluster]
        survivor = _resolve_survivor(cluster_items, strategy)
        survivor_ids.add(survivor.id)

    # Maintain original order
    return [item for item in items if item.id in survivor_ids]


class RedundancyEliminator:
    def __init__(self, config: RedundancyConfig):
        self.config = config

    async def process(self, items: List[ContextItem]) -> List[ContextItem]:
        if not items:
            return []

        # Get embeddings
        texts = [item.content for item in items]
        embeddings = await self.config.provider.embed(texts)

        # Agglomerative clustering (greedy approach)
        clusters: List[List[int]] = []  # list of lists of indices

        for i, emb in enumerate(embeddings):
            added_to_cluster = False
            for cluster in clusters:
                # Compare to the first element of the cluster
                first_idx = cluster[0]
                similarity = cosine_similarity(emb, embeddings[first_idx])
                if similarity >= self.config.similarity_threshold:
                    cluster.append(i)
                    added_to_cluster = True
                    break

            if not added_to_cluster:
                clusters.append([i])

        # Resolve clusters using shared helper
        surviving_items: List[ContextItem] = []
        for cluster in clusters:
            if len(cluster) == 1:
                surviving_items.append(items[cluster[0]])
                continue

            cluster_items = [items[i] for i in cluster]
            best_item = _resolve_survivor(cluster_items, self.config.strategy)
            surviving_items.append(best_item)

        # Maintain original order among surviving items
        final_ids = {item.id for item in surviving_items}
        return [item for item in items if item.id in final_ids]
