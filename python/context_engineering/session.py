"""
Differential Context Sessions

Stateful session manager that tracks what was sent in previous requests
and computes minimal diffs between turns. Combined with cache-topology
packing, this maximizes prefix cache reuse across API calls.

Research: ACE framework showed 83.6% lower token costs with incremental
delta updates compared to full recomputation baselines.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .core import Budget, ContextItem, estimate_tokens, pack


@dataclass
class ManifestEntry:
    """A manifest entry tracking an item's position and content hash."""

    id: str
    content_hash: str
    tokens: int
    position: int


@dataclass
class SessionDelta:
    """Delta between two session states."""

    added: List[ContextItem]
    removed_ids: List[str]
    changed: List[ContextItem]
    kept_count: int
    delta_tokens: int
    reusable_tokens: int
    reuse_ratio: float


@dataclass
class SessionPack:
    """Result from session compile."""

    selected: List[ContextItem]
    dropped: List[ContextItem]
    total_tokens: int
    delta: Optional[SessionDelta]
    cache_key: str
    compile_count: int


def _quick_hash(s: str) -> str:
    """SHA-256 based hash for manifests and cache keys.

    Returns the first 16 hex characters for a compact but
    collision-resistant key.
    """
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _unchanged_prefix(
    previous: List[ManifestEntry], current: List[ManifestEntry]
) -> List[ManifestEntry]:
    prefix: List[ManifestEntry] = []
    for prev_entry, curr_entry in zip(previous, current):
        if prev_entry.id != curr_entry.id:
            break
        if prev_entry.content_hash != curr_entry.content_hash:
            break
        prefix.append(curr_entry)
    return prefix


class ContextSession:
    """A stateful context session that tracks changes between compiles.

    On each compile(), it packs the current items and computes the diff
    from the previous compile. This enables:
    - Tracking how much context actually changes between turns
    - Computing cache reuse ratios for cost estimation
    - Identifying stable prefixes that benefit from KV cache

    Example:
        session = create_session(Budget(max_tokens=8000))

        # Turn 1
        session.set_items([system_prompt, doc1, doc2, query1])
        r1 = session.compile()
        # r1.delta is None (first compile)

        # Turn 2 — only query changed
        session.set_items([system_prompt, doc1, doc2, query2])
        r2 = session.compile()
        # r2.delta.reuse_ratio ~ 0.85 (most tokens cached)
    """

    def __init__(self, budget: Budget, pack_options: Optional[Dict[str, Any]] = None):
        self._budget = budget
        self._pack_options = pack_options or {}
        self._current_items: List[ContextItem] = []
        self._previous_manifest: List[ManifestEntry] = []
        self._compile_count = 0
        self._lock = threading.Lock()

    def set_items(self, items: List[ContextItem]) -> None:
        """Replace the current item set."""
        with self._lock:
            self._current_items = list(items)

    def add_items(self, items: List[ContextItem]) -> None:
        """Add items to the current set (deduplicates by id)."""
        with self._lock:
            existing = {i.id: i for i in self._current_items}
            for item in items:
                existing[item.id] = item
            self._current_items = list(existing.values())

    def remove_items(self, ids: List[str]) -> None:
        """Remove items by ID."""
        with self._lock:
            remove_set = set(ids)
            self._current_items = [i for i in self._current_items if i.id not in remove_set]

    def compile(self) -> SessionPack:
        """Compile the current context, computing delta from previous."""
        with self._lock:
            # Pack current items
            packed = pack(self._current_items, self._budget, **self._pack_options)

            # Build manifest for current compile
            current_manifest: List[ManifestEntry] = []
            for i, item in enumerate(packed.selected):
                tokens = item.tokens or estimate_tokens(item.content)
                current_manifest.append(
                    ManifestEntry(
                        id=item.id,
                        content_hash=_quick_hash(item.content),
                        tokens=tokens,
                        position=i,
                    )
                )

            # Compute delta from previous
            delta: Optional[SessionDelta] = None

            # Compute unchanged prefix once (used for both delta and cache key).
            unchanged_prefix = _unchanged_prefix(self._previous_manifest, current_manifest)

            if self._compile_count > 0:
                prev_map = {e.id: e for e in self._previous_manifest}
                curr_map = {e.id: e for e in current_manifest}
                reusable_prefix_ids = {entry.id for entry in unchanged_prefix}

                added: List[ContextItem] = []
                changed: List[ContextItem] = []
                removed_ids: List[str] = []
                kept_count = 0
                added_tokens = 0
                removed_tokens = 0
                changed_tokens = 0
                reusable_tokens = 0

                # Build a map from id -> item for O(1) lookups
                selected_map = {i.id: i for i in packed.selected}

                # Find added and changed
                for entry in current_manifest:
                    prev = prev_map.get(entry.id)
                    if prev is None:
                        item = selected_map.get(entry.id)
                        if item:
                            added.append(item)
                        added_tokens += entry.tokens
                    elif prev.content_hash != entry.content_hash:
                        item = selected_map.get(entry.id)
                        if item:
                            changed.append(item)
                        changed_tokens += entry.tokens
                    else:
                        kept_count += 1
                        if entry.id in reusable_prefix_ids:
                            reusable_tokens += entry.tokens

                # Find removed
                for entry in self._previous_manifest:
                    if entry.id not in curr_map:
                        removed_ids.append(entry.id)
                        removed_tokens += entry.tokens

                delta_tokens = added_tokens + removed_tokens + changed_tokens
                total_prev = sum(e.tokens for e in self._previous_manifest)

                delta = SessionDelta(
                    added=added,
                    removed_ids=removed_ids,
                    changed=changed,
                    kept_count=kept_count,
                    delta_tokens=delta_tokens,
                    reusable_tokens=reusable_tokens,
                    reuse_ratio=round(reusable_tokens / total_prev, 3) if total_prev > 0 else 0,
                )

            # Generate cache key from unchanged prefix
            cache_key = _quick_hash(
                ",".join(
                    f"{entry.position}:{entry.id}:{entry.content_hash}"
                    for entry in unchanged_prefix
                )
                or "empty"
            )

            # Update state for next compile
            self._previous_manifest = current_manifest
            self._compile_count += 1

            return SessionPack(
                selected=list(packed.selected),
                dropped=list(packed.dropped),
                total_tokens=packed.total_tokens,
                delta=delta,
                cache_key=cache_key,
                compile_count=self._compile_count,
            )

    def item_count(self) -> int:
        """Get the current item count (before packing)."""
        with self._lock:
            return len(self._current_items)

    def get_compile_count(self) -> int:
        """Get the number of compiles performed."""
        with self._lock:
            return self._compile_count

    def clear(self) -> None:
        """Reset the session."""
        with self._lock:
            self._current_items = []
            self._previous_manifest = []
            self._compile_count = 0


def create_session(
    budget: Budget,
    pack_options: Optional[Dict[str, Any]] = None,
) -> ContextSession:
    """Create a new context session.

    Args:
        budget: Token budget for packing
        pack_options: Default pack options

    Returns:
        A ContextSession instance
    """
    return ContextSession(budget, pack_options)
