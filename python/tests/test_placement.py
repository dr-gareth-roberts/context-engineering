"""Tests for the placement module: attention-aware item ordering."""

from context_engineering.core import ContextItem
from context_engineering.placement import (
    ATTENTION_PROFILES,
    AttentionProfile,
    effective_budget,
    place_items,
)


def _item(id: str, score: float) -> ContextItem:
    return ContextItem(id=id, content=f"content-{id}", score=score)


class TestAttentionProfiles:
    def test_has_all_profiles(self):
        assert "claude" in ATTENTION_PROFILES
        assert "gpt4" in ATTENTION_PROFILES
        assert "default" in ATTENTION_PROFILES

    def test_each_profile_has_10_buckets(self):
        for key, profile in ATTENTION_PROFILES.items():
            assert len(profile.position_weights) == 10, f"{key} has wrong bucket count"

    def test_effective_capacity_in_range(self):
        for key, profile in ATTENTION_PROFILES.items():
            assert 0 < profile.effective_capacity <= 1, f"{key} capacity out of range"


class TestPlaceItems:
    def test_score_order_returns_copy(self):
        items = [_item("a", 10), _item("b", 5)]
        result = place_items(items, strategy="score-order")
        assert [i.id for i in result] == ["a", "b"]
        assert result is not items

    def test_default_strategy_is_score_order(self):
        items = [_item("a", 10), _item("b", 5), _item("c", 1)]
        result = place_items(items)
        assert [i.id for i in result] == ["a", "b", "c"]

    def test_two_or_fewer_items_unchanged(self):
        single = [_item("a", 10)]
        pair = [_item("a", 10), _item("b", 5)]
        assert [i.id for i in place_items(single, strategy="attention-optimized")] == ["a"]
        assert [i.id for i in place_items(pair, strategy="attention-optimized")] == ["a", "b"]

    def test_attention_optimized_puts_high_items_at_edges(self):
        items = [
            _item("high1", 100),
            _item("high2", 90),
            _item("mid1", 50),
            _item("mid2", 40),
            _item("low", 10),
        ]
        result = place_items(items, strategy="attention-optimized", model="default")
        assert len(result) == 5
        ids = set(i.id for i in result)
        assert len(ids) == 5

        # Highest item at start or end
        edge_ids = [result[0].id, result[-1].id]
        assert "high1" in edge_ids

        # Low item in the middle
        middle_ids = [i.id for i in result[1:-1]]
        assert "low" in middle_ids

    def test_claude_profile_highest_at_start(self):
        items = [_item("a", 100), _item("b", 50), _item("c", 10)]
        result = place_items(items, strategy="attention-optimized", model="claude")
        assert len(result) == 3
        # Claude weight at position 0 is 1.0 (highest)
        assert result[0].id == "a"

    def test_custom_profile(self):
        custom = AttentionProfile(
            name="custom",
            effective_capacity=0.8,
            position_weights=[1.0, 0.1, 0.1],
        )
        items = [_item("a", 100), _item("b", 50), _item("c", 10)]
        result = place_items(items, strategy="attention-optimized", profile=custom)
        assert len(result) == 3
        assert result[0].id == "a"

    def test_unknown_model_falls_back_to_default(self):
        items = [_item("a", 100), _item("b", 50), _item("c", 10)]
        result = place_items(items, strategy="attention-optimized", model="unknown-model")
        assert len(result) == 3

    def test_items_without_score_default_to_zero(self):
        items = [
            ContextItem(id="a", content="a"),
            ContextItem(id="b", content="b"),
            ContextItem(id="c", content="c", score=10),
        ]
        result = place_items(items, strategy="attention-optimized")
        assert len(result) == 3
        assert "c" in [i.id for i in result]

    def test_preserves_all_items(self):
        items = [_item(f"item{i}", i * 10) for i in range(8)]
        result = place_items(items, strategy="attention-optimized", model="claude")
        assert len(result) == 8
        assert set(i.id for i in result) == set(i.id for i in items)


class TestEffectiveBudget:
    def test_default_profile(self):
        assert effective_budget(200_000) == 140_000

    def test_claude_profile(self):
        assert effective_budget(200_000, "claude") == 140_000

    def test_gpt4_profile(self):
        assert effective_budget(200_000, "gpt4") == 130_000

    def test_floors_result(self):
        assert effective_budget(100_001, "claude") == 70_000

    def test_unknown_model_uses_default(self):
        assert effective_budget(200_000, "unknown") == 140_000
