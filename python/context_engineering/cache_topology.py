"""
Cache-Topology-Aware Packing

Structures context output to maximize prefix cache hits across API calls.
Anthropic: 90% cost reduction, 85% latency reduction with prefix caching.
OpenAI: 50% cost reduction, automatic for prompts >1024 tokens.

The key insight: if items are always sorted by score, every request produces
a different prefix, destroying cache reuse. Instead, we partition items into
a stable prefix (deterministically ordered) and a volatile suffix (score-ordered).

Based on: https://ankitbko.github.io/blog/2025/08/prompt-engineering-kv-cache/
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from .core import Budget, ContextItem, estimate_tokens, pack, pack_async
from .errors import ValidationError

Volatility = Literal["static", "session", "request"]

# Kind-to-volatility mapping
_STATIC_KINDS = {"system", "tool", "schema", "example", "instruction", "few-shot"}
_SESSION_KINDS = {"memory", "conversation", "history", "session"}
_REQUEST_KINDS = {"query", "retrieval", "tool-result", "request"}


@dataclass
class CacheConfig:
    """Provider-specific cache configuration."""

    provider: Optional[str] = None  # "anthropic", "openai", "auto"
    min_prefix_tokens: Optional[int] = None
    mark_breakpoints: bool = False


@dataclass
class CacheAwarePack:
    """Result of cache-aware packing."""

    budget: Budget
    selected: List[ContextItem]
    dropped: List[ContextItem]
    total_tokens: int
    stats: Dict[str, Any]
    cache_key: str
    cacheable_tokens: int
    volatile_tokens: int
    cache_efficiency: float
    partition_boundaries: List[int]


def classify_volatility(item: ContextItem) -> Volatility:
    """Assign a volatility level to an item based on its kind and metadata.

    Items are classified into three tiers:
    - static: system prompts, tool definitions, few-shot examples (rarely change)
    - session: conversation history, memory retrievals (change per session)
    - request: current query, fresh RAG results (change every request)
    """
    # Explicit volatility in metadata takes precedence
    if item.metadata and "volatility" in item.metadata:
        return item.metadata["volatility"]

    kind = (item.kind or "").lower()

    if kind in _STATIC_KINDS:
        return "static"
    if kind in _SESSION_KINDS:
        return "session"
    if kind in _REQUEST_KINDS:
        return "request"

    return "request"


def _hash_string(s: str) -> str:
    """Simple hash for cache key generation."""
    h = 0
    for ch in s:
        h = ((h << 5) - h + ord(ch)) & 0xFFFFFFFF
    return format(h, "x")


def pack_with_cache_topology(
    items: List[ContextItem],
    budget: Budget,
    options: Optional[Dict[str, Any]] = None,
    cache_config: Optional[CacheConfig] = None,
) -> CacheAwarePack:
    """Pack items with cache-topology awareness.

    Partitions items into stable prefix and volatile suffix to maximize
    prefix cache hits across API calls. The stable prefix uses deterministic
    ordering (by id) so the same items always produce the same prefix.

    Args:
        items: Context items to pack (should have `kind` set for best results)
        budget: Token budget
        options: Standard pack options (weights, etc.)
        cache_config: Cache-specific configuration

    Returns:
        CacheAwarePack with cache metadata

    Example:
        result = pack_with_cache_topology(
            [
                ContextItem(id="sys", content="You are helpful.", kind="system", priority=10),
                ContextItem(id="doc", content="Retrieved doc...", kind="retrieval", priority=7),
                ContextItem(id="q", content="User question", kind="query", priority=9),
            ],
            Budget(max_tokens=4096),
        )
        print(result.cache_key)        # stable across requests with same static items
        print(result.cache_efficiency)  # 0.0 - 1.0
    """
    _VALID_PROVIDERS = {"anthropic", "openai", "auto"}
    if cache_config is not None and cache_config.provider is not None:
        if cache_config.provider not in _VALID_PROVIDERS:
            raise ValidationError(
                "Invalid cache config",
                details=[
                    {
                        "path": "cache_config.provider",
                        "message": f"provider must be one of {sorted(_VALID_PROVIDERS)} or None",
                    }
                ],
            )

    config = cache_config or CacheConfig()
    pack_kwargs = dict(options or {})

    # 1. Classify items by volatility
    static_items: List[ContextItem] = []
    session_items: List[ContextItem] = []
    request_items: List[ContextItem] = []

    for item in items:
        v = classify_volatility(item)
        if v == "static":
            static_items.append(item)
        elif v == "session":
            session_items.append(item)
        else:
            request_items.append(item)

    # 2. Sort static items deterministically by id
    static_items.sort(key=lambda x: x.id)

    # 3. Sort session items by recency
    session_items.sort(key=lambda x: x.recency or 0)

    # 4. Pack within each partition
    max_tokens = budget.max_tokens - (budget.reserve_tokens or 0)
    remaining = max_tokens

    # Static items: include all that fit
    selected_static: List[ContextItem] = []
    for item in static_items:
        tokens = item.tokens or estimate_tokens(item.content)
        if tokens <= remaining:
            item_copy = item.model_copy()
            item_copy.tokens = tokens
            selected_static.append(item_copy)
            remaining -= tokens

    # Session items: pack by score within remaining budget
    if remaining > 0 and session_items:
        session_pack = pack(session_items, Budget(max_tokens=remaining), **pack_kwargs)
        session_selected = session_pack.selected
        session_dropped = session_pack.dropped
        remaining -= session_pack.total_tokens
    else:
        session_selected = []
        session_dropped = list(session_items)

    # Request items: pack by score into whatever's left
    if remaining > 0 and request_items:
        request_pack = pack(request_items, Budget(max_tokens=remaining), **pack_kwargs)
        request_selected = request_pack.selected
        request_dropped = request_pack.dropped
    else:
        request_selected = []
        request_dropped = list(request_items)

    # 5. Compose final ordered list: static -> session -> request
    selected = selected_static + session_selected + request_selected
    selected_ids = {i.id for i in selected_static}
    dropped_static = [i for i in static_items if i.id not in selected_ids]
    dropped = dropped_static + session_dropped + request_dropped

    # 6. Add breakpoint markers if configured
    if config.mark_breakpoints:
        static_end = len(selected_static)
        session_end = static_end + len(session_selected)

        if static_end > 0 and static_end < len(selected):
            item = selected[static_end - 1]
            meta = dict(item.metadata or {})
            meta["_cacheBreakpoint"] = "static-end"
            selected[static_end - 1] = item.model_copy(update={"metadata": meta})

        if session_end > static_end and session_end < len(selected):
            item = selected[session_end - 1]
            meta = dict(item.metadata or {})
            meta["_cacheBreakpoint"] = "session-end"
            selected[session_end - 1] = item.model_copy(update={"metadata": meta})

    # 7. Compute cache key from stable prefix content
    static_content = "|".join(f"{i.id}:{i.content}" for i in selected_static)
    cache_key = _hash_string(static_content)

    static_tokens = sum(i.tokens or 0 for i in selected_static)
    total_tokens = sum(i.tokens or 0 for i in selected)

    return CacheAwarePack(
        budget=budget,
        selected=selected,
        dropped=dropped,
        total_tokens=total_tokens,
        stats={
            "staticCount": len(selected_static),
            "sessionCount": len(session_selected),
            "requestCount": len(request_selected),
            "remainingTokens": max(0, max_tokens - total_tokens),
        },
        cache_key=cache_key,
        cacheable_tokens=static_tokens,
        volatile_tokens=total_tokens - static_tokens,
        cache_efficiency=round(static_tokens / total_tokens, 3) if total_tokens > 0 else 0,
        partition_boundaries=[
            len(selected_static),
            len(selected_static) + len(session_selected),
        ],
    )


def _extract_async_kwargs(options: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract keyword arguments compatible with pack_async from options dict."""
    if not options:
        return {}
    kwargs: Dict[str, Any] = {}
    if "weights" in options:
        kwargs["weights"] = options["weights"]
    if "redundancy_config" in options:
        kwargs["redundancy_config"] = options["redundancy_config"]
    if "provider" in options:
        kwargs["provider"] = options["provider"]
    if "allow_compression" in options:
        kwargs["allow_compression"] = options["allow_compression"]
    return kwargs


async def pack_with_cache_topology_async(
    items: List[ContextItem],
    budget: Budget,
    options: Optional[Dict[str, Any]] = None,
    cache_config: Optional[CacheConfig] = None,
) -> CacheAwarePack:
    """Async version of pack_with_cache_topology that uses pack_async internally.

    Supports asynchronous redundancy elimination via pack_async.
    See pack_with_cache_topology for full documentation.

    Args:
        items: Context items to pack (should have `kind` set for best results)
        budget: Token budget
        options: Standard pack options (weights, etc.)
        cache_config: Cache-specific configuration

    Returns:
        CacheAwarePack with cache metadata
    """
    _VALID_PROVIDERS = {"anthropic", "openai", "auto"}
    if cache_config is not None and cache_config.provider is not None:
        if cache_config.provider not in _VALID_PROVIDERS:
            raise ValidationError(
                "Invalid cache config",
                details=[
                    {
                        "path": "cache_config.provider",
                        "message": f"provider must be one of {sorted(_VALID_PROVIDERS)} or None",
                    }
                ],
            )

    config = cache_config or CacheConfig()
    async_kwargs = _extract_async_kwargs(options)

    # 1. Classify items by volatility
    static_items: List[ContextItem] = []
    session_items: List[ContextItem] = []
    request_items: List[ContextItem] = []

    for item in items:
        v = classify_volatility(item)
        if v == "static":
            static_items.append(item)
        elif v == "session":
            session_items.append(item)
        else:
            request_items.append(item)

    # 2. Sort static items deterministically by id
    static_items.sort(key=lambda x: x.id)

    # 3. Sort session items by recency
    session_items.sort(key=lambda x: x.recency or 0)

    # 4. Pack within each partition
    max_tokens = budget.max_tokens - (budget.reserve_tokens or 0)
    remaining = max_tokens

    # Static items: include all that fit
    selected_static: List[ContextItem] = []
    for item in static_items:
        tokens = item.tokens or estimate_tokens(item.content)
        if tokens <= remaining:
            item_copy = item.model_copy()
            item_copy.tokens = tokens
            selected_static.append(item_copy)
            remaining -= tokens

    # Session items: pack by score within remaining budget
    if remaining > 0 and session_items:
        session_pack = await pack_async(session_items, Budget(max_tokens=remaining), **async_kwargs)
        session_selected = session_pack.selected
        session_dropped = session_pack.dropped
        remaining -= session_pack.total_tokens
    else:
        session_selected = []
        session_dropped = list(session_items)

    # Request items: pack by score into whatever's left
    if remaining > 0 and request_items:
        request_pack = await pack_async(request_items, Budget(max_tokens=remaining), **async_kwargs)
        request_selected = request_pack.selected
        request_dropped = request_pack.dropped
    else:
        request_selected = []
        request_dropped = list(request_items)

    # 5. Compose final ordered list: static -> session -> request
    selected = selected_static + session_selected + request_selected
    selected_ids = {i.id for i in selected_static}
    dropped_static = [i for i in static_items if i.id not in selected_ids]
    dropped = dropped_static + session_dropped + request_dropped

    # 6. Add breakpoint markers if configured
    if config.mark_breakpoints:
        static_end = len(selected_static)
        session_end = static_end + len(session_selected)

        if static_end > 0 and static_end < len(selected):
            item = selected[static_end - 1]
            meta = dict(item.metadata or {})
            meta["_cacheBreakpoint"] = "static-end"
            selected[static_end - 1] = item.model_copy(update={"metadata": meta})

        if session_end > static_end and session_end < len(selected):
            item = selected[session_end - 1]
            meta = dict(item.metadata or {})
            meta["_cacheBreakpoint"] = "session-end"
            selected[session_end - 1] = item.model_copy(update={"metadata": meta})

    # 7. Compute cache key from stable prefix content
    static_content = "|".join(f"{i.id}:{i.content}" for i in selected_static)
    cache_key = _hash_string(static_content)

    static_tokens = sum(i.tokens or 0 for i in selected_static)
    total_tokens = sum(i.tokens or 0 for i in selected)

    return CacheAwarePack(
        budget=budget,
        selected=selected,
        dropped=dropped,
        total_tokens=total_tokens,
        stats={
            "staticCount": len(selected_static),
            "sessionCount": len(session_selected),
            "requestCount": len(request_selected),
            "remainingTokens": max(0, max_tokens - total_tokens),
        },
        cache_key=cache_key,
        cacheable_tokens=static_tokens,
        volatile_tokens=total_tokens - static_tokens,
        cache_efficiency=round(static_tokens / total_tokens, 3) if total_tokens > 0 else 0,
        partition_boundaries=[
            len(selected_static),
            len(selected_static) + len(session_selected),
        ],
    )
