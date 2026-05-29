import random

import pytest

from context_engineering.core import ContextItem
from context_engineering.redundancy import (
    RedundancyConfig,
    RedundancyEliminator,
    eliminate_redundancy_sync,
)


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
        ContextItem(id="2", content="zero", recency=2.0),
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
        ContextItem(
            id="2", content="identical-2", recency=5.0, priority=20.0
        ),  # Highest priority wins tie breaker
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
        ContextItem(id="2", content="opposite-2", recency=2.0),
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
        ContextItem(id="2", content="identical-2", recency=2.0),
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
        ContextItem(id="2", content="identical-2", recency=50.0),
    ]
    config = RedundancyConfig(provider=MessyProvider(), strategy="summarize")
    eliminator = RedundancyEliminator(config)
    result = await eliminator.process(items)

    # Fallback behavior uses recency max
    assert len(result) == 1
    assert result[0].id == "2"


class TestEliminateRedundancySync:
    def test_clusters_high_word_overlap(self):
        items = [
            ContextItem(id="a", content="the quick brown fox jumps over the lazy dog"),
            ContextItem(id="b", content="the quick brown fox jumps over the lazy cat"),
            ContextItem(id="c", content="completely unrelated content about space rockets"),
        ]
        result = eliminate_redundancy_sync(items, threshold=0.7, strategy="recent")
        assert len(result) == 2

    def test_does_not_cluster_below_threshold(self):
        items = [
            ContextItem(id="a", content="alpha beta gamma delta epsilon"),
            ContextItem(id="b", content="alpha beta gamma zeta omega"),
        ]
        result = eliminate_redundancy_sync(items)  # default 0.8
        assert len(result) == 2

    def test_highest_priority_strategy(self):
        items = [
            ContextItem(id="a", content="same words repeated here again", priority=1),
            ContextItem(id="b", content="same words repeated here again", priority=10),
        ]
        result = eliminate_redundancy_sync(items, threshold=0.8, strategy="highest-priority")
        assert len(result) == 1
        assert result[0].id == "b"

    def test_recent_strategy(self):
        items = [
            ContextItem(id="a", content="same words repeated here again", recency=1),
            ContextItem(id="b", content="same words repeated here again", recency=10),
        ]
        result = eliminate_redundancy_sync(items, threshold=0.8, strategy="recent")
        assert len(result) == 1
        assert result[0].id == "b"

    def test_empty_input(self):
        assert eliminate_redundancy_sync([]) == []

    def test_single_item(self):
        items = [ContextItem(id="a", content="only one")]
        assert eliminate_redundancy_sync(items) == items

    def test_default_threshold_is_0_8(self):
        items = [
            ContextItem(id="a", content="alpha beta gamma delta epsilon zeta"),
            ContextItem(id="b", content="alpha beta gamma delta epsilon omega"),
        ]
        # Jaccard = 5/7 ~= 0.71, below 0.8 default
        result = eliminate_redundancy_sync(items)
        assert len(result) == 2


@pytest.mark.asyncio
async def test_process_falls_back_to_jaccard_when_no_provider():
    """Regression: RedundancyEliminator.process() with a provider-less config
    must not raise AttributeError and must dedup via Jaccard.

    Previously process() called self.config.provider.embed() unconditionally,
    crashing with 'NoneType' object has no attribute 'embed' on any non-empty
    input when the config had no embedding provider.
    """
    items = [
        ContextItem(id="1", content="the quick brown fox jumps over the lazy dog", recency=1.0),
        ContextItem(id="2", content="the quick brown fox jumps over the lazy dog", recency=2.0),
        ContextItem(
            id="3", content="completely unrelated content about space rockets", recency=3.0
        ),
    ]
    eliminator = RedundancyEliminator(RedundancyConfig())
    result = await eliminator.process(items)

    # Duplicate 1 and 2 (Jaccard 1.0 >= 0.8 default) collapse; 3 stays.
    assert len(result) == 2
    ids = {item.id for item in result}
    assert "3" in ids
    # Survivor of the duplicate cluster is the more recent one.
    assert "2" in ids


@pytest.mark.asyncio
async def test_process_no_provider_uses_jaccard_default_threshold():
    """When no threshold is explicitly set, the no-provider fallback must use
    the Jaccard default (0.8), NOT the embedding default (0.92).

    Discriminating content: 9 shared tokens + 1 unique each -> Jaccard 9/11
    ~= 0.818, which is >= 0.8 (merges) but < 0.92 (would NOT merge). If a
    regression fed the embedding default (0.92) into the Jaccard path, these
    would not collapse and this test would fail.
    """
    items = [
        ContextItem(
            id="a",
            content="alpha beta gamma delta epsilon zeta eta theta iota cat",
            recency=1.0,
        ),
        ContextItem(
            id="b",
            content="alpha beta gamma delta epsilon zeta eta theta iota dog",
            recency=2.0,
        ),
    ]
    eliminator = RedundancyEliminator(RedundancyConfig())
    result = await eliminator.process(items)
    # Jaccard ~= 0.818 >= 0.8 default -> collapse to one (the more recent).
    assert len(result) == 1
    assert result[0].id == "b"


@pytest.mark.asyncio
async def test_process_no_provider_honors_explicit_threshold():
    """An explicitly-set threshold must be honored by the no-provider fallback."""
    items = [
        ContextItem(id="a", content="alpha beta gamma delta epsilon zeta"),
        ContextItem(id="b", content="alpha beta gamma delta epsilon omega"),
    ]
    # Jaccard = 5/7 ~= 0.71. With explicit threshold 0.5 they should merge;
    # this proves the explicit value (not the 0.8 default) is used.
    eliminator = RedundancyEliminator(RedundancyConfig(threshold=0.5))
    result = await eliminator.process(items)
    assert len(result) == 1
