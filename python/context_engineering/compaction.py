"""Compaction module: automatic context management for multi-turn agents.

Tracks token budgets across turns and compacts old content to stay in budget.
Think of it as "malloc for context windows."
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .core import Budget, ContextItem, estimate_tokens


@dataclass
class Turn:
    """A conversation turn."""

    role: str
    content: str
    tokens: int = 0
    timestamp: float = 0.0
    is_summary: bool = False


@dataclass
class CompileResult:
    """Result of compiling context."""

    turns: List[Turn]
    items: List[ContextItem]
    total_tokens: int


class ContextManager:
    """Manages context across turns with automatic compaction.

    Tracks token budgets, preserves recent turns verbatim, and compacts
    older turns into summaries when they exceed the summarize threshold.
    """

    def __init__(
        self,
        budget: Budget,
        summarize_after_turns: int = 5,
        preserve_recent_turns: int = 2,
        system_prompt: Optional[str] = None,
        token_estimator: Optional[Callable[[str], int]] = None,
    ) -> None:
        self._budget = budget
        self._summarize_after = summarize_after_turns
        self._preserve_recent = preserve_recent_turns
        self._system_prompt = system_prompt
        self._estimate = token_estimator or (lambda text: estimate_tokens(text))
        self._turns: List[Turn] = []
        self._items: List[ContextItem] = []

        self._system_tokens = self._estimate(system_prompt) if system_prompt else 0
        self._effective_budget = budget.max_tokens - (budget.reserve_tokens or 0)

    def add_turn(self, role: str, content: str) -> None:
        """Add a conversation turn."""
        tokens = self._estimate(content)
        self._turns.append(
            Turn(role=role, content=content, tokens=tokens, timestamp=time.time())
        )

    def add_items(self, items: List[ContextItem]) -> None:
        """Add context items (e.g., from memory queries)."""
        self._items.extend(items)

    def get_token_usage(self) -> Dict[str, int]:
        """Get current token usage breakdown."""
        turn_tokens = sum(t.tokens for t in self._turns)
        item_tokens = sum(i.tokens or self._estimate(i.content) for i in self._items)
        used = self._system_tokens + turn_tokens + item_tokens
        return {
            "used": used,
            "budget": self._effective_budget,
            "remaining": max(0, self._effective_budget - used),
        }

    def compile(self) -> CompileResult:
        """Compile context -- returns turns + items that fit within budget.

        Three phases:
        1. Preserve recent turns verbatim
        2. Compact older turns into summary if threshold exceeded
        3. Pack context items into remaining budget
        """
        available = self._effective_budget - self._system_tokens

        # Phase 1: Preserve recent turns
        if self._preserve_recent and len(self._turns) > self._preserve_recent:
            recent_turns = self._turns[-self._preserve_recent :]
            older_turns = self._turns[: -self._preserve_recent]
        else:
            recent_turns = list(self._turns)
            older_turns = []

        recent_tokens = sum(t.tokens for t in recent_turns)
        available -= recent_tokens

        # Phase 2: Compact older turns
        compacted_older: List[Turn] = []

        if older_turns and len(older_turns) >= self._summarize_after:
            combined = "\n".join(f"[{t.role}]: {t.content}" for t in older_turns)
            target_tokens = int(available * 0.3)
            truncated = combined[: target_tokens * 4]
            summary_tokens = self._estimate(truncated)

            compacted_older.append(
                Turn(
                    role="system",
                    content=f"[Summary of {len(older_turns)} earlier turns]\n{truncated}",
                    tokens=summary_tokens,
                    is_summary=True,
                    timestamp=older_turns[0].timestamp if older_turns else 0.0,
                )
            )
            available -= summary_tokens
        else:
            for turn in older_turns:
                if turn.tokens <= available:
                    compacted_older.append(turn)
                    available -= turn.tokens

        # Phase 3: Pack context items into remaining budget
        selected_items: List[ContextItem] = []
        if self._items and available > 0:
            scored = []
            for item in self._items:
                tokens = item.tokens or self._estimate(item.content)
                scored.append((item, tokens))

            scored.sort(key=lambda pair: pair[0].score or 0, reverse=True)

            used_item_tokens = 0
            for item, tokens in scored:
                if used_item_tokens + tokens <= available:
                    selected_items.append(item)
                    used_item_tokens += tokens

        all_turns = compacted_older + recent_turns
        total_tokens = (
            self._system_tokens
            + sum(t.tokens for t in all_turns)
            + sum(i.tokens or self._estimate(i.content) for i in selected_items)
        )

        return CompileResult(
            turns=all_turns,
            items=selected_items,
            total_tokens=total_tokens,
        )

    def turn_count(self) -> int:
        """Get the number of turns."""
        return len(self._turns)

    def clear(self) -> None:
        """Clear all turns and items."""
        self._turns = []
        self._items = []


def create_context_manager(
    budget: Budget,
    summarize_after_turns: int = 5,
    preserve_recent_turns: int = 2,
    system_prompt: Optional[str] = None,
    token_estimator: Optional[Callable[[str], int]] = None,
) -> ContextManager:
    """Create an automatic context compaction manager.

    Args:
        budget: Token budget with max_tokens and optional reserve_tokens.
        summarize_after_turns: Compact older turns after this many (default: 5).
        preserve_recent_turns: Always keep last N turns verbatim (default: 2).
        system_prompt: System prompt to always include.
        token_estimator: Custom token estimator function.

    Returns:
        A ContextManager instance.
    """
    return ContextManager(
        budget=budget,
        summarize_after_turns=summarize_after_turns,
        preserve_recent_turns=preserve_recent_turns,
        system_prompt=system_prompt,
        token_estimator=token_estimator,
    )
