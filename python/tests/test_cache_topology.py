"""Tests for cache-topology-aware packing."""

from context_engineering.cache_topology import (
    CacheConfig,
    classify_volatility,
    pack_with_cache_topology,
)
from context_engineering.core import Budget, ContextItem


def make_item(id: str, kind: str, priority: float, tokens: int) -> ContextItem:
    return ContextItem(id=id, content=f"content-{id}", kind=kind, priority=priority, tokens=tokens)


class TestClassifyVolatility:
    def test_static_kinds(self):
        for kind in ("system", "tool", "schema", "example", "instruction"):
            assert classify_volatility(ContextItem(id="a", content="", kind=kind)) == "static"

    def test_session_kinds(self):
        for kind in ("memory", "conversation", "history"):
            assert classify_volatility(ContextItem(id="a", content="", kind=kind)) == "session"

    def test_request_kinds(self):
        for kind in ("query", "retrieval", "tool-result"):
            assert classify_volatility(ContextItem(id="a", content="", kind=kind)) == "request"

    def test_defaults_to_request(self):
        assert classify_volatility(ContextItem(id="a", content="", kind="unknown")) == "request"
        assert classify_volatility(ContextItem(id="a", content="")) == "request"

    def test_explicit_volatility_in_metadata(self):
        item = ContextItem(id="a", content="", kind="query", metadata={"volatility": "static"})
        assert classify_volatility(item) == "static"


class TestPackWithCacheTopology:
    def test_partitions_items(self):
        items = [
            make_item("sys", "system", 10, 100),
            make_item("mem", "memory", 5, 100),
            make_item("q", "query", 8, 100),
        ]
        result = pack_with_cache_topology(items, Budget(max_tokens=500))
        assert len(result.selected) == 3
        assert result.stats["staticCount"] == 1
        assert result.stats["sessionCount"] == 1
        assert result.stats["requestCount"] == 1

    def test_orders_static_session_request(self):
        items = [
            make_item("q", "query", 8, 50),
            make_item("sys", "system", 10, 50),
            make_item("mem", "memory", 5, 50),
        ]
        result = pack_with_cache_topology(items, Budget(max_tokens=500))
        assert result.selected[0].id == "sys"
        assert result.selected[1].id == "mem"
        assert result.selected[2].id == "q"

    def test_sorts_static_by_id(self):
        items = [
            make_item("z-tool", "tool", 5, 50),
            make_item("a-system", "system", 5, 50),
            make_item("m-schema", "schema", 5, 50),
        ]
        result = pack_with_cache_topology(items, Budget(max_tokens=500))
        assert result.selected[0].id == "a-system"
        assert result.selected[1].id == "m-schema"
        assert result.selected[2].id == "z-tool"

    def test_stable_cache_key(self):
        static = [
            make_item("sys", "system", 10, 50),
            make_item("tool", "tool", 8, 50),
        ]
        r1 = pack_with_cache_topology(
            [*static, make_item("q1", "query", 5, 50)],
            Budget(max_tokens=500),
        )
        r2 = pack_with_cache_topology(
            [*static, make_item("q2", "query", 5, 50)],
            Budget(max_tokens=500),
        )
        assert r1.cache_key == r2.cache_key

    def test_cache_key_changes_with_static(self):
        r1 = pack_with_cache_topology(
            [make_item("sys1", "system", 10, 50), make_item("q", "query", 5, 50)],
            Budget(max_tokens=500),
        )
        r2 = pack_with_cache_topology(
            [make_item("sys2", "system", 10, 50), make_item("q", "query", 5, 50)],
            Budget(max_tokens=500),
        )
        assert r1.cache_key != r2.cache_key

    def test_cache_efficiency(self):
        items = [
            make_item("sys", "system", 10, 300),
            make_item("q", "query", 5, 100),
        ]
        result = pack_with_cache_topology(items, Budget(max_tokens=500))
        assert result.cacheable_tokens == 300
        assert result.volatile_tokens == 100
        assert result.cache_efficiency == 0.75

    def test_budget_constraints(self):
        items = [
            make_item("sys", "system", 10, 200),
            make_item("mem", "memory", 5, 200),
            make_item("q", "query", 8, 200),
        ]
        result = pack_with_cache_topology(items, Budget(max_tokens=400))
        assert result.total_tokens <= 400
        assert len(result.dropped) > 0

    def test_breakpoint_markers(self):
        items = [
            make_item("sys", "system", 10, 50),
            make_item("mem", "memory", 5, 50),
            make_item("q", "query", 8, 50),
        ]
        result = pack_with_cache_topology(
            items,
            Budget(max_tokens=500),
            cache_config=CacheConfig(mark_breakpoints=True),
        )
        static_end = next(
            (
                i
                for i in result.selected
                if (i.metadata or {}).get("_cacheBreakpoint") == "static-end"
            ),
            None,
        )
        assert static_end is not None

    def test_empty_pack(self):
        result = pack_with_cache_topology([], Budget(max_tokens=500))
        assert len(result.selected) == 0
        assert result.total_tokens == 0
        assert result.cache_efficiency == 0

    def test_partition_boundaries(self):
        items = [
            make_item("s1", "system", 10, 50),
            make_item("s2", "system", 10, 50),
            make_item("m1", "memory", 5, 50),
            make_item("q1", "query", 8, 50),
        ]
        result = pack_with_cache_topology(items, Budget(max_tokens=500))
        assert result.partition_boundaries[0] == 2  # 2 static items
        assert result.partition_boundaries[1] == 3  # 2 static + 1 session
