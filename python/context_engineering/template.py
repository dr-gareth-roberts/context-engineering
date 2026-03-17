"""Prompt templating — assemble packed context items into LLM API messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from .core import ContextItem, ContextPack, estimate_tokens


@dataclass
class SectionRule:
    kind: str
    role: str  # "system" | "user" | "assistant"
    order: int = 999
    prefix: str = ""
    merge: bool = False
    merge_separator: str = "\n\n"
    cache_breakpoint: bool = False


@dataclass
class PromptTemplateConfig:
    sections: Optional[List[SectionRule]] = None
    fallback_role: str = "system"
    merge_system_messages: bool = False
    provider: Optional[str] = None  # "anthropic" | "openai"


@dataclass
class PromptMessage:
    role: str  # "system" | "user" | "assistant"
    content: str
    cache_control: Optional[Dict[str, str]] = None
    source_item_ids: List[str] = field(default_factory=list)
    source_kinds: List[str] = field(default_factory=list)


@dataclass
class PromptMessageStats:
    section_counts: Dict[str, int] = field(default_factory=dict)
    system_tokens: int = 0
    user_tokens: int = 0
    assistant_tokens: int = 0


@dataclass
class PromptMessages:
    messages: List[PromptMessage] = field(default_factory=list)
    total_tokens: int = 0
    included_item_ids: List[str] = field(default_factory=list)
    stats: PromptMessageStats = field(default_factory=PromptMessageStats)


@dataclass
class AnthropicMessages:
    system: Any = ""  # str or list of content blocks
    messages: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class OpenAIMessages:
    messages: List[Dict[str, str]] = field(default_factory=list)


DEFAULT_SECTION_RULES = [
    SectionRule(kind="system", role="system", order=0, merge=True),
    SectionRule(kind="instruction", role="system", order=1),
    SectionRule(kind="tool", role="system", order=2),
    SectionRule(kind="schema", role="system", order=3),
    SectionRule(kind="example", role="system", order=10, prefix="[Example]\n"),
    SectionRule(kind="memory", role="system", order=20, prefix="[Memory]\n"),
    SectionRule(kind="retrieval", role="system", order=30, prefix="[Retrieved]\n"),
    SectionRule(kind="history", role="user", order=40),
    SectionRule(kind="conversation", role="user", order=50),
    SectionRule(kind="tool-result", role="user", order=90),
    SectionRule(kind="query", role="user", order=100),
]


def _get_rules(config: Optional[PromptTemplateConfig]) -> List[SectionRule]:
    """Return section rules from config or defaults."""
    if config and config.sections:
        return config.sections
    return DEFAULT_SECTION_RULES


def _find_rule(kind: str, rules: List[SectionRule]) -> Optional[SectionRule]:
    """Find a section rule matching the given kind."""
    for rule in rules:
        if rule.kind == kind:
            return rule
    return None


def _resolve_role(
    item: ContextItem,
    rule: Optional[SectionRule],
    fallback_role: str,
) -> str:
    """Resolve the role for an item: item metadata > rule > fallback."""
    if item.metadata and "role" in item.metadata:
        return item.metadata["role"]
    if rule:
        return rule.role
    return fallback_role


def _get_order(rule: Optional[SectionRule]) -> int:
    """Get sort order for an item based on its rule."""
    if rule:
        return rule.order
    return 999


def to_messages(
    input: Union[ContextPack, List[ContextItem]],
    config: Optional[PromptTemplateConfig] = None,
) -> PromptMessages:
    """Convert packed context items into prompt messages.

    Items are grouped by kind, ordered by section rules, and assembled
    into role-tagged messages suitable for LLM APIs.
    """
    if isinstance(input, ContextPack):
        items = input.selected
    else:
        items = input

    rules = _get_rules(config)
    fallback_role = config.fallback_role if config else "system"
    merge_system = config.merge_system_messages if config else False

    # Sort items by rule order, preserving original order within same kind
    def sort_key(item: ContextItem) -> int:
        rule = _find_rule(item.kind or "", rules)
        return _get_order(rule)

    sorted_items = sorted(items, key=sort_key)

    # Group mergeable items by kind
    merged_groups: Dict[str, List[ContextItem]] = {}
    ordered_messages: List[PromptMessage] = []
    included_ids: List[str] = []
    stats = PromptMessageStats()

    for item in sorted_items:
        kind = item.kind or ""
        rule = _find_rule(kind, rules)
        role = _resolve_role(item, rule, fallback_role)

        # Track section counts
        stats.section_counts[kind] = stats.section_counts.get(kind, 0) + 1
        included_ids.append(item.id)

        content = item.content
        if rule and rule.prefix:
            content = rule.prefix + content

        # Handle merging
        if rule and rule.merge:
            if kind not in merged_groups:
                merged_groups[kind] = []
            merged_groups[kind].append(item)
            continue

        msg = PromptMessage(
            role=role,
            content=content,
            source_item_ids=[item.id],
            source_kinds=[kind] if kind else [],
        )

        if rule and rule.cache_breakpoint:
            msg.cache_control = {"type": "ephemeral"}

        ordered_messages.append(msg)

    # Insert merged groups at appropriate positions
    merged_messages: List[PromptMessage] = []
    for kind, group_items in merged_groups.items():
        rule = _find_rule(kind, rules)
        separator = rule.merge_separator if rule else "\n\n"
        role = _resolve_role(group_items[0], rule, fallback_role)

        contents = []
        for item in group_items:
            c = item.content
            if rule and rule.prefix:
                c = rule.prefix + c
            contents.append(c)

        merged_content = separator.join(contents)
        msg = PromptMessage(
            role=role,
            content=merged_content,
            source_item_ids=[item.id for item in group_items],
            source_kinds=[kind] if kind else [],
        )

        if rule and rule.cache_breakpoint:
            msg.cache_control = {"type": "ephemeral"}

        merged_messages.append(msg)

    # Combine: merged groups first (they have lower order), then ordered
    all_messages = merged_messages + ordered_messages

    # Optionally merge all system messages
    if merge_system:
        system_msgs = [m for m in all_messages if m.role == "system"]
        non_system = [m for m in all_messages if m.role != "system"]

        if system_msgs:
            combined = PromptMessage(
                role="system",
                content="\n\n".join(m.content for m in system_msgs),
                source_item_ids=[sid for m in system_msgs for sid in m.source_item_ids],
                source_kinds=[sk for m in system_msgs for sk in m.source_kinds],
            )
            all_messages = [combined] + non_system

    # Compute token stats
    total_tokens = 0
    for msg in all_messages:
        tokens = estimate_tokens(msg.content)
        total_tokens += tokens
        if msg.role == "system":
            stats.system_tokens += tokens
        elif msg.role == "user":
            stats.user_tokens += tokens
        elif msg.role == "assistant":
            stats.assistant_tokens += tokens

    return PromptMessages(
        messages=all_messages,
        total_tokens=total_tokens,
        included_item_ids=included_ids,
        stats=stats,
    )


def format_for_anthropic(
    prompt: PromptMessages,
    cache_breakpoints: bool = False,
) -> AnthropicMessages:
    """Format prompt messages for the Anthropic API.

    Extracts system messages into a separate `system` parameter.
    With cache_breakpoints, system uses content block format with
    cache_control markers.
    """
    system_msgs = [m for m in prompt.messages if m.role == "system"]
    non_system = [m for m in prompt.messages if m.role != "system"]

    # Build system content
    if cache_breakpoints:
        blocks: List[Dict[str, Any]] = []
        for msg in system_msgs:
            block: Dict[str, Any] = {"type": "text", "text": msg.content}
            if msg.cache_control:
                block["cache_control"] = msg.cache_control
            blocks.append(block)
        system: Any = blocks if blocks else ""
    else:
        system_text = "\n\n".join(m.content for m in system_msgs)
        system = system_text

    # Build conversation messages
    messages: List[Dict[str, str]] = []
    for msg in non_system:
        messages.append({"role": msg.role, "content": msg.content})

    return AnthropicMessages(system=system, messages=messages)


def format_for_openai(prompt: PromptMessages) -> OpenAIMessages:
    """Format prompt messages for the OpenAI API.

    System messages come first, followed by user/assistant messages.
    """
    system_msgs = [m for m in prompt.messages if m.role == "system"]
    non_system = [m for m in prompt.messages if m.role != "system"]

    messages: List[Dict[str, str]] = []
    for msg in system_msgs:
        messages.append({"role": "system", "content": msg.content})
    for msg in non_system:
        messages.append({"role": msg.role, "content": msg.content})

    return OpenAIMessages(messages=messages)


def compile_to_messages(
    compiled: Dict[str, Any],
    config: Optional[PromptTemplateConfig] = None,
) -> PromptMessages:
    """Convert a compiled context (with turns and items) into prompt messages.

    The compiled dict should have:
      - turns: list of dicts with role, content, and optional is_summary
      - items: list of ContextItem
      - total_tokens: int
    """
    turns = compiled.get("turns", [])
    items = compiled.get("items", [])
    total_tokens = compiled.get("total_tokens", 0)

    messages: List[PromptMessage] = []
    included_ids: List[str] = []
    stats = PromptMessageStats()

    # First, convert items into messages using standard rules
    if items:
        item_result = to_messages(items, config)
        messages.extend(item_result.messages)
        included_ids.extend(item_result.included_item_ids)
        stats = item_result.stats

    # Then append turns as conversation messages
    for turn in turns:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        is_summary = turn.get("is_summary", False)

        if is_summary:
            content = f"[Summary] {content}"

        msg = PromptMessage(
            role=role,
            content=content,
            source_item_ids=[],
            source_kinds=["conversation"],
        )
        messages.append(msg)

        tokens = estimate_tokens(content)
        if role == "system":
            stats.system_tokens += tokens
        elif role == "user":
            stats.user_tokens += tokens
        elif role == "assistant":
            stats.assistant_tokens += tokens

    # Recompute total tokens if not provided
    if total_tokens == 0:
        total_tokens = sum(estimate_tokens(m.content) for m in messages)

    return PromptMessages(
        messages=messages,
        total_tokens=total_tokens,
        included_item_ids=included_ids,
        stats=stats,
    )
