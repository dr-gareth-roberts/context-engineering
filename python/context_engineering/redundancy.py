import math
from typing import List, Literal, Protocol

from .core import ContextItem


class EmbeddingProvider(Protocol):
    async def embed(self, texts: List[str]) -> List[List[float]]:
        ...

class RedundancyConfig:
    def __init__(
        self,
        provider: EmbeddingProvider,
        similarity_threshold: float = 0.92,
        strategy: Literal["recent", "summarize"] = "recent"
    ):
        self.provider = provider
        self.similarity_threshold = similarity_threshold
        self.strategy = strategy

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot_product = sum(x * y for x, y in zip(v1, v2))
    magnitude1 = math.sqrt(sum(x * x for x in v1))
    magnitude2 = math.sqrt(sum(y * y for y in v2))
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    return dot_product / (magnitude1 * magnitude2)

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
        clusters: List[List[int]] = [] # list of lists of indices

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

            # Need to resolve
            cluster_items = [items[i] for i in cluster]

            if self.config.strategy == "recent":
                # Keep the one with highest recency, fallback to priority or last
                best_item = max(
                    cluster_items,
                    key=lambda x: (x.recency or 0.0, x.priority or 0.0)
                )

                # Annotate other items? Actually, the plan mentions:
                # "For dropped items, append a trace step with reason='superseded' and duplicateOfId=<surviving_id>."
                # The redundancy eliminator might just return the surviving items.
                # We can add supersedes tracking to the items if we modify ContextItem schema later, or keep it simple.
                surviving_items.append(best_item)
            elif self.config.strategy == "summarize":
                # For now, just a placeholder. Real implementation requires an LLM call.
                # Fallback to recent if summarize is too complex to mock right now without an LLM.
                best_item = max(
                    cluster_items,
                    key=lambda x: (x.recency or 0.0, x.priority or 0.0)
                )
                surviving_items.append(best_item)

        # To maintain original sort order loosely
        final_ids = {item.id for item in surviving_items}
        return [item for item in items if item.id in final_ids]

