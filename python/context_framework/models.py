from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class ContextKind(str, Enum):
    SYSTEM = "system"
    MESSAGE = "message"
    MEMORY = "memory"
    DOCUMENT = "document"
    SUMMARY = "summary"


@dataclass(slots=True)
class ContextItem:
    text: str
    kind: ContextKind
    role: str = "system"
    source: str | None = None
    importance: float = 0.5
    pinned: bool = False
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = field(default_factory=lambda: uuid4().hex)
    token_count: int | None = None

    def __post_init__(self) -> None:
        self.importance = min(1.0, max(0.0, self.importance))


@dataclass(slots=True)
class ContextPacket:
    items: list[ContextItem]
    used_tokens: int
    token_budget: int
    dropped_items: list[ContextItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_messages(self) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for item in self.items:
            if item.kind in {ContextKind.MEMORY, ContextKind.DOCUMENT, ContextKind.SUMMARY}:
                prefix = item.kind.value
                if item.source:
                    content = f"[{prefix}:{item.source}] {item.text}"
                else:
                    content = f"[{prefix}] {item.text}"
                messages.append({"role": "system", "content": content})
                continue

            role = item.role if item.kind == ContextKind.MESSAGE else "system"
            messages.append({"role": role, "content": item.text})
        return messages
