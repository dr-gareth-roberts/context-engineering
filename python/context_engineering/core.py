from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Union
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import math
import tiktoken


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


class Budget(BaseModel):
    max_tokens: int = Field(alias="maxTokens")
    reserve_tokens: Optional[int] = Field(default=None, alias="reserveTokens")

    class Config:
        populate_by_name = True


class ContextPlan(BaseModel):
    budget: Budget
    items: List[ContextItem]
    strategy: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class ContextPack(BaseModel):
    budget: Budget
    selected: List[ContextItem]
    dropped: List[ContextItem]
    total_tokens: int = Field(alias="totalTokens")
    stats: Dict[str, Any] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)

    class Config:
        populate_by_name = True


class TraceStep(BaseModel):
    id: str
    decision: str
    tokens: Optional[int] = None
    score: Optional[float] = None
    reason: Optional[str] = None
    used_compression: Optional[bool] = Field(default=None, alias="usedCompression")
    compressed_tokens: Optional[int] = Field(default=None, alias="compressedTokens")

    class Config:
        populate_by_name = True


class ContextTrace(BaseModel):
    pack: ContextPack
    steps: List[TraceStep]
    created_at: str = Field(alias="createdAt")

    class Config:
        populate_by_name = True


class ContextHandoff(BaseModel):
    source_agent_id: str = Field(alias="sourceAgentId")
    target_agent_id: Optional[str] = Field(default=None, alias="targetAgentId")
    items: List[ContextItem]
    budget: Budget
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    class Config:
        populate_by_name = True


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
    if item.supersedes: score += 5.0
    return score


def estimate_tokens(text: str, provider: Optional[str] = None, model: Optional[str] = None) -> int:
    """Estimate the token count for a text string.

    Args:
        text: The text to estimate tokens for.
        **kwargs: Optional model or provider.

    Returns:
        The estimated token count.
    """
    if not text:
        return 0
    if provider == "openai":
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception: return _heuristic_tokens(text, 1.3)
    return _heuristic_tokens(text, 1.3)

def _heuristic_tokens(text: str, multiplier: float = 1.3) -> int:
    words = len(text.strip().split()) if text.strip() else 0
    return max(0, math.ceil(words * multiplier))

def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot_product = sum(a * b for a, b in zip(v1, v2))
    m1 = math.sqrt(sum(a * a for a in v1))
    m2 = math.sqrt(sum(a * a for a in v2))
    if not m1 or not m2: return 0.0
    return dot_product / (m1 * m2)

def _apply_compression(item: ContextItem, remaining_tokens: int, provider: Optional[str] = None) -> Optional[ContextItem]:
    if not item.compressions: return None
    candidates = []
    for c in item.compressions:
        tokens = c.tokens or estimate_tokens(c.content, provider=provider)
        candidates.append((tokens, c))
    for tokens, c in sorted(candidates, key=lambda x: x[0]):
        if tokens <= remaining_tokens:
            return item.model_copy(update={"content": c.content, "tokens": tokens, "metadata": {**item.metadata, "compressionNote": c.note or "compression"}})
    return None

def pack(items: List[ContextItem], budget: Budget, **kwargs: Any) -> ContextPack:
    """Pack context items into a token budget using greedy score-based selection.

    Args:
        items: Context items to pack.
        budget: Token budget with maxTokens and optional reserveTokens.
        **kwargs: Optional scorer, token_estimator, weights.

    Returns:
        ContextPack with selected items, dropped items, and stats.

    Raises:
        ValueError: If budget.maxTokens <= 0 or reserveTokens >= maxTokens.
    """
    if budget.max_tokens <= 0:
        raise ValueError(f"maxTokens must be positive, got {budget.max_tokens}")
    if budget.reserve_tokens is not None and budget.reserve_tokens >= budget.max_tokens:
        raise ValueError(
            f"reserveTokens ({budget.reserve_tokens}) must be less than "
            f"maxTokens ({budget.max_tokens})"
        )
    return internal_pack(items, budget, trace=False, **kwargs)

def internal_pack(
    items: List[ContextItem],
    budget: Budget,
    allow_compression: bool = True,
    provider: Optional[str] = None,
    trace: bool = False,
    redundancy_threshold: Optional[float] = None,
    weights: Optional[ScoringWeights] = None
) -> Union[ContextPack, ContextTrace]:
    # 1. Scored Pre-pass
    scored = []
    for item in items:
        tokens = item.tokens or estimate_tokens(item.content, provider=provider)
        score = calculate_weighted_score(item, weights)
        scored.append(item.model_copy(update={"tokens": tokens, "score": score}))

    # 2. Negation Resolution (Recursive)
    negated_ids: Set[str] = set()
    def collect_negated():
        added = False
        for i in scored:
            if i.supersedes and i.supersedes not in negated_ids:
                negated_ids.add(i.supersedes); added = True
        if added: collect_negated()
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
            if trace: steps.append(TraceStep(id=i.id, decision="exclude", score=i.score, reason="negated_by_newer_info"))

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
            if trace: steps.append(TraceStep(id=item.id, decision="exclude", score=item.score, reason="parent_already_included"))
            continue

        # B. Redundancy
        if redundancy_threshold is not None and item.embedding:
            is_redundant = False
            for existing in selected:
                if existing.embedding and _cosine_similarity(item.embedding, existing.embedding) > redundancy_threshold:
                    is_redundant = True; break
            if is_redundant:
                dropped.append(item)
                if trace: steps.append(TraceStep(id=item.id, decision="exclude", score=item.score, reason="semantic_redundancy"))
                continue

        # C. Selection
        tokens = item.tokens or 0
        if tokens <= remaining:
            selected.append(item); selected_ids.add(item.id); remaining -= tokens
            if trace: steps.append(TraceStep(id=item.id, decision="include", tokens=tokens, score=item.score, reason="fits_budget"))
            continue

        # D. Compression
        if allow_compression:
            compressed = _apply_compression(item, remaining, provider)
            if compressed is not None:
                selected.append(compressed); selected_ids.add(item.id); remaining -= compressed.tokens or 0
                if trace: steps.append(TraceStep(id=item.id, decision="compress", tokens=tokens, score=item.score, used_compression=True, compressed_tokens=compressed.tokens, reason="compressed_to_fit"))
                continue

        # E. Drop
        dropped.append(item)
        if trace: steps.append(TraceStep(id=item.id, decision="exclude", tokens=tokens, score=item.score, reason="over_budget"))

    pack_result = ContextPack(
        budget=budget, selected=selected, dropped=dropped, totalTokens=sum(i.tokens or 0 for i in selected),
        stats={"remainingTokens": max(0, remaining), "selectedCount": len(selected), "droppedCount": len(dropped)}
    )
    return ContextTrace(pack=pack_result, steps=steps, createdAt=datetime.now(timezone.utc).isoformat()) if trace else pack_result


def trace_pack(items: List[ContextItem], budget: Budget, **kwargs: Any) -> ContextTrace:
    """Pack items with a decision trace for debugging.

    Same algorithm as pack() but records every selection decision.

    Args:
        items: Context items to pack.
        budget: Token budget.
        **kwargs: Optional scorer, token_estimator, weights.

    Returns:
        ContextTrace with pack result and step-by-step decisions.
    """
    return internal_pack(items, budget, trace=True, **kwargs)

def simulate_budgets(items: List[ContextItem], min_budget: int, max_budget: int, step: int = 100, **kwargs: Any) -> Dict[int, List[str]]:
    results = {}
    for b in range(min_budget, max_budget + step, step):
        packed = pack(items, Budget(maxTokens=b), **kwargs)
        results[b] = [i.id for i in packed.selected]
    return results

def diff(before: Union[List[ContextItem], ContextPack, Dict[str, Any]], after: Union[List[ContextItem], ContextPack, Dict[str, Any]]) -> Dict[str, Any]:
    """Compare two context item lists to find differences.

    Args:
        before: The original context items.
        after: The updated context items.

    Returns:
        Object with added, removed, kept, and changed items.
    """
    def norm(v):
        if isinstance(v, ContextPack): return v.selected
        if isinstance(v, list): return [ContextItem.model_validate(i) if isinstance(i, dict) else i for i in v]
        if isinstance(v, dict) and "selected" in v: return [ContextItem.model_validate(i) for i in v["selected"]]
        return []
    b_items = norm(before); a_items = norm(after)
    b_map = {i.id: i for i in b_items}; a_map = {i.id: i for i in a_items}
    return {
        "added": [i for i_id, i in a_map.items() if i_id not in b_map],
        "removed": [i for i_id, i in b_map.items() if i_id not in a_map],
        "kept": [i for i_id, i in a_map.items() if i_id in b_map and b_map[i_id].content == i.content],
        "changed": [{"before": b_map[i_id], "after": i} for i_id, i in a_map.items() if i_id in b_map and b_map[i_id].content != i.content]
    }
