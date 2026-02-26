"""Tests for the compaction module: multi-turn context management."""

from context_engineering.compaction import create_context_manager
from context_engineering.core import Budget, ContextItem


def _word_estimator(text: str) -> int:
    """Deterministic: 1 token per word."""
    trimmed = text.strip()
    if not trimmed:
        return 0
    return len(trimmed.split())


class TestContextManager:
    def test_tracks_turns(self):
        mgr = create_context_manager(
            budget=Budget(maxTokens=1000),
            token_estimator=_word_estimator,
        )
        assert mgr.turn_count() == 0
        mgr.add_turn("user", "hello world")
        assert mgr.turn_count() == 1
        mgr.add_turn("assistant", "hi there")
        assert mgr.turn_count() == 2

    def test_token_usage(self):
        mgr = create_context_manager(
            budget=Budget(maxTokens=100),
            token_estimator=_word_estimator,
        )
        mgr.add_turn("user", "one two three")  # 3 tokens
        mgr.add_turn("assistant", "four five")  # 2 tokens
        usage = mgr.get_token_usage()
        assert usage["used"] == 5
        assert usage["budget"] == 100
        assert usage["remaining"] == 95

    def test_compile_within_budget(self):
        mgr = create_context_manager(
            budget=Budget(maxTokens=1000),
            preserve_recent_turns=10,
            token_estimator=_word_estimator,
        )
        mgr.add_turn("user", "hello")
        mgr.add_turn("assistant", "world")
        result = mgr.compile()
        assert len(result.turns) == 2
        assert result.turns[0].role == "user"
        assert result.turns[0].content == "hello"
        assert result.turns[1].role == "assistant"
        assert result.turns[1].content == "world"
        assert result.total_tokens == 2

    def test_compacts_old_turns(self):
        mgr = create_context_manager(
            budget=Budget(maxTokens=500),
            summarize_after_turns=3,
            preserve_recent_turns=2,
            token_estimator=_word_estimator,
        )
        mgr.add_turn("user", "first message")
        mgr.add_turn("assistant", "first reply")
        mgr.add_turn("user", "second message")
        mgr.add_turn("assistant", "second reply")
        mgr.add_turn("user", "third message")

        result = mgr.compile()

        # Last 2 preserved
        last_two = result.turns[-2:]
        assert last_two[0].content == "second reply"
        assert last_two[1].content == "third message"

        # First turn is summary
        assert result.turns[0].is_summary
        assert "Summary of 3 earlier turns" in result.turns[0].content

    def test_preserves_recent_turns(self):
        mgr = create_context_manager(
            budget=Budget(maxTokens=500),
            summarize_after_turns=2,
            preserve_recent_turns=3,
            token_estimator=_word_estimator,
        )
        mgr.add_turn("user", "alpha")
        mgr.add_turn("assistant", "beta")
        mgr.add_turn("user", "gamma")
        mgr.add_turn("assistant", "delta")
        mgr.add_turn("user", "epsilon")

        result = mgr.compile()
        last_three = result.turns[-3:]
        assert last_three[0].content == "gamma"
        assert last_three[1].content == "delta"
        assert last_three[2].content == "epsilon"

    def test_add_items(self):
        mgr = create_context_manager(
            budget=Budget(maxTokens=1000),
            preserve_recent_turns=10,
            token_estimator=_word_estimator,
        )
        mgr.add_turn("user", "hello")
        mgr.add_items(
            [
                ContextItem(id="doc1", content="some context information", tokens=3),
                ContextItem(id="doc2", content="more context", tokens=2),
            ]
        )
        result = mgr.compile()
        assert len(result.items) == 2
        assert set(i.id for i in result.items) == {"doc1", "doc2"}
        assert result.total_tokens == 6  # 1 turn + 3 + 2 items

    def test_clear(self):
        mgr = create_context_manager(
            budget=Budget(maxTokens=1000),
            token_estimator=_word_estimator,
        )
        mgr.add_turn("user", "hello")
        mgr.add_items([ContextItem(id="x", content="data", tokens=5)])
        assert mgr.turn_count() == 1
        mgr.clear()
        assert mgr.turn_count() == 0
        usage = mgr.get_token_usage()
        assert usage["used"] == 0
        result = mgr.compile()
        assert len(result.turns) == 0
        assert len(result.items) == 0
        assert result.total_tokens == 0

    def test_system_prompt_budgeted(self):
        mgr = create_context_manager(
            budget=Budget(maxTokens=10),
            system_prompt="you are a helpful assistant",  # 5 tokens
            preserve_recent_turns=10,
            token_estimator=_word_estimator,
        )
        usage = mgr.get_token_usage()
        assert usage["used"] == 5
        assert usage["remaining"] == 5
        mgr.add_turn("user", "one two three")  # 3 tokens
        usage2 = mgr.get_token_usage()
        assert usage2["used"] == 8
        assert usage2["remaining"] == 2
        result = mgr.compile()
        assert result.total_tokens == 8

    def test_reserve_tokens(self):
        mgr = create_context_manager(
            budget=Budget(maxTokens=100, reserveTokens=30),
            token_estimator=_word_estimator,
        )
        usage = mgr.get_token_usage()
        assert usage["budget"] == 70
        assert usage["remaining"] == 70

    def test_items_sorted_by_score(self):
        mgr = create_context_manager(
            budget=Budget(maxTokens=20),
            preserve_recent_turns=10,
            token_estimator=_word_estimator,
        )
        mgr.add_turn("user", "hi")  # 1 token
        mgr.add_items(
            [
                ContextItem(id="low", content="low score item", tokens=8, score=1),
                ContextItem(id="high", content="high score item", tokens=8, score=10),
                ContextItem(id="mid", content="mid score item", tokens=8, score=5),
            ]
        )
        result = mgr.compile()
        # Budget 20, turn=1, so 19 for items. high(8)+mid(8)=16, low would push to 24
        assert [i.id for i in result.items] == ["high", "mid"]

    def test_no_compact_below_threshold(self):
        mgr = create_context_manager(
            budget=Budget(maxTokens=500),
            summarize_after_turns=10,
            preserve_recent_turns=2,
            token_estimator=_word_estimator,
        )
        mgr.add_turn("user", "first")
        mgr.add_turn("assistant", "second")
        mgr.add_turn("user", "third")
        mgr.add_turn("assistant", "fourth")
        result = mgr.compile()
        assert len(result.turns) == 4
        assert all(not t.is_summary for t in result.turns)
