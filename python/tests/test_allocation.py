"""Tests for kind-aware budget allocation."""
import pytest
from context_engineering.core import Budget, ContextItem
from context_engineering.allocation import (
    KindAllocation,
    pack_with_allocation,
)


def make_item(id: str, kind: str, priority: float, tokens: int) -> ContextItem:
    return ContextItem(id=id, content=f"content-{id}", kind=kind, priority=priority, tokens=tokens)


class TestPackWithAllocation:
    def test_allocates_by_kind(self):
        items = [
            make_item("s1", "system", 10, 50),
            make_item("r1", "retrieval", 7, 100),
            make_item("r2", "retrieval", 6, 100),
            make_item("c1", "conversation", 5, 100),
        ]
        result = pack_with_allocation(
            items,
            Budget(max_tokens=300),
            [
                KindAllocation(kind="system", target_ratio=0.2),
                KindAllocation(kind="retrieval", target_ratio=0.5),
                KindAllocation(kind="conversation", target_ratio=0.3),
            ],
        )
        assert len(result.selected) > 0
        assert "system" in result.allocations
        assert "retrieval" in result.allocations
        assert "conversation" in result.allocations

    def test_respects_minimum(self):
        items = [
            make_item("s1", "system", 10, 200),
            make_item("r1", "retrieval", 7, 100),
        ]
        result = pack_with_allocation(
            items,
            Budget(max_tokens=300),
            [
                KindAllocation(kind="system", min_tokens=200, target_ratio=0.2),
                KindAllocation(kind="retrieval", target_ratio=0.8),
            ],
        )
        assert result.allocations["system"].budget_allocated >= 200

    def test_respects_maximum(self):
        items = [
            make_item("s1", "system", 10, 50),
            make_item("r1", "retrieval", 7, 200),
            make_item("r2", "retrieval", 6, 200),
        ]
        result = pack_with_allocation(
            items,
            Budget(max_tokens=500),
            [
                KindAllocation(kind="system", target_ratio=0.5, max_tokens=100),
                KindAllocation(kind="retrieval", target_ratio=0.5),
            ],
        )
        assert result.allocations["system"].budget_used <= 100

    def test_redistributes_surplus(self):
        items = [
            make_item("s1", "system", 10, 30),
            make_item("r1", "retrieval", 7, 100),
            make_item("r2", "retrieval", 6, 100),
            make_item("r3", "retrieval", 5, 100),
        ]
        result = pack_with_allocation(
            items,
            Budget(max_tokens=400),
            [
                KindAllocation(kind="system", target_ratio=0.5, priority=1),
                KindAllocation(kind="retrieval", target_ratio=0.5, priority=10),
            ],
        )
        assert result.allocations["retrieval"].budget_used > 200

    def test_uncategorized_items(self):
        items = [
            make_item("s1", "system", 10, 50),
            make_item("misc", "other", 5, 50),
        ]
        result = pack_with_allocation(
            items,
            Budget(max_tokens=200),
            [KindAllocation(kind="system", target_ratio=0.5)],
        )
        assert any(i.id == "misc" for i in result.selected)
        assert "_uncategorized" in result.allocations

    def test_allocation_efficiency(self):
        items = [
            make_item("s1", "system", 10, 100),
            make_item("r1", "retrieval", 7, 100),
        ]
        result = pack_with_allocation(
            items,
            Budget(max_tokens=200),
            [
                KindAllocation(kind="system", target_ratio=0.5),
                KindAllocation(kind="retrieval", target_ratio=0.5),
            ],
        )
        assert result.allocation_efficiency > 0.8

    def test_empty_items(self):
        result = pack_with_allocation(
            [],
            Budget(max_tokens=200),
            [KindAllocation(kind="system", target_ratio=1.0)],
        )
        assert len(result.selected) == 0
        assert result.total_tokens == 0

    def test_reserve_tokens(self):
        items = [
            make_item("s1", "system", 10, 100),
            make_item("r1", "retrieval", 7, 100),
        ]
        result = pack_with_allocation(
            items,
            Budget(max_tokens=200, reserve_tokens=50),
            [
                KindAllocation(kind="system", target_ratio=0.5),
                KindAllocation(kind="retrieval", target_ratio=0.5),
            ],
        )
        assert result.total_tokens <= 150

    def test_all_items_accounted(self):
        items = [
            make_item("a", "system", 10, 100),
            make_item("b", "retrieval", 7, 100),
            make_item("c", "retrieval", 5, 100),
            make_item("d", "memory", 3, 100),
        ]
        result = pack_with_allocation(
            items,
            Budget(max_tokens=200),
            [
                KindAllocation(kind="system", target_ratio=0.3),
                KindAllocation(kind="retrieval", target_ratio=0.4),
                KindAllocation(kind="memory", target_ratio=0.3),
            ],
        )
        all_ids = {i.id for i in result.selected} | {i.id for i in result.dropped}
        assert len(all_ids) == 4
