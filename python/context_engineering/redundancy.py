"""Semantic redundancy elimination via embedding similarity.

Uses an async embedding provider to detect and remove near-duplicate
context items before packing.
"""

from __future__ import annotations

from typing import List, Literal, Protocol, runtime_checkable

from ._similarity import cosine_similarity
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
        provider: AsyncEmbeddingProvider,
        similarity_threshold: float = 0.92,
        strategy: Literal["recent", "summarize"] = "recent",
    ):
        self.provider = provider
        self.similarity_threshold = similarity_threshold
        self.strategy = strategy


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

        # Resolve clusters
        surviving_items: List[ContextItem] = []
        for cluster in clusters:
            if len(cluster) == 1:
                surviving_items.append(items[cluster[0]])
                continue

            # Need to resolve -- keep the item with highest recency, then priority
            cluster_items = [items[i] for i in cluster]
            best_item = max(
                cluster_items,
                key=lambda x: (x.recency or 0.0, x.priority or 0.0),
            )
            surviving_items.append(best_item)

        # Maintain original order among surviving items
        final_ids = {item.id for item in surviving_items}
        return [item for item in items if item.id in final_ids]
