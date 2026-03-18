"""Tests for the compaction module: multi-turn context management."""

import pytest

from context_engineering.compaction import create_context_manager
from context_engineering.core import Budget, ContextItem
from context_engineering.errors import ValidationError
from context_engineering.providers import LLMResult, create_llm_summarizer


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


class TestCreateContextManagerValidation:
    def test_rejects_zero_max_tokens(self):
        with pytest.raises(ValidationError) as exc_info:
            create_context_manager(budget=Budget(maxTokens=0))
        assert exc_info.value.code == "VALIDATION_ERROR"
        assert any("max_tokens" in d.path for d in exc_info.value.details)

    def test_rejects_negative_max_tokens(self):
        with pytest.raises(ValidationError) as exc_info:
            create_context_manager(budget=Budget(maxTokens=-100))
        assert exc_info.value.code == "VALIDATION_ERROR"
        assert any("max_tokens" in d.path for d in exc_info.value.details)

    def test_accepts_positive_max_tokens(self):
        # Should not raise
        mgr = create_context_manager(budget=Budget(maxTokens=1000))
        assert mgr is not None

    def test_accepts_small_positive_max_tokens(self):
        mgr = create_context_manager(budget=Budget(maxTokens=1))
        assert mgr is not None


class TestCompileAsync:
    @pytest.mark.asyncio
    async def test_calls_summarizer_for_older_turns(self):
        calls = []

        async def mock_summarizer(item, target_tokens):
            calls.append(item.content)
            return item.model_copy(update={"content": "summary", "tokens": 5})

        mgr = create_context_manager(
            budget=Budget(maxTokens=200),
            summarize_after_turns=2,
            preserve_recent_turns=1,
            async_summarizer=mock_summarizer,
            token_estimator=_word_estimator,
        )
        for i in range(5):
            mgr.add_turn("user", f"turn content {i} with enough words")

        result = await mgr.compile_async()
        assert len(calls) > 0
        assert result.total_tokens < 200

    @pytest.mark.asyncio
    async def test_falls_back_to_truncation_on_none(self):
        async def null_summarizer(item, target_tokens):
            return None

        mgr = create_context_manager(
            budget=Budget(maxTokens=200),
            summarize_after_turns=2,
            preserve_recent_turns=1,
            async_summarizer=null_summarizer,
            token_estimator=_word_estimator,
        )
        for i in range(5):
            mgr.add_turn("user", f"turn {i}")

        result = await mgr.compile_async()
        assert len(result.turns) > 0

    @pytest.mark.asyncio
    async def test_batches_older_turns(self):
        call_count = 0

        async def mock_summarizer(item, target_tokens):
            nonlocal call_count
            call_count += 1
            return item.model_copy(update={"content": f"summary {call_count}", "tokens": 5})

        mgr = create_context_manager(
            budget=Budget(maxTokens=500),
            summarize_after_turns=2,
            preserve_recent_turns=1,
            async_summarizer=mock_summarizer,
            batch_size=5,
            token_estimator=_word_estimator,
        )
        for i in range(11):
            mgr.add_turn("user", f"turn {i} content here")

        await mgr.compile_async()
        assert call_count == 2  # 10 older turns / batch_size 5 = 2 batches

    @pytest.mark.asyncio
    async def test_falls_back_on_summarizer_error(self):
        async def error_summarizer(item, target_tokens):
            raise RuntimeError("API error")

        mgr = create_context_manager(
            budget=Budget(maxTokens=200),
            summarize_after_turns=2,
            preserve_recent_turns=1,
            async_summarizer=error_summarizer,
            token_estimator=_word_estimator,
        )
        for i in range(5):
            mgr.add_turn("user", f"turn {i}")

        result = await mgr.compile_async()
        assert len(result.turns) > 0

    @pytest.mark.asyncio
    async def test_sync_compile_ignores_async_summarizer(self):
        async def boom(item, target_tokens):
            raise RuntimeError("should not be called")

        mgr = create_context_manager(
            budget=Budget(maxTokens=200),
            summarize_after_turns=2,
            preserve_recent_turns=1,
            async_summarizer=boom,
            token_estimator=_word_estimator,
        )
        for i in range(5):
            mgr.add_turn("user", f"turn {i}")

        # sync compile should not call async summarizer
        result = mgr.compile()
        assert len(result.turns) > 0


class TestCreateLLMSummarizer:
    def test_returns_summarized_content(self):
        class MockProvider:
            def generate(self, messages, model="", max_tokens=256, temperature=0.2):
                return LLMResult(
                    text="Concise summary of the conversation.",
                    model="test",
                    input_tokens=100,
                    output_tokens=20,
                )

        summarizer = create_llm_summarizer(provider=MockProvider())
        item = ContextItem(id="batch1", content="Long conversation content...", tokens=500)
        result = summarizer(item, 50)
        assert result is not None
        assert result.content == "Concise summary of the conversation."

    def test_returns_none_on_error(self):
        class ErrorProvider:
            def generate(self, messages, model="", max_tokens=256, temperature=0.2):
                raise RuntimeError("API error")

        summarizer = create_llm_summarizer(provider=ErrorProvider())
        result = summarizer(ContextItem(id="x", content="text"), 50)
        assert result is None
