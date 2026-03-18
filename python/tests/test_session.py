"""Tests for differential context sessions."""

import threading

from context_engineering.core import Budget, ContextItem
from context_engineering.session import create_session


def make_item(id: str, priority: float, tokens: int) -> ContextItem:
    return ContextItem(id=id, content=f"content-{id}", priority=priority, tokens=tokens)


class TestCreateSession:
    def test_compiles_items(self):
        session = create_session(Budget(max_tokens=500))
        session.set_items([make_item("a", 10, 50), make_item("b", 5, 50)])

        result = session.compile()
        assert len(result.selected) == 2
        assert result.total_tokens == 100
        assert result.compile_count == 1

    def test_null_delta_on_first_compile(self):
        session = create_session(Budget(max_tokens=500))
        session.set_items([make_item("a", 10, 50)])
        result = session.compile()
        assert result.delta is None

    def test_delta_on_subsequent_compiles(self):
        session = create_session(Budget(max_tokens=500))
        session.set_items([make_item("a", 10, 50), make_item("b", 5, 50)])
        session.compile()

        # Same items — everything reused
        r2 = session.compile()
        assert r2.delta is not None
        assert len(r2.delta.added) == 0
        assert len(r2.delta.removed_ids) == 0
        assert r2.delta.kept_count == 2
        assert r2.delta.reuse_ratio == 1

    def test_detects_added_items(self):
        session = create_session(Budget(max_tokens=500))
        session.set_items([make_item("a", 10, 50)])
        session.compile()

        session.add_items([make_item("b", 5, 50)])
        r2 = session.compile()

        assert len(r2.delta.added) == 1
        assert r2.delta.added[0].id == "b"
        assert r2.delta.kept_count == 1

    def test_detects_removed_items(self):
        session = create_session(Budget(max_tokens=500))
        session.set_items([make_item("a", 10, 50), make_item("b", 5, 50)])
        session.compile()

        session.remove_items(["b"])
        r2 = session.compile()

        assert "b" in r2.delta.removed_ids
        assert r2.delta.kept_count == 1

    def test_detects_changed_items(self):
        session = create_session(Budget(max_tokens=500))
        session.set_items(
            [
                ContextItem(id="a", content="original content", priority=10, tokens=50),
            ]
        )
        session.compile()

        session.set_items(
            [
                ContextItem(id="a", content="modified content", priority=10, tokens=50),
            ]
        )
        r2 = session.compile()

        assert len(r2.delta.changed) == 1
        assert r2.delta.changed[0].id == "a"
        assert r2.delta.kept_count == 0

    def test_reuse_ratio(self):
        session = create_session(Budget(max_tokens=500))
        session.set_items([make_item("a", 10, 100), make_item("b", 5, 100)])
        session.compile()

        session.set_items([make_item("a", 10, 100), make_item("c", 5, 100)])
        r2 = session.compile()

        assert r2.delta.reusable_tokens == 100
        assert r2.delta.reuse_ratio == 0.5

    def test_reordering_breaks_prefix_reuse(self):
        session = create_session(Budget(max_tokens=500))
        session.set_items([make_item("a", 10, 100), make_item("b", 9, 100)])
        first = session.compile()

        session.set_items([make_item("b", 10, 100), make_item("a", 9, 100)])
        second = session.compile()

        assert second.delta is not None
        assert second.delta.kept_count == 2
        assert second.delta.reusable_tokens == 0
        assert second.delta.reuse_ratio == 0
        assert second.cache_key == first.cache_key

    def test_delta_tokens(self):
        session = create_session(Budget(max_tokens=500))
        session.set_items([make_item("a", 10, 100)])
        session.compile()

        session.set_items([make_item("a", 10, 100), make_item("b", 5, 50)])
        r2 = session.compile()

        assert r2.delta.delta_tokens == 50  # only b is new

    def test_compile_count(self):
        session = create_session(Budget(max_tokens=500))
        session.set_items([make_item("a", 10, 50)])

        assert session.get_compile_count() == 0
        session.compile()
        assert session.get_compile_count() == 1
        session.compile()
        assert session.get_compile_count() == 2

    def test_clear(self):
        session = create_session(Budget(max_tokens=500))
        session.set_items([make_item("a", 10, 50)])
        session.compile()

        session.clear()
        assert session.item_count() == 0
        assert session.get_compile_count() == 0

        session.set_items([make_item("b", 5, 50)])
        result = session.compile()
        assert result.delta is None

    def test_add_items_deduplicates(self):
        session = create_session(Budget(max_tokens=500))
        session.set_items([make_item("a", 10, 50)])
        session.add_items([make_item("a", 8, 60)])
        assert session.item_count() == 1

    def test_respects_budget(self):
        session = create_session(Budget(max_tokens=100))
        session.set_items([make_item("a", 10, 60), make_item("b", 5, 60)])

        result = session.compile()
        assert result.total_tokens <= 100
        assert len(result.dropped) > 0

    def test_multiple_rounds(self):
        session = create_session(Budget(max_tokens=500))

        # Round 1
        session.set_items([make_item("a", 10, 50)])
        session.compile()

        # Round 2: add b
        session.add_items([make_item("b", 5, 50)])
        r2 = session.compile()
        assert len(r2.delta.added) == 1
        assert r2.delta.kept_count == 1

        # Round 3: remove a, add c
        session.remove_items(["a"])
        session.add_items([make_item("c", 3, 50)])
        r3 = session.compile()
        assert len(r3.delta.added) == 1
        assert "a" in r3.delta.removed_ids
        assert r3.delta.kept_count == 1

    def test_reordered_items_break_prefix_reuse(self):
        session = create_session(Budget(max_tokens=500))
        session.set_items([make_item("a", 10, 100), make_item("b", 9, 80)])
        session.compile()

        session.set_items([make_item("b", 10, 80), make_item("a", 9, 100)])
        second = session.compile()

        assert second.delta is not None
        assert second.delta.kept_count == 2
        assert second.delta.reusable_tokens == 0
        assert second.delta.reuse_ratio == 0
        assert second.cache_key

    def test_only_unchanged_prefix_counts_as_reusable(self):
        session = create_session(Budget(max_tokens=500))
        session.set_items(
            [
                ContextItem(id="a", content="stable", priority=10, tokens=100),
                ContextItem(id="b", content="old", priority=9, tokens=80),
                ContextItem(id="c", content="also-stable", priority=8, tokens=60),
            ]
        )
        session.compile()

        session.set_items(
            [
                ContextItem(id="a", content="stable", priority=10, tokens=100),
                ContextItem(id="b", content="new", priority=9, tokens=80),
                ContextItem(id="c", content="also-stable", priority=8, tokens=60),
            ]
        )
        result = session.compile()

        assert result.delta is not None
        assert result.delta.reusable_tokens == 100
        assert result.delta.reuse_ratio == 0.417


def test_concurrent_compile_is_thread_safe():
    session = create_session(Budget(max_tokens=10000))
    for i in range(20):
        session.add_items([ContextItem(id=f"item-{i}", content=f"content {i}", tokens=10)])

    results = []
    errors = []

    def do_compile():
        try:
            result = session.compile()
            results.append(result)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=do_compile) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Thread errors: {errors}"
    assert len(results) == 10
