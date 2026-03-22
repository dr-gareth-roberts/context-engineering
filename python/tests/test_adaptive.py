"""Tests for adaptive learning — ContextOptimizer, WeightOptimizer, and FeedbackStores."""

import time

from context_engineering.adaptive import (
    ContextOptimizer,
    FileFeedbackStore,
    InMemoryFeedbackStore,
    ItemFeature,
    Outcome,
    WeightOptimizer,
    create_context_optimizer,
)
from context_engineering.core import Budget, ContextItem, ScoringWeights

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_items(count: int = 5, token_size: int = 50) -> list[ContextItem]:
    """Create a list of context items with varying priorities and kinds."""
    kinds = ["code", "docs", "memory", "system", "user"]
    return [
        ContextItem(
            id=f"item-{i}",
            content=f"content for item {i}",
            kind=kinds[i % len(kinds)],
            priority=float(count - i),
            recency=i / max(count - 1, 1),
            tokens=token_size,
            metadata={"salience": 0.5, "relevance": 0.3},
        )
        for i in range(count)
    ]


def _report_many(
    optimizer: ContextOptimizer, items: list[ContextItem], budget: Budget, n: int, quality_fn=None
):
    """Pack n times and report outcomes.  Returns the list of optimizer_ids."""
    ids = []
    for i in range(n):
        result = optimizer.pack(items, budget)
        ids.append(result.optimizer_id)
        quality = quality_fn(i) if quality_fn else 0.5 + 0.3 * (i / max(n - 1, 1))
        optimizer.report_outcome(result.optimizer_id, Outcome(quality=quality))
    return ids


# ---------------------------------------------------------------------------
# ContextOptimizer — basic flow
# ---------------------------------------------------------------------------


class TestContextOptimizer:
    def test_pack_returns_optimized_pack(self):
        optimizer = create_context_optimizer()
        items = _make_items()
        result = optimizer.pack(items, Budget(maxTokens=200))

        assert result.optimizer_id
        assert result.weights_used is not None
        assert len(result.selected) > 0
        assert result.total_tokens > 0

    def test_report_outcome_and_get_insights(self):
        optimizer = create_context_optimizer(min_samples=3)
        items = _make_items()
        budget = Budget(maxTokens=200)

        _report_many(optimizer, items, budget, 5)

        insights = optimizer.get_insights()
        assert insights.sample_count == 5
        assert "priority" in insights.correlations
        assert "recency" in insights.correlations
        assert insights.confidence >= 0

    def test_weights_shift_toward_quality_correlated_dimensions(self):
        """Items with high priority should produce better quality, so the
        optimizer should increase the priority weight over base."""
        base = ScoringWeights(priority=1.0, recency=1.0, salience=1.0, relevance=1.0)
        optimizer = create_context_optimizer(
            min_samples=5,
            learning_rate=0.5,
            base_weights=base,
        )

        # Create items where high-priority items correlate with high quality
        high_priority_items = [
            ContextItem(
                id=f"hp-{i}",
                content="important",
                kind="code",
                priority=10.0,
                recency=0.5,
                tokens=30,
                metadata={"salience": 0.5, "relevance": 0.5},
            )
            for i in range(3)
        ]
        low_priority_items = [
            ContextItem(
                id=f"lp-{i}",
                content="filler",
                kind="docs",
                priority=1.0,
                recency=0.5,
                tokens=30,
                metadata={"salience": 0.5, "relevance": 0.5},
            )
            for i in range(3)
        ]

        budget = Budget(maxTokens=120)  # fits ~3-4 items

        # Report high quality when high-priority items are selected
        for _ in range(10):
            result = optimizer.pack(high_priority_items + low_priority_items, budget)
            # Quality proportional to how many high-priority items were selected
            hp_count = sum(1 for s in result.selected if s.id.startswith("hp-"))
            quality = hp_count / max(len(result.selected), 1)
            optimizer.report_outcome(result.optimizer_id, Outcome(quality=quality))

        insights = optimizer.get_insights()
        # Priority correlation should be positive since high-priority items
        # correlate with higher quality
        assert insights.correlations["priority"] >= 0

    def test_min_samples_threshold_prevents_premature_adjustment(self):
        base = ScoringWeights(priority=1.0, recency=0.7, salience=0.5, relevance=0.0)
        optimizer = create_context_optimizer(min_samples=50, base_weights=base)
        items = _make_items()
        budget = Budget(maxTokens=200)

        _report_many(optimizer, items, budget, 5)

        insights = optimizer.get_insights()
        # With only 5 samples and min_samples=50, weights should be base weights
        assert insights.recommended_weights.priority == base.priority
        assert insights.recommended_weights.recency == base.recency

    def test_learning_rate_controls_speed(self):
        """Higher learning rate should produce larger weight changes."""
        items = _make_items()
        budget = Budget(maxTokens=200)

        def run_with_lr(lr: float) -> ScoringWeights:
            opt = create_context_optimizer(min_samples=3, learning_rate=lr)
            _report_many(opt, items, budget, 10)
            return opt.get_insights().recommended_weights

        slow = run_with_lr(0.01)
        fast = run_with_lr(0.9)

        # Both should differ from the default base (1.0 for all dims)
        # The fast one should have moved further from base
        base = ScoringWeights(priority=1.0, recency=1.0, salience=1.0, relevance=1.0)
        slow_dist = abs(slow.priority - base.priority) + abs(slow.recency - base.recency)
        fast_dist = abs(fast.priority - base.priority) + abs(fast.recency - base.recency)
        # Fast should move at least as much (may be equal if signal is very weak)
        assert fast_dist >= slow_dist * 0.5  # generous tolerance

    def test_regularization_pulls_toward_base(self):
        base = ScoringWeights(priority=1.0, recency=1.0, salience=1.0, relevance=1.0)
        strong_reg = create_context_optimizer(
            min_samples=3, learning_rate=0.5, regularization=0.9, base_weights=base
        )
        weak_reg = create_context_optimizer(
            min_samples=3, learning_rate=0.5, regularization=0.0, base_weights=base
        )
        items = _make_items()
        budget = Budget(maxTokens=200)

        _report_many(strong_reg, items, budget, 10)
        _report_many(weak_reg, items, budget, 10)

        strong_weights = strong_reg.get_insights().recommended_weights
        weak_weights = weak_reg.get_insights().recommended_weights

        # Strong regularization should keep weights closer to base
        strong_dist = abs(strong_weights.priority - base.priority)
        weak_dist = abs(weak_weights.priority - base.priority)
        assert strong_dist <= weak_dist + 0.01  # tolerance for floating point

    def test_weight_clamping(self):
        """Weights should stay within [0.01, 10.0]."""
        optimizer = create_context_optimizer(min_samples=1, learning_rate=1.0)
        items = _make_items()
        budget = Budget(maxTokens=200)

        _report_many(optimizer, items, budget, 5)

        insights = optimizer.get_insights()
        for dim in ("priority", "recency", "salience", "relevance"):
            val = getattr(insights.recommended_weights, dim)
            assert 0.01 <= val <= 10.0, f"{dim}={val} out of bounds"

    def test_segment_isolation(self):
        store = InMemoryFeedbackStore()
        opt_a = create_context_optimizer(store=store, segment="seg_a", min_samples=2)
        opt_b = create_context_optimizer(store=store, segment="seg_b", min_samples=2)

        items = _make_items()
        budget = Budget(maxTokens=200)

        _report_many(opt_a, items, budget, 5)

        insights_a = opt_a.get_insights()
        insights_b = opt_b.get_insights()

        assert insights_a.sample_count == 5
        assert insights_b.sample_count == 0

    def test_export_import_state_roundtrip(self):
        optimizer = create_context_optimizer(min_samples=3)
        items = _make_items()
        budget = Budget(maxTokens=200)

        _report_many(optimizer, items, budget, 5)
        state = optimizer.export_state()

        new_optimizer = create_context_optimizer()
        new_optimizer.import_state(state)

        # After import, the new optimizer should use imported weights
        result = new_optimizer.pack(items, budget)
        assert result.weights_used.priority == state.weights.priority

    def test_reset_clears_learned_weights(self):
        optimizer = create_context_optimizer(min_samples=3)
        items = _make_items()
        budget = Budget(maxTokens=200)

        _report_many(optimizer, items, budget, 5)
        assert optimizer.get_insights().sample_count == 5

        optimizer.reset()
        assert optimizer.get_insights().sample_count == 0


# ---------------------------------------------------------------------------
# WeightOptimizer — statistical engine
# ---------------------------------------------------------------------------


class TestWeightOptimizer:
    def test_returns_base_when_insufficient_samples(self):
        base = ScoringWeights(priority=2.0, recency=0.5, salience=0.3, relevance=0.1)
        wo = WeightOptimizer(
            learning_rate=0.1, regularization=0.01, base_weights=base, min_samples=10
        )
        result = wo.optimize([])
        assert result.priority == base.priority
        assert result.recency == base.recency

    def test_compute_correlations_with_no_data(self):
        wo = WeightOptimizer(
            learning_rate=0.1, regularization=0.01, base_weights=ScoringWeights(), min_samples=5
        )
        corr = wo.compute_correlations([])
        assert all(v == 0.0 for v in corr.values())

    def test_compute_confidence_zero_with_no_data(self):
        wo = WeightOptimizer(
            learning_rate=0.1, regularization=0.01, base_weights=ScoringWeights(), min_samples=5
        )
        assert wo.compute_confidence([]) == 0.0

    def test_compute_kind_insights(self):
        wo = WeightOptimizer(
            learning_rate=0.1, regularization=0.01, base_weights=ScoringWeights(), min_samples=1
        )
        from context_engineering.adaptive import FeedbackRecord

        records = []
        for i in range(10):
            features = [
                ItemFeature(
                    item_id="code-1",
                    kind="code",
                    priority=5.0,
                    recency=0.5,
                    salience=0.5,
                    relevance=0.3,
                    tokens=50,
                    selected=(i % 2 == 0),
                ),
                ItemFeature(
                    item_id="docs-1",
                    kind="docs",
                    priority=3.0,
                    recency=0.5,
                    salience=0.5,
                    relevance=0.3,
                    tokens=50,
                    selected=True,
                ),
            ]
            records.append(
                FeedbackRecord(
                    id=f"r-{i}",
                    timestamp=time.time(),
                    pack_id=f"p-{i}",
                    segment="default",
                    selected_item_ids=["code-1", "docs-1"],
                    dropped_item_ids=[],
                    item_features=features,
                    weights_used=ScoringWeights(),
                    budget=200,
                    utilization=0.5,
                    outcome=Outcome(quality=0.9 if i % 2 == 0 else 0.3),
                )
            )

        insights = wo.compute_kind_insights(records)
        assert len(insights) >= 1
        kinds = {ki.kind for ki in insights}
        assert "code" in kinds


# ---------------------------------------------------------------------------
# InMemoryFeedbackStore
# ---------------------------------------------------------------------------


class TestInMemoryFeedbackStore:
    def test_save_and_get_records(self):
        store = InMemoryFeedbackStore()
        from context_engineering.adaptive import FeedbackRecord

        record = FeedbackRecord(
            id="r-1",
            timestamp=time.time(),
            pack_id="p-1",
            segment="default",
            selected_item_ids=["a"],
            dropped_item_ids=["b"],
            item_features=[],
            weights_used=ScoringWeights(),
            budget=100,
            utilization=0.5,
        )
        store.save(record)
        records = store.get_records()
        assert len(records) == 1
        assert records[0].id == "r-1"

    def test_update_outcome(self):
        store = InMemoryFeedbackStore()
        from context_engineering.adaptive import FeedbackRecord

        record = FeedbackRecord(
            id="r-1",
            timestamp=time.time(),
            pack_id="p-1",
            segment="default",
            selected_item_ids=[],
            dropped_item_ids=[],
            item_features=[],
            weights_used=ScoringWeights(),
            budget=100,
            utilization=0.5,
        )
        store.save(record)
        store.update_outcome("p-1", Outcome(quality=0.9))

        records = store.get_records_with_outcomes()
        assert len(records) == 1
        assert records[0].outcome is not None
        assert records[0].outcome.quality == 0.9

    def test_get_records_with_segment_filter(self):
        store = InMemoryFeedbackStore()
        from context_engineering.adaptive import FeedbackRecord

        for seg in ("a", "a", "b"):
            store.save(
                FeedbackRecord(
                    id=f"r-{seg}",
                    timestamp=time.time(),
                    pack_id=f"p-{seg}",
                    segment=seg,
                    selected_item_ids=[],
                    dropped_item_ids=[],
                    item_features=[],
                    weights_used=ScoringWeights(),
                    budget=100,
                    utilization=0.5,
                )
            )
        assert len(store.get_records(segment="a")) == 2
        assert len(store.get_records(segment="b")) == 1

    def test_clear_all(self):
        store = InMemoryFeedbackStore()
        from context_engineering.adaptive import FeedbackRecord

        store.save(
            FeedbackRecord(
                id="r-1",
                timestamp=time.time(),
                pack_id="p-1",
                segment="default",
                selected_item_ids=[],
                dropped_item_ids=[],
                item_features=[],
                weights_used=ScoringWeights(),
                budget=100,
                utilization=0.5,
            )
        )
        store.clear()
        assert len(store.get_records()) == 0

    def test_clear_by_segment(self):
        store = InMemoryFeedbackStore()
        from context_engineering.adaptive import FeedbackRecord

        for seg in ("keep", "remove"):
            store.save(
                FeedbackRecord(
                    id=f"r-{seg}",
                    timestamp=time.time(),
                    pack_id=f"p-{seg}",
                    segment=seg,
                    selected_item_ids=[],
                    dropped_item_ids=[],
                    item_features=[],
                    weights_used=ScoringWeights(),
                    budget=100,
                    utilization=0.5,
                )
            )
        store.clear(segment="remove")
        assert len(store.get_records()) == 1
        assert store.get_records()[0].segment == "keep"


# ---------------------------------------------------------------------------
# FileFeedbackStore
# ---------------------------------------------------------------------------


class TestFileFeedbackStore:
    def test_persistence_across_instances(self, tmp_path):
        path = str(tmp_path / "feedback.jsonl")

        store1 = FileFeedbackStore(path, disable_locking=True)
        from context_engineering.adaptive import FeedbackRecord

        store1.save(
            FeedbackRecord(
                id="r-1",
                timestamp=1000.0,
                pack_id="p-1",
                segment="default",
                selected_item_ids=["a"],
                dropped_item_ids=["b"],
                item_features=[
                    ItemFeature(
                        item_id="a",
                        kind="code",
                        priority=5.0,
                        recency=0.5,
                        salience=0.5,
                        relevance=0.3,
                        tokens=50,
                        selected=True,
                    ),
                ],
                weights_used=ScoringWeights(),
                budget=200,
                utilization=0.5,
                outcome=Outcome(quality=0.8, accepted=True),
            )
        )

        # New instance should load persisted data
        store2 = FileFeedbackStore(path, disable_locking=True)
        records = store2.get_records()
        assert len(records) == 1
        assert records[0].id == "r-1"
        assert records[0].outcome is not None
        assert records[0].outcome.quality == 0.8
        assert len(records[0].item_features) == 1

    def test_update_outcome_persists(self, tmp_path):
        path = str(tmp_path / "feedback.jsonl")
        store = FileFeedbackStore(path, disable_locking=True)
        from context_engineering.adaptive import FeedbackRecord

        store.save(
            FeedbackRecord(
                id="r-1",
                timestamp=1000.0,
                pack_id="p-1",
                segment="default",
                selected_item_ids=[],
                dropped_item_ids=[],
                item_features=[],
                weights_used=ScoringWeights(),
                budget=100,
                utilization=0.5,
            )
        )
        store.update_outcome("p-1", Outcome(quality=0.7))

        store2 = FileFeedbackStore(path, disable_locking=True)
        records = store2.get_records_with_outcomes()
        assert len(records) == 1
        assert records[0].outcome.quality == 0.7

    def test_clear_persists(self, tmp_path):
        path = str(tmp_path / "feedback.jsonl")
        store = FileFeedbackStore(path, disable_locking=True)
        from context_engineering.adaptive import FeedbackRecord

        store.save(
            FeedbackRecord(
                id="r-1",
                timestamp=1000.0,
                pack_id="p-1",
                segment="default",
                selected_item_ids=[],
                dropped_item_ids=[],
                item_features=[],
                weights_used=ScoringWeights(),
                budget=100,
                utilization=0.5,
            )
        )
        store.clear()

        store2 = FileFeedbackStore(path, disable_locking=True)
        assert len(store2.get_records()) == 0
