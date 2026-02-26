"""Tests for the bridge module: MemoryItem -> ContextItem conversion."""

from datetime import datetime, timezone

from context_engineering.bridge import BridgeOptions, memory_to_context, to_context_item
from context_engineering.memory import MemoryItem


def _make_memory(
    id: str = "m1",
    content: str = "test content",
    created_at: str | None = None,
    salience: float = 0.8,
    **kwargs,
) -> MemoryItem:
    return MemoryItem(
        id=id,
        content=content,
        createdAt=created_at or datetime.now(timezone.utc).isoformat(),
        salience=salience,
        **kwargs,
    )


class TestToContextItem:
    def test_basic_conversion(self):
        mem = _make_memory()
        item = to_context_item(mem)
        assert item.id == "m1"
        assert item.content == "test content"
        assert item.kind == "memory"
        assert item.priority == 5.0

    def test_recency_decays_with_age(self):
        now_ms = 1000000000000  # fixed reference
        recent = _make_memory(id="recent", created_at="2001-09-09T01:46:40+00:00")  # exactly now_ms
        old = _make_memory(id="old", created_at="2001-09-08T01:46:40+00:00")  # 1 day earlier

        opts = BridgeOptions(now=now_ms)
        recent_item = to_context_item(recent, opts)
        old_item = to_context_item(old, opts)

        assert recent_item.recency > old_item.recency

    def test_fresh_item_has_high_recency(self):
        now_ms = datetime.now(timezone.utc).timestamp() * 1000
        mem = _make_memory(created_at=datetime.now(timezone.utc).isoformat())
        opts = BridgeOptions(now=now_ms)
        item = to_context_item(mem, opts)
        assert item.recency >= 9.0  # nearly 10.0 for just-created

    def test_salience_mapped_to_metadata(self):
        mem = _make_memory(salience=0.75)
        item = to_context_item(mem)
        assert item.metadata["salience"] == 0.75

    def test_none_salience_defaults_to_1(self):
        mem = _make_memory(salience=None)
        item = to_context_item(mem)
        assert item.metadata["salience"] == 1.0

    def test_custom_priority(self):
        opts = BridgeOptions(priority=9.0)
        item = to_context_item(_make_memory(), opts)
        assert item.priority == 9.0

    def test_custom_kind(self):
        opts = BridgeOptions(kind="document")
        item = to_context_item(_make_memory(), opts)
        assert item.kind == "document"

    def test_half_life_affects_decay_rate(self):
        now_ms = 1000000000000
        mem = _make_memory(created_at="2001-09-08T20:46:40+00:00")  # ~5h ago

        fast_decay = BridgeOptions(now=now_ms, recency_half_life=3600)  # 1h half-life
        slow_decay = BridgeOptions(now=now_ms, recency_half_life=86400)  # 24h half-life

        fast_item = to_context_item(mem, fast_decay)
        slow_item = to_context_item(mem, slow_decay)

        assert slow_item.recency > fast_item.recency

    def test_created_at_in_metadata(self):
        mem = _make_memory(created_at="2024-01-15T10:00:00+00:00")
        item = to_context_item(mem)
        assert item.metadata["createdAt"] == "2024-01-15T10:00:00+00:00"

    def test_updated_at_in_metadata_when_present(self):
        mem = _make_memory(updatedAt="2024-01-16T10:00:00+00:00")
        item = to_context_item(mem)
        assert item.metadata["updatedAt"] == "2024-01-16T10:00:00+00:00"

    def test_updated_at_absent_when_none(self):
        mem = _make_memory()
        item = to_context_item(mem)
        assert "updatedAt" not in item.metadata

    def test_preserves_existing_metadata(self):
        mem = _make_memory(metadata={"source": "test", "tags": ["a"]})
        item = to_context_item(mem)
        assert item.metadata["source"] == "test"
        assert item.metadata["tags"] == ["a"]


class TestMemoryToContext:
    def test_batch_conversion(self):
        memories = [_make_memory(id=f"m{i}") for i in range(5)]
        items = memory_to_context(memories)
        assert len(items) == 5
        assert all(item.kind == "memory" for item in items)

    def test_empty_list(self):
        assert memory_to_context([]) == []

    def test_options_applied_to_all(self):
        memories = [_make_memory(id=f"m{i}") for i in range(3)]
        opts = BridgeOptions(priority=8.0, kind="doc")
        items = memory_to_context(memories, opts)
        assert all(item.priority == 8.0 for item in items)
        assert all(item.kind == "doc" for item in items)
