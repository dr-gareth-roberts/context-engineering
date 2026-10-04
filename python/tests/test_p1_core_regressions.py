"""Regression tests for P1 correctness bugs in the core Python port.

Each test reproduces a bug confirmed by the October 2026 audit and pins the
fixed behaviour (matching the TypeScript implementation where both exist).
"""

from __future__ import annotations

from typing import List

from context_engineering.core import ContextItem
from context_engineering.placement import AttentionProfile, place_items


def _ids(items: List[ContextItem]) -> List[str]:
    return [i.id for i in items]


class TestPlacementFinalBucket:
    def test_last_position_uses_last_attention_bucket(self):
        items = [
            ContextItem(id="a", content="a", score=3),
            ContextItem(id="b", content="b", score=2),
            ContextItem(id="c", content="c", score=1),
        ]
        placed = place_items(items, strategy="attention-optimized")
        assert _ids(placed) == ["a", "c", "b"]

    def test_highest_item_reaches_recency_peaked_final_bucket(self):
        profile = AttentionProfile(
            name="recency-peak",
            effective_capacity=1.0,
            position_weights=[0.5, 0.1, 0.1, 0.1, 0.9],
        )
        items = [ContextItem(id=f"i{i}", content="x", score=4 - i) for i in range(4)]
        placed = place_items(items, strategy="attention-optimized", profile=profile)
        assert placed[-1].id == "i0"
        assert len({i.id for i in placed}) == 4


# ---------------------------------------------------------------------------
# Shared invariants
# ---------------------------------------------------------------------------


def _assert_partition(inputs: List[ContextItem], selected, dropped) -> None:
    """Every input item ends up in exactly one of selected/dropped."""
    assert len(selected) + len(dropped) == len(inputs)
    assert sorted(i.id for i in [*selected, *dropped]) == sorted(i.id for i in inputs)


# ---------------------------------------------------------------------------
# Cache topology (bugs 5, 6, 8, 9)
# ---------------------------------------------------------------------------


class TestCacheTopologyRegressions:
    def test_invalid_volatility_defaults_to_request(self):
        from context_engineering.cache_topology import (
            classify_volatility,
            pack_with_cache_topology,
        )
        from context_engineering.core import Budget

        item = ContextItem(id="typo", content="x", tokens=5, metadata={"volatility": "typo"})
        assert classify_volatility(item) == "request"
        result = pack_with_cache_topology([item], Budget(max_tokens=100))
        assert _ids(result.selected) == ["typo"]
        _assert_partition([item], result.selected, result.dropped)

    def test_non_string_volatility_falls_back_to_kind(self):
        from context_engineering.cache_topology import classify_volatility

        item = ContextItem(id="a", content="", kind="system", metadata={"volatility": 42})
        assert classify_volatility(item) == "static"

    def test_rejects_reserve_ge_max(self):
        import pytest

        from context_engineering.cache_topology import pack_with_cache_topology
        from context_engineering.core import Budget
        from context_engineering.errors import BudgetExceededError

        item = ContextItem(id="s", content="x", kind="system", tokens=10)
        with pytest.raises(BudgetExceededError):
            pack_with_cache_topology([item], Budget(max_tokens=100, reserve_tokens=100))

    def test_rejects_non_positive_max_async(self):
        import asyncio

        import pytest

        from context_engineering.cache_topology import pack_with_cache_topology_async
        from context_engineering.core import Budget
        from context_engineering.errors import ValidationError

        with pytest.raises(ValidationError):
            asyncio.run(pack_with_cache_topology_async([], Budget(max_tokens=0)))

    def test_duplicate_static_ids_stay_in_dropped(self):
        from context_engineering.cache_topology import pack_with_cache_topology
        from context_engineering.core import Budget

        items = [
            ContextItem(id="dup", content="small", kind="system", tokens=10),
            ContextItem(id="dup", content="big", kind="system", tokens=1000),
        ]
        result = pack_with_cache_topology(items, Budget(max_tokens=100))
        assert len(result.selected) == 1
        assert [i.content for i in result.dropped] == ["big"]
        _assert_partition(items, result.selected, result.dropped)

    def test_min_prefix_tokens_below_threshold_is_not_cacheable(self):
        from context_engineering.cache_topology import CacheConfig, pack_with_cache_topology
        from context_engineering.core import Budget

        items = [
            ContextItem(id="sys", content="s", kind="system", priority=10, tokens=100),
            ContextItem(id="q", content="q", kind="query", priority=5, tokens=50),
        ]
        result = pack_with_cache_topology(
            items, Budget(max_tokens=1000), cache_config=CacheConfig(min_prefix_tokens=200)
        )
        assert result.total_tokens == 150
        assert result.cacheable_tokens == 0
        assert result.cache_efficiency == 0
        assert result.volatile_tokens == 150

    def test_min_prefix_tokens_met_is_cacheable(self):
        from context_engineering.cache_topology import CacheConfig, pack_with_cache_topology
        from context_engineering.core import Budget

        items = [ContextItem(id="sys", content="s", kind="system", priority=10, tokens=200)]
        result = pack_with_cache_topology(
            items, Budget(max_tokens=1000), cache_config=CacheConfig(min_prefix_tokens=200)
        )
        assert result.cacheable_tokens == 200
        assert result.cache_efficiency == 1

    def test_budget_invariant_and_no_mutation(self):
        from context_engineering.cache_topology import CacheConfig, pack_with_cache_topology
        from context_engineering.core import Budget

        items = [
            ContextItem(id="s1", content="a", kind="system", priority=9, tokens=40),
            ContextItem(id="s2", content="b", kind="system", priority=3, tokens=40),
            ContextItem(id="m1", content="c", kind="memory", priority=5, tokens=30),
            ContextItem(id="q1", content="d", kind="query", priority=8, tokens=25),
            ContextItem(id="r1", content="e", kind="retrieval", priority=1, tokens=25),
        ]
        snapshot = [i.model_dump() for i in items]
        result = pack_with_cache_topology(
            items,
            Budget(max_tokens=150, reserve_tokens=20),
            cache_config=CacheConfig(mark_breakpoints=True),
        )
        assert result.total_tokens <= 130
        _assert_partition(items, result.selected, result.dropped)
        assert [i.model_dump() for i in items] == snapshot


# ---------------------------------------------------------------------------
# Budget validation (bug 29) and allocation (bugs 6, 30)
# ---------------------------------------------------------------------------


class TestBudgetValidation:
    def test_budget_model_rejects_negative_reserve(self):
        import pytest
        from pydantic import ValidationError as PydanticValidationError

        from context_engineering.core import Budget

        with pytest.raises(PydanticValidationError):
            Budget(max_tokens=100, reserve_tokens=-100)

    def test_pack_rejects_negative_reserve_even_if_constructed_unvalidated(self):
        import pytest

        from context_engineering.core import Budget, pack
        from context_engineering.errors import ValidationError

        budget = Budget.model_construct(max_tokens=100, reserve_tokens=-100)
        item = ContextItem(id="big", content="x", tokens=150)
        with pytest.raises(ValidationError):
            pack([item], budget)

    def test_pack_stream_rejects_negative_reserve(self):
        import asyncio

        import pytest

        from context_engineering.core import Budget
        from context_engineering.errors import ValidationError
        from context_engineering.stream import pack_stream

        budget = Budget.model_construct(max_tokens=100, reserve_tokens=-100)

        async def run():
            return [i async for i in pack_stream([ContextItem(id="a", content="x")], budget)]

        with pytest.raises(ValidationError):
            asyncio.run(run())

    def test_allocation_and_cache_topology_reject_negative_reserve(self):
        import pytest

        from context_engineering.allocation import KindAllocation, pack_with_allocation
        from context_engineering.cache_topology import pack_with_cache_topology
        from context_engineering.core import Budget
        from context_engineering.errors import ValidationError

        budget = Budget.model_construct(max_tokens=100, reserve_tokens=-100)
        item = ContextItem(id="big", content="x", kind="doc", tokens=150)
        with pytest.raises(ValidationError):
            pack_with_allocation([item], budget, [KindAllocation(kind="doc", target_ratio=1)])
        with pytest.raises(ValidationError):
            pack_with_cache_topology([item], budget)

    def test_recommendation_parsing_ignores_negative_reserve(self, monkeypatch):
        from context_engineering import recommendations

        monkeypatch.setattr(
            recommendations,
            "_fetch_json",
            lambda *_args, **_kwargs: {"maxTokens": 100, "reserveTokens": -100},
        )
        rec = recommendations.fetch_budget_recommendation(
            "s1", recommendations.RecommendationOptions(budget_url="https://example.invalid/b")
        )
        assert rec.max_tokens == 100
        assert rec.reserve_tokens is None


class TestAllocationRegressions:
    def test_allocation_rejects_invalid_budget(self):
        import pytest

        from context_engineering.allocation import pack_with_allocation
        from context_engineering.core import Budget
        from context_engineering.errors import BudgetExceededError

        with pytest.raises(BudgetExceededError):
            pack_with_allocation([], Budget(max_tokens=100, reserve_tokens=100), [])

    def test_overcommitted_minimums_never_exceed_budget(self):
        import asyncio

        from context_engineering.allocation import (
            KindAllocation,
            pack_with_allocation,
            pack_with_allocation_async,
        )
        from context_engineering.core import Budget

        items = [
            ContextItem(id=f"a{i}", content="a", kind="a", priority=5, tokens=20) for i in range(4)
        ] + [
            ContextItem(id=f"b{i}", content="b", kind="b", priority=5, tokens=20) for i in range(4)
        ]
        allocations = [
            KindAllocation(kind="a", min_tokens=80, priority=2),
            KindAllocation(kind="b", min_tokens=80, priority=1),
        ]
        budget = Budget(max_tokens=100)
        for result in (
            pack_with_allocation(items, budget, allocations),
            asyncio.run(pack_with_allocation_async(items, budget, allocations)),
        ):
            assert result.total_tokens <= 100
            _assert_partition(items, result.selected, result.dropped)
            # Higher-priority kind keeps its floor; the lower one absorbs the cut.
            assert result.allocations["a"].budget_allocated == 80
            assert result.allocations["b"].budget_allocated == 20


# ---------------------------------------------------------------------------
# Compaction (bug 7 parity, bugs 31, 32)
# ---------------------------------------------------------------------------


def _words(text: str) -> int:
    trimmed = text.strip()
    return len(trimmed.split()) if trimmed else 0


class TestCompactionRegressions:
    def _sum(self, result) -> int:
        return sum(t.tokens for t in result.turns) + sum(i.tokens or 0 for i in result.items)

    def test_recent_turns_never_exceed_budget(self):
        import asyncio

        from context_engineering.compaction import create_context_manager
        from context_engineering.core import Budget

        mgr = create_context_manager(
            budget=Budget(max_tokens=5), preserve_recent_turns=2, token_estimator=_words
        )
        mgr.add_turn("user", "a b c d")
        mgr.add_turn("assistant", "e f g h")
        for result in (mgr.compile(), asyncio.run(mgr.compile_async())):
            assert result.total_tokens <= 5
            assert self._sum(result) == result.total_tokens
            assert [t.content for t in result.turns] == ["a", "e f g h"]

    def test_no_summary_when_no_budget_remains(self):
        import asyncio

        from context_engineering.compaction import create_context_manager
        from context_engineering.core import Budget

        mgr = create_context_manager(
            budget=Budget(max_tokens=5),
            summarize_after_turns=2,
            preserve_recent_turns=1,
            token_estimator=_words,
        )
        for i in range(3):
            mgr.add_turn("user", f"older turn {i}")
        mgr.add_turn("user", "one two three four five six")
        for result in (mgr.compile(), asyncio.run(mgr.compile_async())):
            assert result.total_tokens <= 5
            assert self._sum(result) == result.total_tokens
            assert not any(t.is_summary for t in result.turns)

    def test_never_exceeds_effective_budget_across_budgets(self):
        import asyncio

        from context_engineering.compaction import create_context_manager
        from context_engineering.core import Budget

        async def summarizer(item, _target):
            return item.model_copy(
                update={"content": " ".join(item.content.split()[:3]), "tokens": None}
            )

        for max_tokens in range(1, 41):
            mgr = create_context_manager(
                budget=Budget(max_tokens=max_tokens + 2, reserve_tokens=2),
                summarize_after_turns=2,
                preserve_recent_turns=2,
                token_estimator=_words,
                async_summarizer=summarizer,
            )
            for i in range(6):
                mgr.add_turn("user" if i % 2 == 0 else "assistant", f"turn {i} has a few words")
            mgr.add_items([ContextItem(id="doc", content="some doc words", score=1)])
            for result in (mgr.compile(), asyncio.run(mgr.compile_async())):
                assert result.total_tokens <= max_tokens
                assert self._sum(result) == result.total_tokens

    def test_rejects_reserve_that_consumes_budget(self):
        import pytest

        from context_engineering.compaction import create_context_manager
        from context_engineering.core import Budget
        from context_engineering.errors import BudgetExceededError

        with pytest.raises(BudgetExceededError):
            create_context_manager(budget=Budget(max_tokens=10, reserve_tokens=10))

    def test_rejects_system_prompt_over_budget(self):
        import pytest

        from context_engineering.compaction import create_context_manager
        from context_engineering.core import Budget
        from context_engineering.errors import BudgetExceededError

        with pytest.raises(BudgetExceededError):
            create_context_manager(
                budget=Budget(max_tokens=3),
                system_prompt="you are a helpful assistant",
                token_estimator=_words,
            )

    def test_summary_tokens_count_the_prefix(self):
        from context_engineering.compaction import create_context_manager
        from context_engineering.core import Budget

        mgr = create_context_manager(
            budget=Budget(max_tokens=100),
            summarize_after_turns=3,
            preserve_recent_turns=1,
            token_estimator=_words,
        )
        for i in range(4):
            mgr.add_turn("user", f"message number {i} with some extra words")
        result = mgr.compile()
        summary = next(t for t in result.turns if t.is_summary)
        assert summary.tokens == _words(summary.content)
        assert self._sum(result) == result.total_tokens

    def test_causal_scoring_normalizes_timestamps(self, monkeypatch):
        from context_engineering import compaction
        from context_engineering.compaction import create_context_manager
        from context_engineering.core import Budget

        clock = iter([1_700_000_000.0, 1_700_000_001.0, 1_700_000_002.0])
        monkeypatch.setattr(compaction.time, "time", lambda: next(clock))

        mgr = create_context_manager(
            budget=Budget(max_tokens=3), preserve_recent_turns=1, token_estimator=_words
        )
        # Related to an in-progress (non-active) task: 1.2x multiplier, oldest.
        mgr.add_turn("user", "side task", task_id="t-side")
        # Untagged and newer: on TS's 0-10 recency scale it outranks the
        # older side-task turn ((5 + 10 * 0.7) * 1.0 > (5 + 0) * 1.2). Raw
        # Unix timestamps made recency dominate everything instead.
        mgr.add_turn("assistant", "fresh context")
        mgr.add_turn("user", "now")
        mgr.set_beads_graph([{"id": "t-side", "status": "in_progress"}])

        result = mgr.compile()
        assert [t.content for t in result.turns] == ["fresh context", "now"]
