"""Tests for the quality module: context quality metrics."""
import pytest

from context_engineering.core import ContextItem
from context_engineering.quality import ContextQuality, analyze_context, analyze_context_pack


def _item(id: str, content: str, recency: float = 0, tokens: int | None = None) -> ContextItem:
    return ContextItem(id=id, content=content, recency=recency, tokens=tokens)


class TestAnalyzeContext:
    def test_empty_items(self):
        q = analyze_context([])
        assert q.item_count == 0
        assert q.total_tokens == 0
        assert q.overall == 0.0

    def test_single_item(self):
        q = analyze_context([_item("a", "hello world", tokens=2)])
        assert q.item_count == 1
        assert q.total_tokens == 2
        assert q.density > 0
        assert q.redundancy == 0.0  # no pairs

    def test_high_diversity_distinct_content(self):
        items = [
            _item("a", "the cat sat on the mat", tokens=6),
            _item("b", "quantum physics explains particle behavior", tokens=5),
            _item("c", "cooking requires fresh ingredients daily", tokens=5),
        ]
        q = analyze_context(items)
        assert q.diversity > 0.5

    def test_low_diversity_similar_content(self):
        items = [
            _item("a", "the cat sat on the mat", tokens=6),
            _item("b", "the cat sat on the rug", tokens=6),
            _item("c", "the cat sat on the floor", tokens=6),
        ]
        q = analyze_context(items)
        assert q.redundancy > 0.3

    def test_freshness_with_recent_items(self):
        items = [
            _item("a", "content a", recency=8.0, tokens=2),
            _item("b", "content b", recency=9.0, tokens=2),
            _item("c", "content c", recency=1.0, tokens=2),
        ]
        q = analyze_context(items)
        assert q.freshness == pytest.approx(2 / 3, abs=0.01)

    def test_freshness_with_no_recent_items(self):
        items = [
            _item("a", "content a", recency=1.0, tokens=2),
            _item("b", "content b", recency=2.0, tokens=2),
        ]
        q = analyze_context(items)
        assert q.freshness == 0.0

    def test_overall_is_weighted_combination(self):
        items = [
            _item("a", "unique words here for testing purposes", recency=7.0, tokens=6),
            _item("b", "completely different content about other things", recency=8.0, tokens=6),
        ]
        q = analyze_context(items)
        expected = round(
            q.density * 0.25 + q.diversity * 0.25 + q.freshness * 0.20 + (1 - q.redundancy) * 0.30,
            2,
        )
        assert q.overall == expected

    def test_metrics_in_range(self):
        items = [_item(f"i{i}", f"item number {i} with some content", tokens=5) for i in range(10)]
        q = analyze_context(items)
        assert 0 <= q.density <= 1
        assert 0 <= q.diversity <= 1
        assert 0 <= q.freshness <= 1
        assert 0 <= q.redundancy <= 1
        assert 0 <= q.overall <= 1


class TestAnalyzeContextPack:
    def test_delegates_to_analyze_context(self):
        from context_engineering.core import Budget, ContextPack

        pack = ContextPack(
            budget=Budget(maxTokens=100),
            selected=[_item("a", "hello world", tokens=2)],
            dropped=[],
            totalTokens=2,
        )
        q = analyze_context_pack(pack)
        assert q.item_count == 1
