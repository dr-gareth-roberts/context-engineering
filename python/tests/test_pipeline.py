"""Tests for composable context pipeline."""

from context_engineering.allocation import KindAllocation
from context_engineering.core import Budget, ContextItem
from context_engineering.pipeline import create_pipeline
from context_engineering.session import create_session


def make_item(id: str, kind: str, priority: float, tokens: int) -> ContextItem:
    return ContextItem(id=id, content=f"content-{id}", kind=kind, priority=priority, tokens=tokens)


class TestPipeline:
    def test_numeric_budget(self):
        result = create_pipeline(500).add(make_item("a", "system", 10, 50)).build()
        assert len(result.selected) == 1
        assert result.total_tokens == 50
        assert result.budget.max_tokens == 500

    def test_budget_object(self):
        result = (
            create_pipeline(Budget(max_tokens=500)).add(make_item("a", "system", 10, 50)).build()
        )
        assert len(result.selected) == 1

    def test_multiple_items(self):
        result = (
            create_pipeline(500)
            .add(make_item("a", "system", 10, 50), make_item("b", "retrieval", 7, 50))
            .build()
        )
        assert len(result.selected) == 2
        assert result.input_count == 2

    def test_add_many_with_defaults(self):
        items = [
            ContextItem(id="r1", content="doc 1", tokens=50),
            ContextItem(id="r2", content="doc 2", tokens=50),
        ]
        result = create_pipeline(500).add_many(items, kind="retrieval", priority=5).build()
        assert len(result.selected) == 2
        assert result.selected[0].kind == "retrieval"

    def test_budget_constraint(self):
        result = (
            create_pipeline(100)
            .add(make_item("a", "system", 10, 60), make_item("b", "retrieval", 5, 60))
            .build()
        )
        assert result.total_tokens <= 100
        assert len(result.dropped) > 0

    def test_allocation(self):
        result = (
            create_pipeline(300)
            .add(
                make_item("s", "system", 10, 50),
                make_item("r1", "retrieval", 7, 100),
                make_item("r2", "retrieval", 6, 100),
            )
            .allocate(
                [
                    KindAllocation(kind="system", target_ratio=0.3),
                    KindAllocation(kind="retrieval", target_ratio=0.7),
                ]
            )
            .build()
        )
        assert "allocate" in result.stages
        assert result.allocations is not None

    def test_cache_topology(self):
        result = (
            create_pipeline(500)
            .add(make_item("sys", "system", 10, 100), make_item("q", "query", 8, 50))
            .cache_topology(provider="anthropic")
            .build()
        )
        assert "cacheTopology" in result.stages
        assert result.cache_key is not None
        assert result.cache_efficiency is not None

    def test_cache_topology_ordering(self):
        result = (
            create_pipeline(500)
            .add(make_item("q", "query", 8, 50), make_item("sys", "system", 10, 50))
            .cache_topology()
            .build()
        )
        assert result.selected[0].id == "sys"
        assert result.selected[1].id == "q"

    def test_placement(self):
        result = (
            create_pipeline(500)
            .add(
                make_item("a", "system", 10, 50),
                make_item("b", "retrieval", 7, 50),
            )
            .place("score-order")
            .build()
        )
        assert "place" in result.stages

    def test_quality_gate(self):
        result = (
            create_pipeline(500)
            .add(make_item("a", "system", 10, 100), make_item("b", "retrieval", 7, 100))
            .quality_gate(min_overall=0.0)
            .build()
        )
        assert "quality" in result.stages
        assert result.quality is not None
        assert result.quality.overall > 0

    def test_session_tracking(self):
        session = create_session(Budget(max_tokens=500))

        r1 = create_pipeline(500).add(make_item("a", "system", 10, 50)).session(session).build()
        assert "session" in r1.stages
        assert r1.delta is None

        r2 = create_pipeline(500).add(make_item("a", "system", 10, 50)).session(session).build()
        assert r2.delta is not None
        assert r2.delta.kept_count == 1

    def test_full_pipeline(self):
        session = create_session(Budget(max_tokens=500))

        result = (
            create_pipeline(500)
            .add(
                make_item("sys", "system", 10, 100),
                make_item("mem", "memory", 5, 80),
                make_item("doc", "retrieval", 7, 80),
                make_item("q", "query", 8, 50),
            )
            .allocate(
                [
                    KindAllocation(kind="system", target_ratio=0.3),
                    KindAllocation(kind="memory", target_ratio=0.2),
                    KindAllocation(kind="retrieval", target_ratio=0.3),
                    KindAllocation(kind="query", target_ratio=0.2),
                ]
            )
            .cache_topology(provider="anthropic")
            .place("score-order")
            .quality_gate()
            .session(session)
            .build()
        )

        assert len(result.selected) > 0
        assert "allocate" in result.stages
        assert "cacheTopology" in result.stages
        assert "place" in result.stages
        assert "quality" in result.stages
        assert "session" in result.stages

    def test_empty_pipeline(self):
        result = create_pipeline(500).build()
        assert len(result.selected) == 0
        assert result.total_tokens == 0

    def test_stages_recorded(self):
        result = (
            create_pipeline(500)
            .add(make_item("a", "system", 10, 50))
            .cache_topology()
            .quality_gate()
            .build()
        )
        assert "cacheTopology" in result.stages
        assert "quality" in result.stages
        assert "allocate" not in result.stages
