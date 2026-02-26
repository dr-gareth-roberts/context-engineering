from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Union

import tiktoken
from pydantic import BaseModel, ConfigDict, Field

from .errors import BudgetExceededError, ValidationError


class Compression(BaseModel):
    content: str
    tokens: Optional[int] = None
    note: Optional[str] = None


class ContextItem(BaseModel):
    id: str
    content: str
    kind: Optional[str] = None
    priority: Optional[float] = None
    recency: Optional[float] = None
    tokens: Optional[int] = None
    score: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    compressions: List[Compression] = Field(default_factory=list)
    supersedes: Optional[str] = None
    embedding: Optional[List[float]] = None
    parent_id: Optional[str] = None
    cost: float = 0.0
    latency: float = 0.0
    links: List[str] = Field(default_factory=list)


def create_context_item(id: str, content: str, **kwargs) -> ContextItem:
    """Create a ContextItem with sensible defaults.

    Only ``id`` and ``content`` are required.  All other ContextItem fields
    can be passed as keyword arguments.

    Example::

        item = create_context_item("readme", "# My Project\\n...")
        item = create_context_item("code", source, kind="code", priority=10)
    """
    return ContextItem(id=id, content=content, **kwargs)


class Budget(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    max_tokens: int = Field(alias="maxTokens")
    reserve_tokens: Optional[int] = Field(default=None, alias="reserveTokens")


class ContextPlan(BaseModel):
    budget: Budget
    items: List[ContextItem]
    strategy: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class ContextPack(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    budget: Budget
    selected: List[ContextItem]
    dropped: List[ContextItem]
    total_tokens: int = Field(alias="totalTokens")
    stats: Dict[str, Any] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)


class TraceStep(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    decision: str
    tokens: Optional[int] = None
    score: Optional[float] = None
    reason: Optional[str] = None
    used_compression: Optional[bool] = Field(default=None, alias="usedCompression")
    compressed_tokens: Optional[int] = Field(default=None, alias="compressedTokens")


class ContextTrace(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pack: ContextPack
    steps: List[TraceStep]
    created_at: str = Field(alias="createdAt")


class ContextHandoff(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_agent_id: str = Field(alias="sourceAgentId")
    target_agent_id: Optional[str] = Field(default=None, alias="targetAgentId")
    items: List[ContextItem]
    budget: Budget
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ScoringWeights:
    priority: float = 1.0
    recency: float = 0.7
    salience: float = 0.5
    cost: float = -0.3
    latency: float = -0.2
    relation_boost: float = 2.0


def calculate_weighted_score(item: ContextItem, weights: ScoringWeights = None) -> float:
    w = weights or ScoringWeights()
    p = item.priority or 0.0
    r = item.recency or 0.0
    s = float(item.metadata.get("salience", 0.0))
    score = (p * w.priority) + (r * w.recency) + (s * w.salience)
    score += (item.cost * w.cost) + (item.latency * w.latency)
    if item.supersedes:
        score += 5.0
    return score


def estimate_tokens(text: str, provider: Optional[str] = None, model: Optional[str] = None) -> int:
    """Estimate the token count for a text string.

    Args:
        text: The text to estimate. Returns 0 for empty/None.
        provider: "openai" uses tiktoken (cl100k_base). None uses heuristic (words × 1.3).
        model: Reserved for future model-specific tokenizers.

    Returns:
        Estimated token count (always >= 0).
    """
    if not text:
        return 0
    if provider == "openai":
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception:
            return _heuristic_tokens(text, 1.3)
    return _heuristic_tokens(text, 1.3)


def _heuristic_tokens(text: str, multiplier: float = 1.3) -> int:
    words = len(text.strip().split()) if text.strip() else 0
    return max(0, math.ceil(words * multiplier))


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot_product = sum(a * b for a, b in zip(v1, v2))
    m1 = math.sqrt(sum(a * a for a in v1))
    m2 = math.sqrt(sum(a * a for a in v2))
    if not m1 or not m2:
        return 0.0
    return dot_product / (m1 * m2)


def _apply_compression(
    item: ContextItem, remaining_tokens: int, provider: Optional[str] = None
) -> Optional[ContextItem]:
    if not item.compressions:
        return None
    candidates = []
    for c in item.compressions:
        tokens = c.tokens if c.tokens is not None else estimate_tokens(c.content, provider=provider)
        candidates.append((tokens, c))
    for tokens, c in sorted(candidates, key=lambda x: x[0]):
        if tokens <= remaining_tokens:
            return item.model_copy(
                update={
                    "content": c.content,
                    "tokens": tokens,
                    "metadata": {**item.metadata, "compressionNote": c.note or "compression"},
                }
            )
    return None


def pack(
    items: List[ContextItem],
    budget: Budget,
    *,
    allow_compression: bool = True,
    provider: Optional[str] = None,
    weights: Optional[ScoringWeights] = None,
    redundancy_threshold: Optional[float] = None,
) -> ContextPack:
    """Pack context items into a token budget using greedy score-based selection.

    Items are scored (default: priority*1.0 + recency*0.7 + salience*0.5),
    sorted by score, and greedily selected until the budget is exhausted.

    Args:
        items: Context items to pack.
        budget: Token budget with maxTokens and optional reserveTokens.
        allow_compression: If True, try item compressions when item is too large.
        provider: Token estimator — None (heuristic), "openai", or "anthropic".
        weights: Custom scoring weights for priority, recency, salience.
        redundancy_threshold: Cosine similarity threshold for redundancy detection.

    Returns:
        ContextPack with selected items, dropped items, and totalTokens.

    Raises:
        ValidationError: If budget.maxTokens <= 0.
        BudgetExceededError: If reserveTokens >= maxTokens.

    Example::

        from context_engineering import pack, Budget, create_context_item
        items = [create_context_item("doc", "Hello world", priority=5)]
        result = pack(items, Budget(maxTokens=1000))
        print(f"Selected {len(result.selected)} items")
    """
    if budget.max_tokens <= 0:
        raise ValidationError(
            f"maxTokens must be positive, got {budget.max_tokens}",
            [{"path": "maxTokens", "message": "must be positive"}],
        )
    if budget.reserve_tokens is not None and budget.reserve_tokens >= budget.max_tokens:
        raise BudgetExceededError(
            f"reserveTokens ({budget.reserve_tokens}) must be less than "
            f"maxTokens ({budget.max_tokens})"
        )
    return internal_pack(
        items,
        budget,
        trace=False,
        allow_compression=allow_compression,
        provider=provider,
        weights=weights,
        redundancy_threshold=redundancy_threshold,
    )


def internal_pack(
    items: List[ContextItem],
    budget: Budget,
    allow_compression: bool = True,
    provider: Optional[str] = None,
    trace: bool = False,
    redundancy_threshold: Optional[float] = None,
    weights: Optional[ScoringWeights] = None,
) -> Union[ContextPack, ContextTrace]:
    # 1. Scored Pre-pass
    scored = []
    for idx, item in enumerate(items):
        if not item.id:
            raise ValidationError(
                f"Item at index {idx} has empty id",
                [{"path": f"items[{idx}].id", "message": "id must be a non-empty string"}],
            )
        for field_name in ("priority", "recency", "tokens"):
            val = getattr(item, field_name, None)
            if val is not None and (math.isnan(val) or math.isinf(val)):
                raise ValidationError(
                    f"Item '{item.id}' has non-finite {field_name} ({val})",
                    [
                        {
                            "path": f"items[{item.id}].{field_name}",
                            "message": "must be a finite number",
                        }
                    ],
                )
        tokens = (
            item.tokens
            if item.tokens is not None
            else estimate_tokens(item.content, provider=provider)
        )
        if tokens < 0:
            raise ValidationError(
                f"Item '{item.id}' has negative tokens ({tokens})",
                [{"path": f"items[{item.id}].tokens", "message": "must be non-negative"}],
            )
        score = calculate_weighted_score(item, weights)
        scored.append(item.model_copy(update={"tokens": tokens, "score": score}))

    # 2. Negation Resolution (Recursive)
    negated_ids: Set[str] = set()

    def collect_negated():
        added = False
        for i in scored:
            if i.supersedes and i.supersedes not in negated_ids:
                negated_ids.add(i.supersedes)
                added = True
        if added:
            collect_negated()

    collect_negated()

    # 3. Dynamic Ranking Loop
    remaining = budget.max_tokens - (budget.reserve_tokens or 0)
    selected: List[ContextItem] = []
    dropped: List[ContextItem] = []
    steps: List[TraceStep] = []
    selected_ids: Set[str] = set()
    w = weights or ScoringWeights()

    # Pool excludes negated items
    pool = [i for i in scored if i.id not in negated_ids]
    for i in scored:
        if i.id in negated_ids:
            dropped.append(i)
            if trace:
                steps.append(
                    TraceStep(
                        id=i.id, decision="exclude", score=i.score, reason="negated_by_newer_info"
                    )
                )

    # IMPORTANT: Initial sort of pool before looping
    pool.sort(key=lambda x: (x.score or 0, x.recency or 0), reverse=True)

    while pool:
        # Re-calculate boosts based on CURRENTLY selected items
        for item in pool:
            boost = sum(w.relation_boost for sid in selected_ids if sid in item.links)
            item.score = calculate_weighted_score(item, weights) + boost

        # KEY: RE-SORT EVERY TIME we pull from pool to ensure highest boosted item is picked
        pool.sort(key=lambda x: (x.score or 0, x.recency or 0), reverse=True)
        item = pool.pop(0)

        # A. Hierarchical
        if item.parent_id and item.parent_id in selected_ids:
            dropped.append(item)
            if trace:
                steps.append(
                    TraceStep(
                        id=item.id,
                        decision="exclude",
                        score=item.score,
                        reason="parent_already_included",
                    )
                )
            continue

        # B. Redundancy
        if redundancy_threshold is not None and item.embedding:
            is_redundant = False
            for existing in selected:
                if (
                    existing.embedding
                    and _cosine_similarity(item.embedding, existing.embedding)
                    > redundancy_threshold
                ):
                    is_redundant = True
                    break
            if is_redundant:
                dropped.append(item)
                if trace:
                    steps.append(
                        TraceStep(
                            id=item.id,
                            decision="exclude",
                            score=item.score,
                            reason="semantic_redundancy",
                        )
                    )
                continue

        # C. Selection
        tokens = item.tokens if item.tokens is not None else 0
        if tokens <= remaining:
            selected.append(item)
            selected_ids.add(item.id)
            remaining -= tokens
            if trace:
                steps.append(
                    TraceStep(
                        id=item.id,
                        decision="include",
                        tokens=tokens,
                        score=item.score,
                        reason="fits_budget",
                    )
                )
            continue

        # D. Compression
        if allow_compression:
            compressed = _apply_compression(item, remaining, provider)
            if compressed is not None:
                selected.append(compressed)
                selected_ids.add(item.id)
                remaining -= compressed.tokens if compressed.tokens is not None else 0
                if trace:
                    steps.append(
                        TraceStep(
                            id=item.id,
                            decision="compress",
                            tokens=tokens,
                            score=item.score,
                            used_compression=True,
                            compressed_tokens=compressed.tokens,
                            reason="compressed_to_fit",
                        )
                    )
                continue

        # E. Drop
        dropped.append(item)
        if trace:
            steps.append(
                TraceStep(
                    id=item.id,
                    decision="exclude",
                    tokens=tokens,
                    score=item.score,
                    reason="over_budget",
                )
            )

    pack_result = ContextPack(
        budget=budget,
        selected=selected,
        dropped=dropped,
        totalTokens=sum((i.tokens if i.tokens is not None else 0) for i in selected),
        stats={
            "remainingTokens": max(0, remaining),
            "selectedCount": len(selected),
            "droppedCount": len(dropped),
        },
    )
    return (
        ContextTrace(
            pack=pack_result, steps=steps, createdAt=datetime.now(timezone.utc).isoformat()
        )
        if trace
        else pack_result
    )


def trace_pack(
    items: List[ContextItem],
    budget: Budget,
    *,
    allow_compression: bool = True,
    provider: Optional[str] = None,
    weights: Optional[ScoringWeights] = None,
    redundancy_threshold: Optional[float] = None,
) -> ContextTrace:
    """Pack items with a decision trace for debugging.

    Same algorithm as pack() but records every selection decision
    (include/compress/exclude) with reasons.

    Args:
        items: Context items to pack.
        budget: Token budget.
        allow_compression: If True, try item compressions when item is too large.
        provider: Token estimator — None (heuristic), "openai", or "anthropic".
        weights: Custom scoring weights for priority, recency, salience.
        redundancy_threshold: Cosine similarity threshold for redundancy detection.

    Returns:
        ContextTrace with pack result and per-item step decisions.
    """
    return internal_pack(
        items,
        budget,
        trace=True,
        allow_compression=allow_compression,
        provider=provider,
        weights=weights,
        redundancy_threshold=redundancy_threshold,
    )


def simulate_budgets(
    items: List[ContextItem], min_budget: int, max_budget: int, step: int = 100, **kwargs: Any
) -> Dict[int, List[str]]:
    results = {}
    for b in range(min_budget, max_budget + step, step):
        packed = pack(items, Budget(maxTokens=b), **kwargs)
        results[b] = [i.id for i in packed.selected]
    return results


def diff(
    before: Union[List[ContextItem], ContextPack, Dict[str, Any]],
    after: Union[List[ContextItem], ContextPack, Dict[str, Any]],
) -> Dict[str, Any]:
    """Compare two context states to find what changed.

    Accepts item lists, ContextPacks, or raw dicts with a ``selected`` key.
    Items are matched by ``id``. Content changes are detected.

    Args:
        before: The original context (items, pack, or dict).
        after: The updated context (items, pack, or dict).

    Returns:
        Dict with keys: ``added``, ``removed``, ``kept``, ``changed``.
        ``changed`` entries are ``{"before": item, "after": item}`` dicts.

    Example::

        result = diff(old_pack.selected, new_pack.selected)
        print(f"{len(result['added'])} added, {len(result['removed'])} removed")
    """

    def norm(v):
        if isinstance(v, ContextPack):
            return v.selected
        if isinstance(v, list):
            return [ContextItem.model_validate(i) if isinstance(i, dict) else i for i in v]
        if isinstance(v, dict) and "selected" in v:
            return [ContextItem.model_validate(i) for i in v["selected"]]
        return []

    b_items = norm(before)
    a_items = norm(after)
    b_map = {i.id: i for i in b_items}
    a_map = {i.id: i for i in a_items}
    return {
        "added": [i for i_id, i in a_map.items() if i_id not in b_map],
        "removed": [i for i_id, i in b_map.items() if i_id not in a_map],
        "kept": [
            i for i_id, i in a_map.items() if i_id in b_map and b_map[i_id].content == i.content
        ],
        "changed": [
            {"before": b_map[i_id], "after": i}
            for i_id, i in a_map.items()
            if i_id in b_map and b_map[i_id].content != i.content
        ],
    }
