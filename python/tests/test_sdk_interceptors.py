"""Tests for SDK interceptors — OpenAI and Anthropic client wrapping."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from context_engineering.sdk_interceptors import (
    ContextEvent,
    InterceptorOptions,
    with_context,
    with_context_anthropic,
)


def _make_openai_client(response: str = "hello") -> SimpleNamespace:
    """Create a mock OpenAI-like client with chat.completions.create."""
    create_fn = MagicMock(return_value={"choices": [{"message": {"content": response}}]})
    completions = SimpleNamespace(create=create_fn)
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(chat=chat)


def _make_anthropic_client(response: str = "hello") -> SimpleNamespace:
    """Create a mock Anthropic-like client with messages.create."""
    create_fn = MagicMock(return_value={"content": [{"text": response}]})
    messages = SimpleNamespace(create=create_fn)
    return SimpleNamespace(messages=messages)


def _make_messages(count: int, token_size: int = 100) -> list[dict]:
    """Create a list of messages with enough content to exceed budgets."""
    messages = [{"role": "system", "content": "You are a helpful assistant."}]
    for i in range(count - 1):
        role = "user" if i % 2 == 0 else "assistant"
        # Each word ~1.3 tokens, so token_size/1.3 words
        word_count = max(1, token_size)
        content = " ".join(f"word{j}" for j in range(word_count))
        messages.append({"role": role, "content": content})
    return messages


class TestOpenAIInterceptor:
    def test_messages_packed_when_over_budget(self):
        client = _make_openai_client()
        client = with_context(client, budget=200, reserve_tokens=50, log=False)

        messages = _make_messages(10, token_size=50)
        client.chat.completions.create(messages=messages, model="gpt-4o")

        # The original create function should have been called with packed messages
        call_args = client.chat._original.completions.create.call_args
        packed_messages = call_args.kwargs.get(
            "messages", call_args.args[0] if call_args.args else []
        )
        assert len(packed_messages) <= len(messages)

    def test_under_budget_messages_pass_through(self):
        client = _make_openai_client()
        original_create = client.chat.completions.create
        client = with_context(client, budget=999_999, reserve_tokens=100, log=False)

        messages = [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hi"},
        ]
        client.chat.completions.create(messages=messages, model="gpt-4o")

        # Under budget: original create should be called with original messages
        original_create.assert_called_once()
        call_kwargs = original_create.call_args
        passed_messages = call_kwargs.kwargs.get("messages") or call_kwargs.args[0]
        assert len(passed_messages) == 2

    def test_trim_strategy_drops_low_priority_messages(self):
        client = _make_openai_client()
        client = with_context(client, budget=300, reserve_tokens=50, strategy="trim", log=False)

        messages = _make_messages(20, token_size=30)
        client.chat.completions.create(messages=messages, model="gpt-4o")

        call_args = client.chat._original.completions.create.call_args
        packed_messages = call_args.kwargs.get("messages")
        assert packed_messages is not None
        assert len(packed_messages) < len(messages)

    def test_custom_summarize_strategy(self):
        client = _make_openai_client()

        def summarizer(dropped_messages: list[dict]) -> str:
            return f"Summary of {len(dropped_messages)} messages"

        client = with_context(client, budget=300, reserve_tokens=50, strategy=summarizer, log=False)

        messages = _make_messages(20, token_size=30)
        client.chat.completions.create(messages=messages, model="gpt-4o")

        call_args = client.chat._original.completions.create.call_args
        packed_messages = call_args.kwargs.get("messages")
        assert packed_messages is not None
        # Should have a summary message injected
        contents = [m["content"] for m in packed_messages]
        assert any("Summary of" in c for c in contents)

    def test_event_callbacks_fire(self):
        client = _make_openai_client()
        events: list[ContextEvent] = []

        client = with_context(
            client,
            budget=300,
            reserve_tokens=50,
            log=False,
            on_pack=lambda e: events.append(e),
        )

        messages = _make_messages(20, token_size=30)
        client.chat.completions.create(messages=messages, model="gpt-4o")

        assert len(events) == 1
        assert events[0].model == "gpt-4o"
        assert events[0].total_messages == 20
        assert events[0].kept_messages > 0
        assert 0 <= events[0].utilization <= 100

    def test_on_trim_callback_fires_when_items_trimmed(self):
        client = _make_openai_client()
        trim_events: list[ContextEvent] = []

        client = with_context(
            client,
            budget=300,
            reserve_tokens=50,
            log=False,
            on_trim=lambda e: trim_events.append(e),
        )

        messages = _make_messages(20, token_size=30)
        client.chat.completions.create(messages=messages, model="gpt-4o")

        assert len(trim_events) == 1
        assert trim_events[0].trimmed_messages > 0

    def test_console_logging(self, caplog):
        client = _make_openai_client()
        client = with_context(client, budget=300, reserve_tokens=50, log=True)

        with caplog.at_level(logging.INFO, logger="context-engineering"):
            messages = _make_messages(20, token_size=30)
            client.chat.completions.create(messages=messages, model="gpt-4o")

        assert any("[context-engineering]" in record.message for record in caplog.records)
        assert any("messages kept" in record.message for record in caplog.records)
        assert any("tokens used" in record.message for record in caplog.records)

    def test_error_fallthrough(self):
        client = _make_openai_client()
        errors: list[Exception] = []

        # Create a client with a broken packer by passing invalid weights
        # that will cause an error during packing
        client = with_context(
            client,
            budget=300,
            reserve_tokens=50,
            log=False,
            on_error=lambda e: errors.append(e),
        )

        # Patch pack to raise an error
        import context_engineering.sdk_interceptors as mod

        original_pack = mod.pack

        def broken_pack(*args, **kwargs):
            raise RuntimeError("pack is broken")

        mod.pack = broken_pack
        try:
            messages = _make_messages(20, token_size=30)
            # Should not raise — falls through to original
            client.chat.completions.create(messages=messages, model="gpt-4o")
            assert len(errors) == 1
            assert "pack is broken" in str(errors[0])
        finally:
            mod.pack = original_pack

    def test_system_messages_get_high_priority(self):
        client = _make_openai_client()
        events: list[ContextEvent] = []

        client = with_context(
            client,
            budget=200,
            reserve_tokens=50,
            log=False,
            on_pack=lambda e: events.append(e),
        )

        messages = [
            {"role": "system", "content": "You are an expert."},
        ] + [
            {"role": "user", "content": " ".join(f"word{j}" for j in range(40))} for _ in range(10)
        ]
        client.chat.completions.create(messages=messages, model="gpt-4o")

        # System message should always be kept (highest priority)
        call_args = client.chat._original.completions.create.call_args
        packed_messages = call_args.kwargs.get("messages")
        if packed_messages:
            roles = [m["role"] for m in packed_messages]
            assert "system" in roles

    def test_recent_messages_protected(self):
        client = _make_openai_client()
        client = with_context(
            client, budget=400, reserve_tokens=50, recent_message_count=2, log=False
        )

        messages = _make_messages(10, token_size=30)
        last_two_contents = [messages[-1]["content"], messages[-2]["content"]]

        client.chat.completions.create(messages=messages, model="gpt-4o")

        call_args = client.chat._original.completions.create.call_args
        packed_messages = call_args.kwargs.get("messages")
        if packed_messages:
            packed_contents = [m["content"] for m in packed_messages]
            # At least some of the recent messages should be preserved
            assert any(c in packed_contents for c in last_two_contents)

    def test_no_budget_passes_through(self):
        client = _make_openai_client()
        original_create = client.chat.completions.create
        client = with_context(client, budget=None, log=False)

        messages = _make_messages(5)
        client.chat.completions.create(messages=messages, model="gpt-4o")

        original_create.assert_called_once()

    def test_non_list_messages_pass_through(self):
        client = _make_openai_client()
        original_create = client.chat.completions.create
        client = with_context(client, budget=1000, log=False)

        # Passing no messages kwarg
        client.chat.completions.create(model="gpt-4o")

        original_create.assert_called_once()


class TestAnthropicInterceptor:
    def test_messages_packed_when_over_budget(self):
        client = _make_anthropic_client()
        client = with_context_anthropic(client, budget=200, reserve_tokens=50, log=False)

        messages = _make_messages(10, token_size=50)
        # Anthropic doesn't use system in messages; separate it
        system_msg = messages[0]["content"]
        non_system = [m for m in messages[1:] if m["role"] != "system"]
        client.messages.create(messages=non_system, system=system_msg, model="claude-3-5-sonnet")

        call_args = client.messages._original.create.call_args
        packed_messages = call_args.kwargs.get("messages")
        assert packed_messages is not None

    def test_under_budget_passes_through(self):
        client = _make_anthropic_client()
        original_create = client.messages.create
        client = with_context_anthropic(client, budget=999_999, reserve_tokens=100, log=False)

        messages = [{"role": "user", "content": "Hi"}]
        client.messages.create(messages=messages, model="claude-3-5-sonnet")

        original_create.assert_called_once()

    def test_event_callbacks_fire(self):
        client = _make_anthropic_client()
        events: list[ContextEvent] = []

        client = with_context_anthropic(
            client,
            budget=300,
            reserve_tokens=50,
            log=False,
            on_pack=lambda e: events.append(e),
        )

        messages = [
            {"role": "user", "content": " ".join(f"word{j}" for j in range(60))} for _ in range(10)
        ]
        client.messages.create(messages=messages, model="claude-3-5-sonnet")

        assert len(events) == 1
        assert events[0].model == "claude-3-5-sonnet"

    def test_system_message_preserved(self):
        client = _make_anthropic_client()
        client = with_context_anthropic(client, budget=200, reserve_tokens=50, log=False)

        messages = [
            {"role": "user", "content": " ".join(f"word{j}" for j in range(60))} for _ in range(10)
        ]
        client.messages.create(messages=messages, system="Be helpful.", model="claude-3-5-sonnet")

        call_args = client.messages._original.create.call_args
        # System should be preserved
        system = call_args.kwargs.get("system")
        assert system is not None
        assert "helpful" in system

    def test_error_fallthrough(self):
        client = _make_anthropic_client()
        errors: list[Exception] = []

        client = with_context_anthropic(
            client,
            budget=300,
            reserve_tokens=50,
            log=False,
            on_error=lambda e: errors.append(e),
        )

        import context_engineering.sdk_interceptors as mod

        original_pack = mod.pack

        def broken_pack(*args, **kwargs):
            raise RuntimeError("pack is broken")

        mod.pack = broken_pack
        try:
            messages = [
                {"role": "user", "content": " ".join(f"word{j}" for j in range(60))}
                for _ in range(10)
            ]
            client.messages.create(messages=messages, model="claude-3-5-sonnet")
            assert len(errors) == 1
        finally:
            mod.pack = original_pack

    def test_no_budget_passes_through(self):
        client = _make_anthropic_client()
        original_create = client.messages.create
        client = with_context_anthropic(client, budget=None, log=False)

        messages = [{"role": "user", "content": "Hi"}]
        client.messages.create(messages=messages, model="claude-3-5-sonnet")

        original_create.assert_called_once()


class TestInterceptorOptions:
    def test_default_values(self):
        opts = InterceptorOptions()
        assert opts.budget is None
        assert opts.reserve_tokens == 4096
        assert opts.strategy == "trim"
        assert opts.log is True
        assert opts.system_priority == 100
        assert opts.recent_message_count == 2

    def test_custom_values(self):
        opts = InterceptorOptions(
            budget=128_000,
            reserve_tokens=8192,
            strategy="trim",
            log=False,
            system_priority=50,
            recent_message_count=5,
        )
        assert opts.budget == 128_000
        assert opts.reserve_tokens == 8192
        assert opts.recent_message_count == 5


class TestContextEvent:
    def test_event_fields(self):
        event = ContextEvent(
            timestamp=1000.0,
            model="gpt-4o",
            total_messages=20,
            kept_messages=12,
            trimmed_messages=8,
            summarized=False,
            tokens_used=2847,
            token_budget=4096,
            utilization=69.4,
            pack_time_ms=3.5,
        )
        assert event.total_messages == 20
        assert event.kept_messages == 12
        assert event.utilization == 69.4
