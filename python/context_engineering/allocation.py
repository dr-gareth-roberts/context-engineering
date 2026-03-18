"""
Kind-Aware Budget Allocation

Replaces flat greedy packing with category-level budget constraints.
Instead of treating all items as a flat list, groups them by `kind`
and allocates budget per category with min/max/target constraints.

Research: "Token-Budget-Aware LLM Reasoning" (ACL 2025) showed up to
47% cost reduction with dynamic budget approaches while maintaining accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .core import Budget, ContextItem, pack, pack_async
from .errors import ValidationError


@dataclass
class KindAllocation:
    """Budget constraint for a single item kind."""

    kind: str
    min_tokens: Optional[int] = None
    max_tokens: Optional[int] = None
    target_ratio: Optional[float] = None
    priority: int = 0


@dataclass
class KindResult:
    """Per-kind allocation result."""

    kind: str
    budget_allocated: int
    budget_used: int
    item_count: int
    surplus: int


@dataclass
class AllocatedPack:
    """Result of kind-aware packing."""

    budget: Budget
    selected: List[ContextItem]
    dropped: List[ContextItem]
    total_tokens: int
    stats: Dict[str, Any]
    allocations: Dict[str, KindResult]
    allocation_efficiency: float


def pack_with_allocation(
    items: List[ContextItem],
    budget: Budget,
    allocations: List[KindAllocation],
    options: Optional[Dict[str, Any]] = None,
) -> AllocatedPack:
    """Pack items with kind-aware budget allocation.

    Groups items by `kind`, allocates budget per category respecting
    min/max/target constraints, then packs greedily within each allocation.
    Surplus budget from underfilled categories is redistributed to
    overfilled ones by priority.

    Args:
        items: Context items to pack (should have `kind` set)
        budget: Total token budget
        allocations: Per-kind budget constraints
        options: Standard pack options

    Returns:
        AllocatedPack with per-kind breakdown

    Example:
        result = pack_with_allocation(
            items,
            Budget(max_tokens=8000),
            [
                KindAllocation(kind="system", min_tokens=500, target_ratio=0.15, priority=10),
                KindAllocation(kind="retrieval", target_ratio=0.40, priority=5),
                KindAllocation(kind="conversation", target_ratio=0.35, priority=7),
            ],
        )
        print(result.allocations)
        print(result.allocation_efficiency)
    """
    details = []
    for i, alloc in enumerate(allocations):
        kind = alloc.kind if hasattr(alloc, "kind") else alloc.get("kind", "")
        if not kind:
            details.append(
                {
                    "path": f"allocations[{i}].kind",
                    "message": "kind must be a non-empty string",
                }
            )
        ratio = (
            alloc.target_ratio
            if hasattr(alloc, "target_ratio")
            else alloc.get("target_ratio", None)
        )
        if ratio is not None and not (0 <= ratio <= 1):
            details.append(
                {
                    "path": f"allocations[{i}].target_ratio",
                    "message": "target_ratio must be between 0 and 1",
                }
            )
    if details:
        raise ValidationError("Invalid allocation config", details=details)

    pack_kwargs = dict(options or {})
    effective_budget = budget.max_tokens - (budget.reserve_tokens or 0)

    # Group items by kind
    kind_groups: Dict[str, List[ContextItem]] = {}
    uncategorized: List[ContextItem] = []
    alloc_kinds = {a.kind for a in allocations}

    for item in items:
        kind = item.kind or "_uncategorized"
        if kind in alloc_kinds:
            kind_groups.setdefault(kind, []).append(item)
        else:
            uncategorized.append(item)

    # Phase 1: Compute initial allocation per kind
    kind_budgets: Dict[str, int] = {}
    allocated_total = 0

    for alloc in allocations:
        tokens = 0
        if alloc.target_ratio is not None:
            tokens = int(effective_budget * alloc.target_ratio)
        if alloc.min_tokens is not None:
            tokens = max(tokens, alloc.min_tokens)
        if alloc.max_tokens is not None:
            tokens = min(tokens, alloc.max_tokens)
        kind_budgets[alloc.kind] = tokens
        allocated_total += tokens

    # Scale if over-allocated
    if allocated_total > effective_budget:
        scale = effective_budget / allocated_total
        for alloc in allocations:
            scaled = int(kind_budgets[alloc.kind] * scale)
            if alloc.min_tokens is not None:
                scaled = max(scaled, alloc.min_tokens)
            kind_budgets[alloc.kind] = scaled

    # Phase 2: Pack within each kind's allocation
    kind_results: Dict[str, Dict[str, Any]] = {}
    total_surplus = 0

    for alloc in allocations:
        kind_items = kind_groups.get(alloc.kind, [])
        kind_budget = kind_budgets.get(alloc.kind, 0)

        if not kind_items or kind_budget <= 0:
            kind_results[alloc.kind] = {"selected": [], "dropped": list(kind_items), "used": 0}
            total_surplus += kind_budget
            continue

        result = pack(kind_items, Budget(max_tokens=kind_budget), **pack_kwargs)
        kind_results[alloc.kind] = {
            "selected": list(result.selected),
            "dropped": list(result.dropped),
            "used": result.total_tokens,
        }

        surplus = kind_budget - result.total_tokens
        if surplus > 0:
            total_surplus += surplus

    # Phase 3: Redistribute surplus to kinds that need more space
    if total_surplus > 0:
        sorted_allocs = sorted(allocations, key=lambda a: a.priority, reverse=True)

        for alloc in sorted_allocs:
            if total_surplus <= 0:
                break

            result = kind_results.get(alloc.kind)
            if not result or not result["dropped"]:
                continue

            max_extra = (
                alloc.max_tokens - result["used"] if alloc.max_tokens is not None else total_surplus
            )
            if max_extra <= 0:
                continue

            extra_budget = min(total_surplus, max_extra)
            extra_pack = pack(result["dropped"], Budget(max_tokens=extra_budget), **pack_kwargs)

            result["selected"].extend(extra_pack.selected)
            result["dropped"] = list(extra_pack.dropped)
            result["used"] += extra_pack.total_tokens
            total_surplus -= extra_pack.total_tokens

    # Phase 4: Pack uncategorized items into remaining budget
    used_so_far = sum(r["used"] for r in kind_results.values())
    remaining_budget = effective_budget - used_so_far

    if uncategorized and remaining_budget > 0:
        uncat_result = pack(uncategorized, Budget(max_tokens=remaining_budget), **pack_kwargs)
        uncat_selected = list(uncat_result.selected)
        uncat_dropped = list(uncat_result.dropped)
    else:
        uncat_selected = []
        uncat_dropped = list(uncategorized)

    # Compose final result
    all_selected: List[ContextItem] = []
    all_dropped: List[ContextItem] = []
    alloc_result: Dict[str, KindResult] = {}

    for alloc in allocations:
        result = kind_results[alloc.kind]
        all_selected.extend(result["selected"])
        all_dropped.extend(result["dropped"])
        alloc_result[alloc.kind] = KindResult(
            kind=alloc.kind,
            budget_allocated=kind_budgets.get(alloc.kind, 0),
            budget_used=result["used"],
            item_count=len(result["selected"]),
            surplus=max(0, kind_budgets.get(alloc.kind, 0) - result["used"]),
        )

    all_selected.extend(uncat_selected)
    all_dropped.extend(uncat_dropped)

    if uncat_selected or uncat_dropped:
        uncat_tokens = sum(i.tokens or 0 for i in uncat_selected)
        alloc_result["_uncategorized"] = KindResult(
            kind="_uncategorized",
            budget_allocated=remaining_budget,
            budget_used=uncat_tokens,
            item_count=len(uncat_selected),
            surplus=max(0, remaining_budget - uncat_tokens),
        )

    total_tokens = sum(i.tokens or 0 for i in all_selected)

    # Compute allocation efficiency
    efficiency_sum = 0.0
    efficiency_count = 0
    for alloc in allocations:
        if alloc.target_ratio is not None and total_tokens > 0:
            actual_ratio = (alloc_result[alloc.kind].budget_used) / total_tokens
            diff = abs(actual_ratio - alloc.target_ratio)
            if alloc.target_ratio > 0:
                efficiency_sum += 1 - min(diff / alloc.target_ratio, 1)
            else:
                efficiency_sum += 1.0  # perfect efficiency if no target
            efficiency_count += 1

    return AllocatedPack(
        budget=budget,
        selected=all_selected,
        dropped=all_dropped,
        total_tokens=total_tokens,
        stats={
            "kindCount": len(allocations),
            "remainingTokens": max(0, effective_budget - total_tokens),
        },
        allocations=alloc_result,
        allocation_efficiency=round(efficiency_sum / efficiency_count, 3)
        if efficiency_count > 0
        else 1.0,
    )


def _extract_async_kwargs(options: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract keyword arguments compatible with pack_async from options dict."""
    if not options:
        return {}
    kwargs: Dict[str, Any] = {}
    if "weights" in options:
        kwargs["weights"] = options["weights"]
    if "redundancy_config" in options:
        kwargs["redundancy_config"] = options["redundancy_config"]
    if "provider" in options:
        kwargs["provider"] = options["provider"]
    if "allow_compression" in options:
        kwargs["allow_compression"] = options["allow_compression"]
    return kwargs


async def pack_with_allocation_async(
    items: List[ContextItem],
    budget: Budget,
    allocations: List[KindAllocation],
    options: Optional[Dict[str, Any]] = None,
) -> AllocatedPack:
    """Async version of pack_with_allocation that uses pack_async internally.

    Supports asynchronous redundancy elimination via pack_async.
    See pack_with_allocation for full documentation.

    Args:
        items: Context items to pack (should have `kind` set)
        budget: Total token budget
        allocations: Per-kind budget constraints
        options: Standard pack options

    Returns:
        AllocatedPack with per-kind breakdown
    """
    details = []
    for i, alloc in enumerate(allocations):
        kind = alloc.kind if hasattr(alloc, "kind") else alloc.get("kind", "")
        if not kind:
            details.append(
                {
                    "path": f"allocations[{i}].kind",
                    "message": "kind must be a non-empty string",
                }
            )
        ratio = (
            alloc.target_ratio
            if hasattr(alloc, "target_ratio")
            else alloc.get("target_ratio", None)
        )
        if ratio is not None and not (0 <= ratio <= 1):
            details.append(
                {
                    "path": f"allocations[{i}].target_ratio",
                    "message": "target_ratio must be between 0 and 1",
                }
            )
    if details:
        raise ValidationError("Invalid allocation config", details=details)

    async_kwargs = _extract_async_kwargs(options)
    effective_budget = budget.max_tokens - (budget.reserve_tokens or 0)

    # Group items by kind
    kind_groups: Dict[str, List[ContextItem]] = {}
    uncategorized: List[ContextItem] = []
    alloc_kinds = {a.kind for a in allocations}

    for item in items:
        kind = item.kind or "_uncategorized"
        if kind in alloc_kinds:
            kind_groups.setdefault(kind, []).append(item)
        else:
            uncategorized.append(item)

    # Phase 1: Compute initial allocation per kind
    kind_budgets: Dict[str, int] = {}
    allocated_total = 0

    for alloc in allocations:
        tokens = 0
        if alloc.target_ratio is not None:
            tokens = int(effective_budget * alloc.target_ratio)
        if alloc.min_tokens is not None:
            tokens = max(tokens, alloc.min_tokens)
        if alloc.max_tokens is not None:
            tokens = min(tokens, alloc.max_tokens)
        kind_budgets[alloc.kind] = tokens
        allocated_total += tokens

    # Scale if over-allocated
    if allocated_total > effective_budget:
        scale = effective_budget / allocated_total
        for alloc in allocations:
            scaled = int(kind_budgets[alloc.kind] * scale)
            if alloc.min_tokens is not None:
                scaled = max(scaled, alloc.min_tokens)
            kind_budgets[alloc.kind] = scaled

    # Phase 2: Pack within each kind's allocation
    kind_results: Dict[str, Dict[str, Any]] = {}
    total_surplus = 0

    for alloc in allocations:
        kind_items = kind_groups.get(alloc.kind, [])
        kind_budget = kind_budgets.get(alloc.kind, 0)

        if not kind_items or kind_budget <= 0:
            kind_results[alloc.kind] = {"selected": [], "dropped": list(kind_items), "used": 0}
            total_surplus += kind_budget
            continue

        result = await pack_async(kind_items, Budget(max_tokens=kind_budget), **async_kwargs)
        kind_results[alloc.kind] = {
            "selected": list(result.selected),
            "dropped": list(result.dropped),
            "used": result.total_tokens,
        }

        surplus = kind_budget - result.total_tokens
        if surplus > 0:
            total_surplus += surplus

    # Phase 3: Redistribute surplus to kinds that need more space
    if total_surplus > 0:
        sorted_allocs = sorted(allocations, key=lambda a: a.priority, reverse=True)

        for alloc in sorted_allocs:
            if total_surplus <= 0:
                break

            result = kind_results.get(alloc.kind)
            if not result or not result["dropped"]:
                continue

            max_extra = (
                alloc.max_tokens - result["used"] if alloc.max_tokens is not None else total_surplus
            )
            if max_extra <= 0:
                continue

            extra_budget = min(total_surplus, max_extra)
            extra_pack = await pack_async(
                result["dropped"], Budget(max_tokens=extra_budget), **async_kwargs
            )

            result["selected"].extend(extra_pack.selected)
            result["dropped"] = list(extra_pack.dropped)
            result["used"] += extra_pack.total_tokens
            total_surplus -= extra_pack.total_tokens

    # Phase 4: Pack uncategorized items into remaining budget
    used_so_far = sum(r["used"] for r in kind_results.values())
    remaining_budget = effective_budget - used_so_far

    if uncategorized and remaining_budget > 0:
        uncat_result = await pack_async(
            uncategorized, Budget(max_tokens=remaining_budget), **async_kwargs
        )
        uncat_selected = list(uncat_result.selected)
        uncat_dropped = list(uncat_result.dropped)
    else:
        uncat_selected = []
        uncat_dropped = list(uncategorized)

    # Compose final result
    all_selected: List[ContextItem] = []
    all_dropped: List[ContextItem] = []
    alloc_result: Dict[str, KindResult] = {}

    for alloc in allocations:
        result = kind_results[alloc.kind]
        all_selected.extend(result["selected"])
        all_dropped.extend(result["dropped"])
        alloc_result[alloc.kind] = KindResult(
            kind=alloc.kind,
            budget_allocated=kind_budgets.get(alloc.kind, 0),
            budget_used=result["used"],
            item_count=len(result["selected"]),
            surplus=max(0, kind_budgets.get(alloc.kind, 0) - result["used"]),
        )

    all_selected.extend(uncat_selected)
    all_dropped.extend(uncat_dropped)

    if uncat_selected or uncat_dropped:
        uncat_tokens = sum(i.tokens or 0 for i in uncat_selected)
        alloc_result["_uncategorized"] = KindResult(
            kind="_uncategorized",
            budget_allocated=remaining_budget,
            budget_used=uncat_tokens,
            item_count=len(uncat_selected),
            surplus=max(0, remaining_budget - uncat_tokens),
        )

    total_tokens = sum(i.tokens or 0 for i in all_selected)

    # Compute allocation efficiency
    efficiency_sum = 0.0
    efficiency_count = 0
    for alloc in allocations:
        if alloc.target_ratio is not None and total_tokens > 0:
            actual_ratio = (alloc_result[alloc.kind].budget_used) / total_tokens
            diff = abs(actual_ratio - alloc.target_ratio)
            if alloc.target_ratio > 0:
                efficiency_sum += 1 - min(diff / alloc.target_ratio, 1)
            else:
                efficiency_sum += 1.0
            efficiency_count += 1

    return AllocatedPack(
        budget=budget,
        selected=all_selected,
        dropped=all_dropped,
        total_tokens=total_tokens,
        stats={
            "kindCount": len(allocations),
            "remainingTokens": max(0, effective_budget - total_tokens),
        },
        allocations=alloc_result,
        allocation_efficiency=round(efficiency_sum / efficiency_count, 3)
        if efficiency_count > 0
        else 1.0,
    )
