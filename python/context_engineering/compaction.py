"""Compaction module: automatic context management for multi-turn agents.

Tracks token budgets across turns and compacts old content to stay in budget.
Think of it as "malloc for context windows."
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .core import Budget, ContextItem, create_causal_scorer, estimate_tokens
from .errors import ValidationError


@dataclass
class Turn:
    """A conversation turn."""

    role: str
    content: str
    tokens: int = 0
    timestamp: float = 0.0
    is_summary: bool = False
    task_id: Optional[str] = None
    is_outcome: Optional[bool] = None


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
        self._active_task_id: Optional[str] = None
        self._beads_graph: List[Any] = []

        self._system_tokens = self._estimate(system_prompt) if system_prompt else 0
        self._effective_budget = budget.max_tokens - (budget.reserve_tokens or 0)

    def set_active_task(self, task_id: str) -> None:
        """Set the currently active task ID."""
        self._active_task_id = task_id

    def set_beads_graph(self, issues: List[Any]) -> None:
        """Provide a BEADS graph for causal scoring."""
        self._beads_graph = issues

    def add_turn(
        self, role: str, content: str, task_id: Optional[str] = None, is_outcome: bool = False
    ) -> None:
        """Add a conversation turn."""
        tokens = self._estimate(content)
        tid = task_id or self._active_task_id
        self._turns.append(
            Turn(
                role=role,
                content=content,
                tokens=tokens,
                timestamp=time.time(),
                task_id=tid,
                is_outcome=is_outcome,
            )
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
        2. Compact older turns (causal scoring if graph available, else summary)
        3. Pack context items into remaining budget
        """
        available = self._effective_budget - self._system_tokens

        # Phase 1: Preserve recent turns
        if self._preserve_recent > 0:
            recent_turns = self._turns[-self._preserve_recent :]
            older_turns = self._turns[: -self._preserve_recent]
        else:
            recent_turns = []
            older_turns = list(self._turns)

        recent_tokens = sum(t.tokens for t in recent_turns)
        available -= recent_tokens

        # Phase 2: Compact older turns
        compacted_older: List[Turn] = []

        # If we have a BEADS graph, we use causal scoring
        scorer = None
        if self._beads_graph:
            scorer = create_causal_scorer(self._beads_graph, self._active_task_id)

        if scorer and older_turns:
            # Map Turns to ContextItems for scoring
            scored_turns = []
            for idx, t in enumerate(older_turns):
                item = ContextItem(
                    id=f"turn-{idx}",
                    content=t.content,
                    tokens=t.tokens,
                    task_id=t.task_id,
                    is_outcome=t.is_outcome,
                    priority=5.0,
                    recency=t.timestamp,
                )
                score = scorer(item)
                scored_turns.append((t, score))

            # Sort by causal score
            scored_turns.sort(key=lambda pair: pair[1], reverse=True)

            for t, _ in scored_turns:
                if t.tokens <= available:
                    compacted_older.append(t)
                    available -= t.tokens

            # Re-sort by timestamp for conversation order
            compacted_older.sort(key=lambda t: t.timestamp)

        elif older_turns and len(older_turns) >= self._summarize_after:
            combined = "\n".join(f"[{t.role}]: {t.content}" for t in older_turns)
            target_tokens = int(available * 0.3)
            # Binary search for the right truncation point to hit target_tokens.
            # Start with a heuristic then adjust.
            lo, hi = 0, len(combined)
            truncated = combined
            while lo < hi:
                mid = (lo + hi) // 2
                candidate = combined[:mid]
                est = self._estimate(candidate)
                if est <= target_tokens:
                    truncated = candidate
                    lo = mid + 1
                else:
                    hi = mid
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
            item_scorer = scorer if scorer else (lambda i: i.score or 0.0)

            scored = []
            for item in self._items:
                tokens = item.tokens or self._estimate(item.content)
                item_with_tokens = item.model_copy(update={"tokens": tokens})
                score = item_scorer(item_with_tokens)
                scored.append((item_with_tokens, score))

            scored.sort(key=lambda pair: pair[1], reverse=True)

            used_item_tokens = 0
            for item, _ in scored:
                if used_item_tokens + (item.tokens or 0) <= available:
                    selected_items.append(item)
                    used_item_tokens += item.tokens or 0

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
        self._active_task_id = None
        self._beads_graph = []


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
    if budget.max_tokens <= 0:
        raise ValidationError(
            "Invalid budget",
            details=[
                {
                    "path": "budget.max_tokens",
                    "message": "max_tokens must be greater than 0",
                }
            ],
        )

    return ContextManager(
        budget=budget,
        summarize_after_turns=summarize_after_turns,
        preserve_recent_turns=preserve_recent_turns,
        system_prompt=system_prompt,
        token_estimator=token_estimator,
    )
