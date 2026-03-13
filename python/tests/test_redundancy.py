import random

import pytest

from context_engineering.core import ContextItem
from context_engineering.redundancy import RedundancyConfig, RedundancyEliminator


class MessyProvider:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for text in texts:
            if text == "zero":
                embeddings.append([0.0, 0.0, 0.0])
            elif text.startswith("identical"):
                embeddings.append([0.5, 0.5, 0.5])
            elif text == "opposite-1":
                embeddings.append([1.0, -1.0, 1.0])
            elif text == "opposite-2":
                embeddings.append([-1.0, 1.0, -1.0])
            else:
                embeddings.append([random.random(), random.random(), random.random()])
        return embeddings

@pytest.mark.asyncio
async def test_handles_empty_items_array():
    config = RedundancyConfig(provider=MessyProvider())
    eliminator = RedundancyEliminator(config)
    result = await eliminator.process([])
    assert result == []

@pytest.mark.asyncio
async def test_handles_zero_magnitude_vectors():
    items = [
        ContextItem(id="1", content="zero", recency=1.0),
        ContextItem(id="2", content="zero", recency=2.0)
    ]
    config = RedundancyConfig(provider=MessyProvider(), similarity_threshold=0.5)
    eliminator = RedundancyEliminator(config)
    result = await eliminator.process(items)

    # Cosine similarity with a zero vector should be 0.0, which is < 0.5, so no grouping
    assert len(result) == 2

@pytest.mark.asyncio
async def test_handles_perfectly_identical_vectors_resolves_ties():
    items = [
        ContextItem(id="1", content="identical-1", recency=5.0, priority=10.0),
        ContextItem(id="2", content="identical-2", recency=5.0, priority=20.0), # Highest priority wins tie breaker
        ContextItem(id="3", content="identical-3", recency=5.0, priority=5.0),
    ]
    config = RedundancyConfig(provider=MessyProvider(), similarity_threshold=0.99)
    eliminator = RedundancyEliminator(config)
    result = await eliminator.process(items)

    assert len(result) == 1
    assert result[0].id == "2"

@pytest.mark.asyncio
async def test_handles_opposite_vectors():
    items = [
        ContextItem(id="1", content="opposite-1", recency=1.0),
        ContextItem(id="2", content="opposite-2", recency=2.0)
    ]
    # Similarity should be exactly -1.0
    config = RedundancyConfig(provider=MessyProvider(), similarity_threshold=0.0)
    eliminator = RedundancyEliminator(config)
    result = await eliminator.process(items)

    # -1.0 < 0.0 so they shouldn't merge
    assert len(result) == 2

@pytest.mark.asyncio
async def test_does_not_mutate_original_list():
    items = [
        ContextItem(id="1", content="identical-1", recency=1.0),
        ContextItem(id="2", content="identical-2", recency=2.0)
    ]
    original_len = len(items)
    config = RedundancyConfig(provider=MessyProvider())
    eliminator = RedundancyEliminator(config)
    await eliminator.process(items)
    assert len(items) == original_len

@pytest.mark.asyncio
async def test_summarize_strategy_fallback():
    items = [
        ContextItem(id="1", content="identical-1", recency=10.0),
        ContextItem(id="2", content="identical-2", recency=50.0)
    ]
    config = RedundancyConfig(provider=MessyProvider(), strategy="summarize")
    eliminator = RedundancyEliminator(config)
    result = await eliminator.process(items)

    # Fallback behavior uses recency max
    assert len(result) == 1
    assert result[0].id == "2"
