"""Bridge module: convert MemoryItems to scored ContextItems.

Maps memory salience to metadata, computes recency via exponential decay
from createdAt. This bridges the memory -> pack pipeline gap.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from .core import ContextItem
from .memory import MemoryItem


@dataclass
class BridgeOptions:
    """Options for memory-to-context conversion."""

    priority: float = 5.0
    now: Optional[float] = None  # epoch ms; defaults to time.time() * 1000
    recency_half_life: float = 3600.0  # seconds
    kind: Optional[str] = None


def to_context_item(
    memory: MemoryItem,
    options: Optional[BridgeOptions] = None,
) -> ContextItem:
    """Convert a MemoryItem to a ContextItem with proper scoring fields.

    Maps salience to metadata.salience (used by the scorer),
    and computes recency from createdAt using exponential decay.

    Args:
        memory: The memory item to convert.
        options: Conversion options (priority, recency half-life, etc.).

    Returns:
        A ContextItem ready for packing.
    """
    opts = options or BridgeOptions()
    now_ms = opts.now or (time.time() * 1000)
    half_life = opts.recency_half_life

    created_ms = _parse_iso_to_ms(memory.created_at)
    age_seconds = (now_ms - created_ms) / 1000

    recency = math.pow(0.5, age_seconds / half_life) * 10 if half_life > 0 else 0.0
    recency = round(recency * 100) / 100

    metadata = dict(memory.metadata) if memory.metadata else {}
    metadata["salience"] = memory.salience if memory.salience is not None else 1.0
    metadata["createdAt"] = memory.created_at
    if memory.updated_at:
        metadata["updatedAt"] = memory.updated_at

    return ContextItem(
        id=memory.id,
        content=memory.content,
        kind=opts.kind or "memory",
        priority=opts.priority,
        recency=recency,
        metadata=metadata,
    )


def memory_to_context(
    memories: List[MemoryItem],
    options: Optional[BridgeOptions] = None,
) -> List[ContextItem]:
    """Batch convert MemoryItems to ContextItems.

    Args:
        memories: List of memory items.
        options: Conversion options applied to all items.

    Returns:
        List of ContextItems ready for packing.
    """
    return [to_context_item(m, options) for m in memories]


def _parse_iso_to_ms(iso_str: str) -> float:
    """Parse ISO 8601 datetime string to epoch milliseconds."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.timestamp() * 1000
    except (ValueError, TypeError):
        return time.time() * 1000
