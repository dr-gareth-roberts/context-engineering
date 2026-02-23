"""Tests for the stream module: async generator pack variant."""
import pytest

from context_engineering.core import Budget, ContextItem
from context_engineering.stream import pack_stream


@pytest.mark.asyncio
async def test_basic_stream():
    items = [
        ContextItem(id="a", content="hello world", priority=10, tokens=2),
        ContextItem(id="b", content="foo bar baz", priority=5, tokens=3),
    ]
    budget = Budget(maxTokens=10)
    selected = []
    async for item in pack_stream(items, budget):
        selected.append(item)
    assert len(selected) == 2


@pytest.mark.asyncio
async def test_stream_respects_budget():
    items = [
        ContextItem(id="a", content="a", priority=10, tokens=5),
        ContextItem(id="b", content="b", priority=8, tokens=5),
        ContextItem(id="c", content="c", priority=1, tokens=5),
    ]
    budget = Budget(maxTokens=10)
    selected = []
    async for item in pack_stream(items, budget):
        selected.append(item)
    assert len(selected) == 2
    assert selected[0].id == "a"
    assert selected[1].id == "b"


@pytest.mark.asyncio
async def test_stream_score_order():
    items = [
        ContextItem(id="low", content="low", priority=1, tokens=2),
        ContextItem(id="high", content="high", priority=10, tokens=2),
        ContextItem(id="mid", content="mid", priority=5, tokens=2),
    ]
    budget = Budget(maxTokens=100)
    selected = []
    async for item in pack_stream(items, budget):
        selected.append(item)
    assert selected[0].id == "high"
    assert selected[1].id == "mid"
    assert selected[2].id == "low"


@pytest.mark.asyncio
async def test_stream_empty_items():
    budget = Budget(maxTokens=100)
    selected = []
    async for item in pack_stream([], budget):
        selected.append(item)
    assert selected == []


@pytest.mark.asyncio
async def test_stream_invalid_budget():
    with pytest.raises(ValueError, match="maxTokens must be positive"):
        async for _ in pack_stream([], Budget(maxTokens=0)):
            pass


@pytest.mark.asyncio
async def test_stream_reserve_tokens():
    items = [
        ContextItem(id="a", content="a", priority=10, tokens=5),
        ContextItem(id="b", content="b", priority=8, tokens=5),
    ]
    budget = Budget(maxTokens=12, reserveTokens=5)
    selected = []
    async for item in pack_stream(items, budget):
        selected.append(item)
    # 12 - 5 = 7 available, only "a" (5 tokens) fits
    assert len(selected) == 1
    assert selected[0].id == "a"
