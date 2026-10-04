"""Compaction module: automatic context management for multi-turn agents.

Tracks token budgets across turns and compacts old content to stay in budget.
Think of it as "malloc for context windows."
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from .core import Budget, ContextItem, create_causal_scorer, estimate_tokens, validate_budget
from .errors import BudgetExceededError, ValidationError

# Async summarizer type: takes a ContextItem and target tokens, returns summarized item or None.
AsyncSummarizer = Callable[[ContextItem, int], Awaitable[Optional[ContextItem]]]


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
        async_summarizer: Optional[AsyncSummarizer] = None,
        batch_size: int = 5,
    ) -> None:
        self._budget = budget
        self._summarize_after = summarize_after_turns
        self._preserve_recent = preserve_recent_turns
        self._system_prompt = system_prompt
        self._estimate = token_estimator or (lambda text: estimate_tokens(text))
        self._async_summarizer = async_summarizer
        self._batch_size = batch_size
        self._turns: List[Turn] = []
        self._items: List[ContextItem] = []
        self._active_task_id: Optional[str] = None
        self._beads_graph: List[Any] = []

        validate_budget(budget)
        self._system_tokens = self._estimate(system_prompt) if system_prompt else 0
        self._effective_budget = budget.max_tokens - (budget.reserve_tokens or 0)
        # The system prompt is always included, so it must fit for compile()
        # to honour the budget as a hard cap.
        if self._system_tokens > self._effective_budget:
            raise BudgetExceededError(
                f"system_prompt ({self._system_tokens} tokens) exceeds the effective "
                f"budget ({self._effective_budget} tokens)"
            )

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
        1. Preserve recent turns verbatim (within the hard budget cap)
        2. Compact older turns (causal scoring if graph available, else summary)
        3. Pack context items into remaining budget

        The effective budget is a hard cap: if the preserved recent turns do
        not fit, the newest are kept and the oldest overflowing one is
        truncated (or dropped).
        """
        available = self._effective_budget - self._system_tokens

        # Phase 1: Preserve recent turns
        recent_turns, older_turns, available = self._split_recent(available)

        # Phase 2: Compact older turns
        compacted_older: List[Turn] = []

        # If we have a BEADS graph, we use causal scoring
        scorer = None
        if self._beads_graph:
            scorer = create_causal_scorer(self._beads_graph, self._active_task_id)

        if scorer and older_turns:
            compacted_older, available = self._causal_compact(older_turns, available, scorer)
        elif older_turns and len(older_turns) >= self._summarize_after:
            summary = self._truncate_older_turns(older_turns, available)
            if summary is not None:
                compacted_older.append(summary[0])
                available -= summary[1]
        else:
            for turn in older_turns:
                if turn.tokens <= available:
                    compacted_older.append(turn)
                    available -= turn.tokens

        # Phase 3: Pack context items into remaining budget
        selected_items = self._pack_items(available, scorer)

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

    def _truncate_to_fit(
        self, text: str, max_tokens: int, prefix: str = ""
    ) -> Optional[Tuple[str, int]]:
        """Truncate ``text`` word-by-word to the longest prefix whose estimate
        (with ``prefix`` prepended) fits ``max_tokens``. Returns None if not
        even one word fits."""
        if max_tokens <= 0:
            return None
        full = prefix + text
        full_tokens = self._estimate(full)
        if full_tokens <= max_tokens:
            return full, full_tokens

        words = text.split()
        lo, hi = 0, len(words)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self._estimate(prefix + " ".join(words[:mid])) <= max_tokens:
                lo = mid
            else:
                hi = mid - 1
        if lo == 0:
            return None
        content = prefix + " ".join(words[:lo])
        return content, self._estimate(content)

    def _split_recent(self, available: int) -> Tuple[List[Turn], List[Turn], int]:
        """Split turns into (recent kept within budget, older, remaining budget).

        Keeps the most recent contiguous run of preserved turns that fits in
        ``available``; the oldest turn that overflows is truncated to the
        remaining space when possible and anything older is dropped.
        """
        if self._preserve_recent > 0:
            recent = self._turns[-self._preserve_recent :]
            older = self._turns[: -self._preserve_recent]
        else:
            recent = []
            older = list(self._turns)

        kept: List[Turn] = []
        remaining = max(0, available)
        for turn in reversed(recent):
            if turn.tokens <= remaining:
                kept.insert(0, turn)
                remaining -= turn.tokens
                continue
            truncated = self._truncate_to_fit(turn.content, remaining)
            if truncated is not None:
                content, tokens = truncated
                kept.insert(0, replace(turn, content=content, tokens=tokens))
                remaining -= tokens
            break
        return kept, older, available - (max(0, available) - remaining)

    def _causal_compact(
        self, older_turns: List[Turn], available: int, scorer: Callable[[ContextItem], float]
    ) -> Tuple[List[Turn], int]:
        """Keep the causally most relevant older turns that fit.

        Timestamps are normalised to the same 0-10 recency scale as the TS
        implementation (most recent older turn = 10, oldest = 0) so raw Unix
        timestamps don't swamp priority and task multipliers.
        """
        timestamps = [t.timestamp for t in older_turns]
        min_ts, max_ts = min(timestamps), max(timestamps)
        ts_range = max_ts - min_ts

        scored_turns = []
        for idx, t in enumerate(older_turns):
            recency = ((t.timestamp - min_ts) / ts_range) * 10 if ts_range > 0 else 5.0
            item = ContextItem(
                id=f"turn-{idx}",
                content=t.content,
                tokens=t.tokens,
                task_id=t.task_id,
                is_outcome=t.is_outcome,
                priority=5.0,
                recency=recency,
            )
            scored_turns.append((t, scorer(item)))

        # Sort by causal score (stable, so ties keep conversation order)
        scored_turns.sort(key=lambda pair: pair[1], reverse=True)

        compacted: List[Turn] = []
        for t, _ in scored_turns:
            if t.tokens <= available:
                compacted.append(t)
                available -= t.tokens

        # Re-sort by timestamp for conversation order
        compacted.sort(key=lambda t: t.timestamp)
        return compacted, available

    def _truncate_older_turns(
        self, older_turns: List[Turn], available_budget: int
    ) -> Optional[Tuple[Turn, int]]:
        """Truncate older turns into a summary that fits within budget.

        The token count is estimated on the full summary string (header
        included), and None is returned when there is no room for a summary
        with any content.
        """
        combined = "\n".join(f"[{t.role}]: {t.content}" for t in older_turns)
        target_tokens = int(max(0, available_budget) * 0.3)
        prefix = f"[Summary of {len(older_turns)} earlier turns]\n"
        fitted = self._truncate_to_fit(combined, target_tokens, prefix)
        if fitted is None:
            return None
        summary_content, summary_tokens = fitted
        turn = Turn(
            role="system",
            content=summary_content,
            tokens=summary_tokens,
            is_summary=True,
            timestamp=older_turns[0].timestamp if older_turns else 0.0,
        )
        return turn, summary_tokens

    def _pack_items(self, available: int, scorer: Optional[Callable] = None) -> List[ContextItem]:
        """Pack context items into remaining budget."""
        if not self._items or available <= 0:
            return []

        item_scorer = scorer if scorer else (lambda i: i.score or 0.0)
        scored = []
        for item in self._items:
            tokens = item.tokens or self._estimate(item.content)
            item_with_tokens = item.model_copy(update={"tokens": tokens})
            score = item_scorer(item_with_tokens)
            scored.append((item_with_tokens, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)

        selected: List[ContextItem] = []
        used = 0
        for item, _ in scored:
            if used + (item.tokens or 0) <= available:
                selected.append(item)
                used += item.tokens or 0
        return selected

    async def compile_async(self) -> CompileResult:
        """Async compile with LLM summarization support.

        Like compile(), but when an async_summarizer is provided, batches
        older turns and calls the summarizer for each batch. Falls back
        to truncation if the summarizer returns None or raises.
        """
        available = self._effective_budget - self._system_tokens

        # Phase 1: Preserve recent turns
        recent_turns, older_turns, available = self._split_recent(available)

        # Phase 2: Compact older turns
        scorer = None
        if self._beads_graph:
            scorer = create_causal_scorer(self._beads_graph, self._active_task_id)

        compacted_older: List[Turn] = []

        if scorer and older_turns:
            # BEADS causal scoring — same as sync
            compacted_older, available = self._causal_compact(older_turns, available, scorer)

        elif older_turns and len(older_turns) >= self._summarize_after and self._async_summarizer:
            # Async summarization path: batch older turns
            batches: List[List[Turn]] = []
            for i in range(0, len(older_turns), self._batch_size):
                batches.append(older_turns[i : i + self._batch_size])

            per_batch_budget = int((available * 0.3) / len(batches)) if batches else 0

            for batch in batches:
                batch_content = "\n".join(f"[{t.role}]: {t.content}" for t in batch)
                batch_item = ContextItem(
                    id=f"batch-summary-{batch[0].timestamp if batch else 0}",
                    content=batch_content,
                    tokens=self._estimate(batch_content),
                )

                summary_result: Optional[ContextItem] = None
                try:
                    summary_result = await self._async_summarizer(batch_item, per_batch_budget)
                except Exception:
                    pass

                if (
                    summary_result
                    and (summary_result.tokens or self._estimate(summary_result.content))
                    <= available
                ):
                    summary_tokens = summary_result.tokens or self._estimate(summary_result.content)
                    compacted_older.append(
                        Turn(
                            role="system",
                            content=summary_result.content,
                            tokens=summary_tokens,
                            is_summary=True,
                            timestamp=batch[0].timestamp if batch else 0.0,
                        )
                    )
                    available -= summary_tokens
                else:
                    # Fallback: truncate this batch
                    summary = self._truncate_older_turns(batch, available)
                    if summary is not None:
                        compacted_older.append(summary[0])
                        available -= summary[1]

        elif older_turns and len(older_turns) >= self._summarize_after:
            # No async_summarizer — truncation (same as sync)
            summary = self._truncate_older_turns(older_turns, available)
            if summary is not None:
                compacted_older.append(summary[0])
                available -= summary[1]
        else:
            for turn in older_turns:
                if turn.tokens <= available:
                    compacted_older.append(turn)
                    available -= turn.tokens

        # Phase 3: Pack context items
        selected_items = self._pack_items(available, scorer)

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
    async_summarizer: Optional[AsyncSummarizer] = None,
    batch_size: int = 5,
) -> ContextManager:
    """Create an automatic context compaction manager.

    Args:
        budget: Token budget with max_tokens and optional reserve_tokens.
        summarize_after_turns: Compact older turns after this many (default: 5).
        preserve_recent_turns: Always keep last N turns verbatim (default: 2).
        system_prompt: System prompt to always include.
        token_estimator: Custom token estimator function.
        async_summarizer: Async summarizer for LLM-based compaction (compile_async only).
        batch_size: Number of turns per summarization batch (default: 5).

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
        async_summarizer=async_summarizer,
        batch_size=batch_size,
    )
