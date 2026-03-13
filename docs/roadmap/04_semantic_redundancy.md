# Roadmap 04: Semantic Redundancy Elimination

## Objective

Automatically detect and merge context items that contain the same information, preventing "context bloat" and model confusion.

## Core Logic

- **Vector Comparison:** Use the `EmbeddingProvider` to calculate cosine similarity between `ContextItems`.
- **Clustering:** Group items that exceed a similarity threshold (e.g., > 0.92).
- **Resolution Strategies:**
  1.  **Keep Most Recent:** Drop the older items.
  2.  **Summarize/Merge:** Use a small LLM (like Llama 3 8B via Cerebras) to merge the two items into one concise fact.
  3.  **Explicit `supersedes`:** Automatically populate the `supersedes` field in the `ContextItem`.

## Integration Point

Add a `RedundancyEliminator` class to `python/context_engineering/core.py`:

```python
class RedundancyEliminator:
    def __init__(self, threshold: float = 0.9, strategy: str = "recent"):
        self.threshold = threshold
        self.strategy = strategy

    def process(self, items: List[ContextItem]) -> List[ContextItem]:
        # Logic to find duplicates and apply strategy
        ...
```

## Challenges

- **False Positives:** Two different items might look similar (e.g., "The balance is $100" vs "The balance is $200"). Must include "Delta Detection" to ensure critical data differences are preserved.
- **Cost:** Running embeddings for every item. Solution: Cache embeddings in the `MemoryStore`.

## Success Criteria

- Feeding 10 slightly different versions of the same user instruction results in only 1 optimized instruction in the final `ContextPack`.
