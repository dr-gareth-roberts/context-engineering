from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .models import ContextItem
from .tokenizer import ApproxTokenCounter, TokenCounter


class ConversationSummarizer(Protocol):
    def summarize(
        self,
        *,
        existing_summary: str,
        new_messages: Sequence[ContextItem],
        max_tokens: int,
    ) -> str:
        ...


@dataclass(slots=True)
class RollingSummaryConfig:
    enabled: bool = False
    trigger_messages: int = 18
    keep_recent_messages: int = 6
    target_tokens: int = 256
    source: str = "rolling-conversation"

    def validate(self) -> None:
        if self.trigger_messages < 1:
            raise ValueError("trigger_messages must be >= 1")
        if self.keep_recent_messages < 0:
            raise ValueError("keep_recent_messages must be >= 0")
        if self.target_tokens < 1:
            raise ValueError("target_tokens must be >= 1")


@dataclass(slots=True)
class HeuristicConversationSummarizer:
    """
    Simple deterministic summarizer for rolling conversation memory.

    It creates bullet highlights and clips output to a token budget.
    """

    token_counter: TokenCounter | None = None
    snippet_chars: int = 140

    def __post_init__(self) -> None:
        if self.snippet_chars < 24:
            raise ValueError("snippet_chars must be >= 24")
        if self.token_counter is None:
            self.token_counter = ApproxTokenCounter()

    def summarize(
        self,
        *,
        existing_summary: str,
        new_messages: Sequence[ContextItem],
        max_tokens: int,
    ) -> str:
        if max_tokens < 1:
            return ""

        lines: list[str] = []
        if existing_summary.strip():
            lines.append(existing_summary.strip())

        if new_messages:
            lines.append("Conversation highlights:")
            for item in new_messages:
                role = item.role if item.role in {"user", "assistant"} else "note"
                text = " ".join(item.text.split())
                if len(text) > self.snippet_chars:
                    text = f"{text[: self.snippet_chars - 3].rstrip()}..."
                lines.append(f"- {role}: {text}")

        candidate = "\n".join(lines).strip()
        return self._clip_to_budget(candidate, max_tokens)

    def _clip_to_budget(self, text: str, max_tokens: int) -> str:
        if not text:
            return ""
        assert self.token_counter is not None
        if self.token_counter.count(text) <= max_tokens:
            return text

        low = 1
        high = len(text)
        best = ""
        while low <= high:
            mid = (low + high) // 2
            candidate = text[:mid].rstrip()
            if mid < len(text):
                candidate = f"{candidate}..."
            if self.token_counter.count(candidate) <= max_tokens:
                best = candidate
                low = mid + 1
            else:
                high = mid - 1
        return best
