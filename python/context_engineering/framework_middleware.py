"""Framework Middleware — drop-in context management for LLM frameworks.

Provides ``with_context_langchain``, ``with_context_llamaindex``,
``with_context_crewai``, and ``with_context_generic`` adapters that
monkey-patch framework LLM objects to automatically pack messages within
a token budget before each call.

All adapters use duck typing — no framework imports required at runtime.
On error the original call is made unmodified (graceful fallthrough).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from .core import (
    Budget,
    ContextItem,
    ContextPack,
    ScoringWeights,
    estimate_tokens,
    pack,
)

logger = logging.getLogger(__name__)

TAG = "[context-engineering]"


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class ContextEvent:
    """Event emitted after each framework interception."""

    timestamp: float
    framework: str
    model: str
    total_messages: int
    kept_messages: int
    trimmed_messages: int
    tokens_used: int
    token_budget: int
    utilization: float
    pack_time_ms: int


@dataclass
class FrameworkMiddlewareOptions:
    """Options for framework middleware adapters."""

    budget: int | None = None
    reserve_tokens: int = 4096
    strategy: str | Callable[..., Any] = "trim"
    log: bool = True
    system_priority: int = 100
    recent_message_count: int = 2
    weights: ScoringWeights | None = None
    on_pack: Callable[[ContextEvent], None] | None = None
    on_error: Callable[[Exception], None] | None = None


_DEFAULT_BUDGET = 128_000


def _resolve_budget(options: FrameworkMiddlewareOptions) -> int:
    return options.budget or _DEFAULT_BUDGET


# ---------------------------------------------------------------------------
# Shared packing logic
# ---------------------------------------------------------------------------


def _extract_text(content: Any) -> str:
    """Extract plain text from message content (string, list, or object)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts) if parts else str(content)
    if content is not None:
        return str(content)
    return ""


def _messages_to_context_items(
    messages: list[dict[str, Any]],
    options: FrameworkMiddlewareOptions,
) -> list[ContextItem]:
    """Convert generic message dicts to ContextItem list for scoring."""
    total = len(messages)
    protected_tail = options.recent_message_count
    items: list[ContextItem] = []

    for i, msg in enumerate(messages):
        text = _extract_text(msg.get("content", ""))
        tokens = estimate_tokens(text)
        role = msg.get("role", "user")
        is_system = role == "system"
        is_protected = i >= total - protected_tail

        if is_system:
            priority = float(options.system_priority)
        elif is_protected:
            priority = 90.0
        else:
            old_count = max(1, total - protected_tail)
            position = i
            priority = max(10.0, round(50.0 - (position / old_count) * 40.0))

        recency = i / (total - 1) if total > 1 else 1.0

        items.append(
            ContextItem(
                id=f"msg-{i}",
                content=text,
                kind=role,
                priority=priority,
                recency=recency,
                tokens=tokens,
                metadata={
                    "original_index": i,
                    "original_message": msg,
                    "role": role,
                    "is_system": is_system,
                    "is_protected": is_protected,
                },
            )
        )
    return items


def _context_items_to_messages(
    original_messages: list[dict[str, Any]],
    kept_items: list[ContextItem],
) -> list[dict[str, Any]]:
    """Reconstruct message dicts from packed items, preserving order."""
    sorted_items = sorted(
        kept_items,
        key=lambda item: item.metadata.get("original_index", 0),
    )
    result: list[dict[str, Any]] = []
    for item in sorted_items:
        idx = item.metadata.get("original_index")
        original = item.metadata.get("original_message")
        if original is not None:
            result.append(original)
        elif idx is not None and 0 <= idx < len(original_messages):
            result.append(original_messages[idx])
        else:
            result.append({"role": item.kind or "user", "content": item.content})
    return result


def _pack_messages(
    messages: list[dict[str, Any]],
    model_name: str,
    framework: str,
    options: FrameworkMiddlewareOptions,
) -> tuple[list[dict[str, Any]], ContextEvent]:
    """Core packing: convert messages -> items -> pack -> messages."""
    start = time.monotonic()
    budget = _resolve_budget(options)
    effective_budget = budget - options.reserve_tokens

    items = _messages_to_context_items(messages, options)
    total_tokens = sum(item.tokens or 0 for item in items)

    # If everything fits, pass through unchanged
    if total_tokens <= effective_budget:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        event = ContextEvent(
            timestamp=time.time(),
            framework=framework,
            model=model_name,
            total_messages=len(messages),
            kept_messages=len(messages),
            trimmed_messages=0,
            tokens_used=total_tokens,
            token_budget=budget,
            utilization=(total_tokens / budget * 100) if budget > 0 else 0,
            pack_time_ms=elapsed_ms,
        )
        _emit_event(event, options)
        return messages, event

    pack_result: ContextPack = pack(
        items,
        Budget(maxTokens=effective_budget, reserveTokens=0),
        weights=options.weights,
    )

    packed = _context_items_to_messages(messages, pack_result.selected)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    trimmed_count = len(messages) - len(pack_result.selected)
    event = ContextEvent(
        timestamp=time.time(),
        framework=framework,
        model=model_name,
        total_messages=len(messages),
        kept_messages=len(pack_result.selected),
        trimmed_messages=trimmed_count,
        tokens_used=pack_result.total_tokens,
        token_budget=budget,
        utilization=(pack_result.total_tokens / budget * 100) if budget > 0 else 0,
        pack_time_ms=elapsed_ms,
    )
    _emit_event(event, options)
    return packed, event


def _emit_event(event: ContextEvent, options: FrameworkMiddlewareOptions) -> None:
    """Log and fire callbacks."""
    if options.log:
        detail = (
            f"{event.kept_messages}/{event.total_messages} messages kept, "
            f"{event.tokens_used:,}/{event.token_budget:,} tokens "
            f"({event.utilization:.1f}%)"
        )
        if event.trimmed_messages > 0:
            detail += f", {event.trimmed_messages} trimmed"
        logger.info("%s [%s] %s", TAG, event.framework, detail)

    if options.on_pack is not None:
        options.on_pack(event)


# ---------------------------------------------------------------------------
# LangChain adapter
# ---------------------------------------------------------------------------


def _extract_role_langchain(msg: Any) -> str:
    """Extract role from a LangChain BaseMessage (duck-typed)."""
    if hasattr(msg, "_getType") and callable(msg._getType):
        t = msg._getType()
        if t == "human":
            return "user"
        if t == "ai":
            return "assistant"
        return t
    if hasattr(msg, "type"):
        t = msg.type
        if t == "human":
            return "user"
        if t == "ai":
            return "assistant"
        return t
    if hasattr(msg, "role"):
        return msg.role
    return "user"


def _langchain_to_generic(messages: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for msg in messages:
        role = _extract_role_langchain(msg)
        content = _extract_text(getattr(msg, "content", ""))
        result.append({"role": role, "content": content, "_original": msg})
    return result


def _generic_to_langchain(packed: list[dict[str, Any]]) -> list[Any]:
    return [
        msg.get("_original", {"role": msg["role"], "content": msg["content"]}) for msg in packed
    ]


def with_context_langchain(
    model: Any,
    options: FrameworkMiddlewareOptions | None = None,
    **kwargs: Any,
) -> Any:
    """Wrap a LangChain ChatModel with context management.

    Intercepts ``invoke()`` to pack messages within the token budget.
    Uses duck typing — no ``langchain`` import required.

    Args:
        model: Any object with an ``invoke(messages, ...)`` method.
        options: Middleware options (budget, strategy, etc.).
        **kwargs: Shorthand — forwarded to ``FrameworkMiddlewareOptions``.

    Returns:
        The same model object with ``invoke`` monkey-patched.
    """
    opts = options or FrameworkMiddlewareOptions(**kwargs)
    model_name = (
        getattr(model, "model_name", None) or getattr(model, "modelName", None) or "unknown"
    )

    original_invoke = model.invoke

    def intercepted_invoke(messages: Any, *args: Any, **kw: Any) -> Any:
        if not isinstance(messages, list) or len(messages) == 0:
            return original_invoke(messages, *args, **kw)
        try:
            generic = _langchain_to_generic(messages)
            packed, _ = _pack_messages(generic, model_name, "langchain", opts)
            reconstructed = _generic_to_langchain(packed)
            return original_invoke(reconstructed, *args, **kw)
        except Exception as exc:
            if opts.on_error is not None:
                opts.on_error(exc)
            return original_invoke(messages, *args, **kw)

    model.invoke = intercepted_invoke
    return model


# ---------------------------------------------------------------------------
# LlamaIndex adapter
# ---------------------------------------------------------------------------


def _llamaindex_to_generic(messages: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for msg in messages:
        role = getattr(msg, "role", "user")
        if isinstance(role, str):
            pass
        elif hasattr(role, "value"):
            role = role.value  # enum
        else:
            role = str(role)
        content = _extract_text(getattr(msg, "content", ""))
        result.append({"role": role, "content": content, "_original": msg})
    return result


def _generic_to_llamaindex(packed: list[dict[str, Any]]) -> list[Any]:
    return [
        msg.get(
            "_original", type("ChatMessage", (), {"role": msg["role"], "content": msg["content"]})()
        )
        for msg in packed
    ]


def with_context_llamaindex(
    llm: Any,
    options: FrameworkMiddlewareOptions | None = None,
    **kwargs: Any,
) -> Any:
    """Wrap a LlamaIndex LLM with context management.

    Intercepts ``chat()`` to pack messages within the token budget.

    Args:
        llm: Any object with a ``chat(messages=..., ...)`` method.
        options: Middleware options.
        **kwargs: Shorthand — forwarded to ``FrameworkMiddlewareOptions``.

    Returns:
        The same LLM object with ``chat`` monkey-patched.
    """
    opts = options or FrameworkMiddlewareOptions(**kwargs)
    model_name = (
        getattr(llm, "model", None) or getattr(llm, "metadata", {}).get("model") or "unknown"
    )

    original_chat = llm.chat

    def intercepted_chat(*args: Any, **kw: Any) -> Any:
        # LlamaIndex chat() signature: chat(messages=...) or chat(messages, ...)
        messages = kw.get("messages") or (args[0] if args else None)
        if not isinstance(messages, list) or len(messages) == 0:
            return original_chat(*args, **kw)
        try:
            generic = _llamaindex_to_generic(messages)
            packed, _ = _pack_messages(generic, model_name, "llamaindex", opts)
            reconstructed = _generic_to_llamaindex(packed)
            if "messages" in kw:
                kw["messages"] = reconstructed
                return original_chat(*args, **kw)
            else:
                return original_chat(reconstructed, *args[1:], **kw)
        except Exception as exc:
            if opts.on_error is not None:
                opts.on_error(exc)
            return original_chat(*args, **kw)

    llm.chat = intercepted_chat
    return llm


# ---------------------------------------------------------------------------
# CrewAI adapter
# ---------------------------------------------------------------------------


def with_context_crewai(
    llm: Any,
    options: FrameworkMiddlewareOptions | None = None,
    **kwargs: Any,
) -> Any:
    """Wrap a CrewAI-compatible LLM with context management.

    CrewAI uses LangChain models internally.  Intercepts ``invoke()``
    and/or ``call()`` on the LLM.

    Args:
        llm: Any object with ``invoke(messages, ...)`` or ``call(messages, ...)``.
        options: Middleware options.
        **kwargs: Shorthand — forwarded to ``FrameworkMiddlewareOptions``.

    Returns:
        The same LLM object with relevant methods monkey-patched.
    """
    opts = options or FrameworkMiddlewareOptions(**kwargs)
    model_name = getattr(llm, "model_name", None) or getattr(llm, "model", None) or "unknown"

    def _make_interceptor(original_method: Callable[..., Any]) -> Callable[..., Any]:
        def intercepted(messages: Any, *args: Any, **kw: Any) -> Any:
            if not isinstance(messages, list) or len(messages) == 0:
                return original_method(messages, *args, **kw)
            try:
                generic = _langchain_to_generic(messages)
                packed, _ = _pack_messages(generic, model_name, "crewai", opts)
                reconstructed = _generic_to_langchain(packed)
                return original_method(reconstructed, *args, **kw)
            except Exception as exc:
                if opts.on_error is not None:
                    opts.on_error(exc)
                return original_method(messages, *args, **kw)

        return intercepted

    if hasattr(llm, "invoke") and callable(llm.invoke):
        llm.invoke = _make_interceptor(llm.invoke)

    if hasattr(llm, "call") and callable(llm.call):
        llm.call = _make_interceptor(llm.call)

    return llm


# ---------------------------------------------------------------------------
# Generic adapter
# ---------------------------------------------------------------------------


def with_context_generic(
    target: Any,
    method_name: str,
    message_extractor: Callable[..., list[dict[str, Any]]],
    message_injector: Callable[..., tuple[Any, ...]],
    options: FrameworkMiddlewareOptions | None = None,
    model_extractor: Callable[[Any], str] | None = None,
    framework_name: str = "generic",
    **kwargs: Any,
) -> Any:
    """Wrap any object's method with context management.

    Args:
        target: The object to wrap.
        method_name: Name of the method to intercept.
        message_extractor: ``(args, kwargs) -> messages`` — extracts messages
            from the method's arguments.
        message_injector: ``(args, kwargs, packed_messages) -> (new_args, new_kwargs)``
            — injects packed messages back.
        options: Middleware options.
        model_extractor: ``(target) -> model_name``.
        framework_name: Name for logging/events.
        **kwargs: Shorthand — forwarded to ``FrameworkMiddlewareOptions``.

    Returns:
        The same target with the named method monkey-patched.
    """
    opts = options or FrameworkMiddlewareOptions(**kwargs)
    model_name = model_extractor(target) if model_extractor else "unknown"

    original_method = getattr(target, method_name)

    def intercepted(*args: Any, **kw: Any) -> Any:
        try:
            messages = message_extractor(args, kw)
            if not isinstance(messages, list) or len(messages) == 0:
                return original_method(*args, **kw)
            packed, _ = _pack_messages(messages, model_name, framework_name, opts)
            new_args, new_kwargs = message_injector(args, kw, packed)
            return original_method(*new_args, **new_kwargs)
        except Exception as exc:
            if opts.on_error is not None:
                opts.on_error(exc)
            return original_method(*args, **kw)

    setattr(target, method_name, intercepted)
    return target
