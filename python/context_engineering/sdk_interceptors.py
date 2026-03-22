"""SDK Interceptors — wrap OpenAI and Anthropic clients with automatic context management.

Usage::

    from context_engineering.sdk_interceptors import with_context, with_context_anthropic

    # OpenAI
    from openai import OpenAI
    client = with_context(OpenAI(), budget=128_000, strategy="trim")
    # client.chat.completions.create() now auto-manages context

    # Anthropic
    from anthropic import Anthropic
    client = with_context_anthropic(Anthropic(), budget=200_000)
    # client.messages.create() now auto-manages context
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from .core import Budget, ContextItem, ContextPack, ScoringWeights, estimate_tokens, pack

logger = logging.getLogger("context-engineering")

T = TypeVar("T")


@dataclass
class ContextEvent:
    """Event emitted after context packing is applied to a request."""

    timestamp: float
    model: str
    total_messages: int
    kept_messages: int
    trimmed_messages: int
    summarized: bool
    tokens_used: int
    token_budget: int
    utilization: float  # 0-100
    pack_time_ms: float


@dataclass
class InterceptorOptions:
    """Configuration for SDK interceptors."""

    budget: int | None = None
    reserve_tokens: int = 4096
    strategy: str | Callable[..., Any] = "trim"  # "trim" | "summarize" | custom callable
    log: bool = True
    system_priority: int = 100
    recent_message_count: int = 2
    weights: ScoringWeights | None = None
    on_pack: Callable[[ContextEvent], None] | None = None
    on_trim: Callable[[ContextEvent], None] | None = None
    on_error: Callable[[Exception], None] | None = None
    recorder: Any = None  # ContextRecorder from replay module


def _messages_to_context_items(
    messages: list[dict[str, Any]],
    system_priority: int,
    recent_message_count: int,
) -> list[ContextItem]:
    """Convert SDK message dicts to ContextItems with appropriate priorities."""
    items: list[ContextItem] = []
    total = len(messages)

    for idx, msg in enumerate(messages):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            # Handle multi-part content (e.g. vision messages)
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif isinstance(part, str):
                    text_parts.append(part)
            content = "\n".join(text_parts)

        # Priority assignment:
        # - system messages get highest priority
        # - recent messages are protected
        # - older messages get decaying priority
        if role == "system":
            priority = float(system_priority)
            recency = 1.0
        elif idx >= total - recent_message_count:
            # Recent messages — protected with high priority
            priority = float(system_priority - 1)
            recency = 1.0
        else:
            # Older messages — decaying priority based on position
            position_ratio = idx / max(total - 1, 1)
            priority = position_ratio * 10.0
            recency = position_ratio

        items.append(
            ContextItem(
                id=f"msg-{idx}",
                content=content,
                priority=priority,
                recency=recency,
                metadata={"role": role, "index": idx},
            )
        )

    return items


def _context_items_to_messages(
    items: list[ContextItem],
) -> list[dict[str, Any]]:
    """Convert packed ContextItems back to SDK message dicts, preserving original order."""
    sorted_items = sorted(items, key=lambda item: item.metadata.get("index", 0))
    return [
        {"role": item.metadata.get("role", "user"), "content": item.content}
        for item in sorted_items
    ]


def _build_event(
    model: str,
    total_messages: int,
    pack_result: ContextPack,
    token_budget: int,
    pack_time_ms: float,
    summarized: bool = False,
) -> ContextEvent:
    """Build a ContextEvent from pack results."""
    kept = len(pack_result.selected)
    trimmed = len(pack_result.dropped)
    tokens_used = pack_result.total_tokens
    utilization = (tokens_used / token_budget * 100) if token_budget > 0 else 0.0

    return ContextEvent(
        timestamp=time.time(),
        model=model,
        total_messages=total_messages,
        kept_messages=kept,
        trimmed_messages=trimmed,
        summarized=summarized,
        tokens_used=tokens_used,
        token_budget=token_budget,
        utilization=round(utilization, 1),
        pack_time_ms=round(pack_time_ms, 2),
    )


def _log_event(event: ContextEvent) -> None:
    """Log a one-liner summary of the context packing event."""
    logger.info(
        "[context-engineering] %d/%d messages kept, %s/%s tokens used (%.1f%%), %d items trimmed",
        event.kept_messages,
        event.total_messages,
        f"{event.tokens_used:,}",
        f"{event.token_budget:,}",
        event.utilization,
        event.trimmed_messages,
    )


def _apply_summarize_strategy(
    strategy: Callable[..., Any],
    messages: list[dict[str, Any]],
    dropped_items: list[ContextItem],
) -> list[dict[str, Any]]:
    """Apply a custom summarize strategy to dropped messages."""
    dropped_messages = _context_items_to_messages(dropped_items)
    summary = strategy(dropped_messages)
    if summary and isinstance(summary, str):
        return [{"role": "system", "content": summary}]
    if summary and isinstance(summary, list):
        return summary
    return []


def _intercept_openai_create(
    original_create: Callable[..., Any],
    options: InterceptorOptions,
) -> Callable[..., Any]:
    """Create an intercepted version of chat.completions.create."""

    def intercepted_create(*args: Any, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or (args[0] if args else None)
        if messages is None or not isinstance(messages, list):
            return original_create(*args, **kwargs)

        model = kwargs.get("model", "unknown")
        token_budget = options.budget
        if token_budget is None:
            return original_create(*args, **kwargs)

        try:
            # Convert messages to context items
            context_items = _messages_to_context_items(
                messages,
                system_priority=options.system_priority,
                recent_message_count=options.recent_message_count,
            )

            # Check if we're under budget — pass through if so
            total_tokens = sum(
                item.tokens if item.tokens is not None else estimate_tokens(item.content)
                for item in context_items
            )
            effective_budget = token_budget - options.reserve_tokens

            if total_tokens <= effective_budget:
                return original_create(*args, **kwargs)

            # Pack with budget
            start = time.monotonic()
            budget = Budget(maxTokens=effective_budget)
            pack_result = pack(context_items, budget, weights=options.weights)
            pack_time_ms = (time.monotonic() - start) * 1000

            summarized = False
            packed_messages = _context_items_to_messages(pack_result.selected)

            # Apply strategy
            if options.strategy == "trim":
                pass  # Already trimmed by pack
            elif callable(options.strategy):
                summary_messages = _apply_summarize_strategy(
                    options.strategy, messages, pack_result.dropped
                )
                if summary_messages:
                    packed_messages = summary_messages + packed_messages
                    summarized = True

            # Build and emit event
            event = _build_event(
                model=model,
                total_messages=len(messages),
                pack_result=pack_result,
                token_budget=effective_budget,
                pack_time_ms=pack_time_ms,
                summarized=summarized,
            )

            if options.log:
                _log_event(event)
            if options.on_pack:
                options.on_pack(event)
            if pack_result.dropped and options.on_trim:
                options.on_trim(event)

            # Record if recorder is present
            if options.recorder is not None:
                try:
                    options.recorder.record(
                        model=model,
                        items=context_items,
                        budget=budget,
                        result=pack_result,
                    )
                except Exception:
                    pass  # Recording failures should not break the request

            # Call original with packed messages
            kwargs["messages"] = packed_messages
            return original_create(**kwargs)

        except Exception as exc:
            if options.on_error:
                options.on_error(exc)
            # Fall through gracefully — use original messages
            return original_create(*args, **kwargs)

    return intercepted_create


def _intercept_anthropic_create(
    original_create: Callable[..., Any],
    options: InterceptorOptions,
) -> Callable[..., Any]:
    """Create an intercepted version of messages.create."""

    def intercepted_create(*args: Any, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or (args[0] if args else None)
        if messages is None or not isinstance(messages, list):
            return original_create(*args, **kwargs)

        model = kwargs.get("model", "unknown")
        token_budget = options.budget
        if token_budget is None:
            return original_create(*args, **kwargs)

        try:
            # Include system message if present
            all_messages = list(messages)
            system = kwargs.get("system")
            if system:
                all_messages = [{"role": "system", "content": system}] + all_messages

            # Convert messages to context items
            context_items = _messages_to_context_items(
                all_messages,
                system_priority=options.system_priority,
                recent_message_count=options.recent_message_count,
            )

            # Check if we're under budget
            total_tokens = sum(
                item.tokens if item.tokens is not None else estimate_tokens(item.content)
                for item in context_items
            )
            effective_budget = token_budget - options.reserve_tokens

            if total_tokens <= effective_budget:
                return original_create(*args, **kwargs)

            # Pack with budget
            start = time.monotonic()
            budget = Budget(maxTokens=effective_budget)
            pack_result = pack(context_items, budget, weights=options.weights)
            pack_time_ms = (time.monotonic() - start) * 1000

            summarized = False
            packed_items = list(pack_result.selected)

            # Apply strategy
            if options.strategy == "trim":
                pass
            elif callable(options.strategy):
                summary_messages = _apply_summarize_strategy(
                    options.strategy, all_messages, pack_result.dropped
                )
                if summary_messages:
                    # Add summary as high-priority items
                    for i, sm in enumerate(summary_messages):
                        packed_items.insert(
                            0,
                            ContextItem(
                                id=f"summary-{i}",
                                content=sm.get("content", ""),
                                priority=float(options.system_priority),
                                metadata={"role": sm.get("role", "system"), "index": -1},
                            ),
                        )
                    summarized = True

            # Separate system and non-system messages
            packed_messages = _context_items_to_messages(packed_items)
            new_system = None
            new_messages = []
            for msg in packed_messages:
                if msg["role"] == "system":
                    new_system = (
                        msg["content"]
                        if new_system is None
                        else new_system + "\n\n" + msg["content"]
                    )
                else:
                    new_messages.append(msg)

            # Build and emit event
            event = _build_event(
                model=model,
                total_messages=len(all_messages),
                pack_result=pack_result,
                token_budget=effective_budget,
                pack_time_ms=pack_time_ms,
                summarized=summarized,
            )

            if options.log:
                _log_event(event)
            if options.on_pack:
                options.on_pack(event)
            if pack_result.dropped and options.on_trim:
                options.on_trim(event)

            # Record if recorder is present
            if options.recorder is not None:
                try:
                    options.recorder.record(
                        model=model,
                        items=context_items,
                        budget=budget,
                        result=pack_result,
                    )
                except Exception:
                    pass

            # Call original with packed messages
            kwargs["messages"] = new_messages
            if new_system is not None:
                kwargs["system"] = new_system
            return original_create(**kwargs)

        except Exception as exc:
            if options.on_error:
                options.on_error(exc)
            return original_create(*args, **kwargs)

    return intercepted_create


class _OpenAICompletionsProxy:
    """Proxy for client.chat.completions that intercepts create()."""

    def __init__(self, original_completions: Any, options: InterceptorOptions) -> None:
        self._original = original_completions
        self._options = options
        self.create = _intercept_openai_create(original_completions.create, options)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


class _OpenAIChatProxy:
    """Proxy for client.chat that intercepts completions.create()."""

    def __init__(self, original_chat: Any, options: InterceptorOptions) -> None:
        self._original = original_chat
        self.completions = _OpenAICompletionsProxy(original_chat.completions, options)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


class _AnthropicMessagesProxy:
    """Proxy for client.messages that intercepts create()."""

    def __init__(self, original_messages: Any, options: InterceptorOptions) -> None:
        self._original = original_messages
        self._options = options
        self.create = _intercept_anthropic_create(original_messages.create, options)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


def with_context(client: T, **kwargs: Any) -> T:
    """Wrap an OpenAI client with automatic context management.

    The returned client proxies ``client.chat.completions.create()`` to
    automatically pack messages within the configured token budget.

    Args:
        client: An OpenAI client instance (or any duck-typed equivalent).
        **kwargs: Options matching :class:`InterceptorOptions` fields.

    Returns:
        The same client with ``chat.completions.create`` intercepted.

    Example::

        from openai import OpenAI
        client = with_context(OpenAI(), budget=128_000, strategy="trim")
    """
    options = InterceptorOptions(**kwargs)
    client.chat = _OpenAIChatProxy(client.chat, options)  # type: ignore[attr-defined]
    return client


def with_context_anthropic(client: T, **kwargs: Any) -> T:
    """Wrap an Anthropic client with automatic context management.

    The returned client proxies ``client.messages.create()`` to
    automatically pack messages within the configured token budget.

    Args:
        client: An Anthropic client instance (or any duck-typed equivalent).
        **kwargs: Options matching :class:`InterceptorOptions` fields.

    Returns:
        The same client with ``messages.create`` intercepted.

    Example::

        from anthropic import Anthropic
        client = with_context_anthropic(Anthropic(), budget=200_000)
    """
    options = InterceptorOptions(**kwargs)
    client.messages = _AnthropicMessagesProxy(client.messages, options)  # type: ignore[attr-defined]
    return client
