"""Context Compiler — declarative context programs compiled into optimized layouts.

Like a C compiler targets x86 vs ARM, this targets Claude vs GPT vs Gemini.
A ContextProgram declares what the context should contain (slots, constraints,
priorities) without specifying how to arrange it. The compiler then optimizes
the layout for a target model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Set, Tuple

from .core import Budget, ContextItem, estimate_tokens
from .quality import ContextQuality, analyze_context

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class Slot:
    """A slot declares a category of content the context needs."""

    name: str
    kind: str
    required: bool = False
    position: Literal["first", "last", "any"] = "any"
    max_tokens: Optional[int] = None
    min_tokens: Optional[int] = None
    fill_remaining: bool = False
    strategy: Literal["priority", "recency", "relevance"] = "priority"
    deduplicate: bool = False
    max_staleness: Optional[float] = None


@dataclass
class Constraint:
    """A constraint on the compiled context."""

    type: Literal[
        "no-contradiction",
        "freshness",
        "coverage",
        "budget-utilization",
        "max-redundancy",
    ]
    slots: Optional[List[str]] = None
    threshold: Optional[float] = None


CompileTarget = Literal["claude", "gpt4", "gemini", "generic"]


@dataclass
class CompileDiagnostic:
    """A diagnostic emitted during compilation."""

    level: Literal["info", "warning", "error"]
    message: str
    slot: Optional[str] = None
    constraint: Optional[str] = None


@dataclass
class OptimizationPass:
    """Record of an optimization pass applied."""

    name: str
    description: str
    items_reordered: int
    tokens_affected: int


@dataclass
class SlotStats:
    """Per-slot breakdown in compile result."""

    item_count: int
    tokens_used: int
    satisfied: bool


@dataclass
class CompileResult:
    """Result of compiling a context program."""

    items: List[ContextItem]
    dropped: List[ContextItem]
    total_tokens: int
    diagnostics: List[CompileDiagnostic]
    optimizations: List[OptimizationPass]
    target: CompileTarget
    slots: Dict[str, SlotStats]
    quality: ContextQuality


@dataclass
class ContextProgram:
    """A declarative context program."""

    slots: List[Slot] = field(default_factory=list)
    constraints: List[Constraint] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Program builder
# ---------------------------------------------------------------------------


class ContextProgramBuilder:
    """Fluent builder for declaring context programs.

    Example::

        program = (
            context_program()
            .declare("system", kind="system", required=True, position="first")
            .declare("code", kind="code", strategy="relevance", deduplicate=True)
            .constraint("coverage")
            .constraint("max-redundancy", threshold=0.3)
            .build()
        )
    """

    def __init__(self) -> None:
        self._slots: List[Slot] = []
        self._constraints: List[Constraint] = []

    def declare(self, name: str, **kwargs) -> "ContextProgramBuilder":
        """Declare a slot in the program."""
        self._slots.append(Slot(name=name, **kwargs))
        return self

    def constraint(
        self,
        type: str,
        slots: Optional[List[str]] = None,
        threshold: Optional[float] = None,
    ) -> "ContextProgramBuilder":
        """Add a constraint to the program."""
        self._constraints.append(
            Constraint(type=type, slots=slots, threshold=threshold)  # type: ignore[arg-type]
        )
        return self

    def build(self) -> ContextProgram:
        """Build an immutable ContextProgram."""
        return ContextProgram(
            slots=list(self._slots),
            constraints=list(self._constraints),
        )


def context_program() -> ContextProgramBuilder:
    """Create a new context program builder."""
    return ContextProgramBuilder()


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

_NEGATION_WORDS = frozenset(
    [
        "not",
        "never",
        "don't",
        "dont",
        "avoid",
        "shouldn't",
        "shouldnt",
        "won't",
        "wont",
        "cannot",
        "can't",
        "cant",
        "no",
    ]
)


def _get_words(text: str) -> List[str]:
    return [w for w in text.lower().split() if w]


def _word_set(words: List[str]) -> Set[str]:
    return set(words)


def _has_negation(words: List[str]) -> bool:
    return any(w in _NEGATION_WORDS for w in words)


def _word_overlap(a: Set[str], b: Set[str]) -> float:
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def _items_for_slots(
    items: List[ContextItem],
    slots: List[Slot],
    constraint_slots: Optional[List[str]] = None,
) -> List[ContextItem]:
    target_slots = [s for s in slots if s.name in constraint_slots] if constraint_slots else slots
    slot_kinds = {s.kind for s in target_slots}
    return [item for item in items if item.kind and item.kind in slot_kinds]


def _validate_no_contradiction(
    items: List[ContextItem], constraint: Constraint, slots: List[Slot]
) -> List[CompileDiagnostic]:
    diagnostics: List[CompileDiagnostic] = []
    relevant = _items_for_slots(items, slots, constraint.slots)
    for i in range(len(relevant)):
        for j in range(i + 1, len(relevant)):
            words_a = _get_words(relevant[i].content)
            words_b = _get_words(relevant[j].content)
            overlap = _word_overlap(_word_set(words_a), _word_set(words_b))
            if overlap > 0.6:
                neg_a = _has_negation(words_a)
                neg_b = _has_negation(words_b)
                if neg_a != neg_b:
                    diagnostics.append(
                        CompileDiagnostic(
                            level="warning",
                            constraint="no-contradiction",
                            message=(
                                f'Potential contradiction between items "{relevant[i].id}" '
                                f'and "{relevant[j].id}" '
                                f"(overlap: {round(overlap * 100)}%, negation mismatch)"
                            ),
                        )
                    )
    return diagnostics


def _validate_freshness(
    items: List[ContextItem], constraint: Constraint, slots: List[Slot]
) -> List[CompileDiagnostic]:
    diagnostics: List[CompileDiagnostic] = []
    threshold = constraint.threshold if constraint.threshold is not None else 5.0
    relevant = _items_for_slots(items, slots, constraint.slots)
    for item in relevant:
        recency = item.recency or 0
        if recency < threshold:
            diagnostics.append(
                CompileDiagnostic(
                    level="warning",
                    constraint="freshness",
                    message=f'Item "{item.id}" has low recency ({recency}) below threshold ({threshold})',
                )
            )
    return diagnostics


def _validate_coverage(
    items: List[ContextItem], _constraint: Constraint, slots: List[Slot]
) -> List[CompileDiagnostic]:
    diagnostics: List[CompileDiagnostic] = []
    item_kinds = {item.kind for item in items if item.kind}
    for slot in slots:
        if slot.required and slot.kind not in item_kinds:
            diagnostics.append(
                CompileDiagnostic(
                    level="error",
                    slot=slot.name,
                    constraint="coverage",
                    message=f'Required slot "{slot.name}" (kind: "{slot.kind}") has no matching items',
                )
            )
    return diagnostics


def _validate_budget_utilization(
    items: List[ContextItem],
    constraint: Constraint,
    _slots: List[Slot],
    budget: Budget,
) -> List[CompileDiagnostic]:
    diagnostics: List[CompileDiagnostic] = []
    total_tokens = sum(item.tokens or estimate_tokens(item.content) for item in items)
    max_tokens = budget.max_tokens - (budget.reserve_tokens or 0)
    utilization = total_tokens / max_tokens if max_tokens > 0 else 0
    threshold = constraint.threshold if constraint.threshold is not None else 0.7

    if utilization < threshold:
        diagnostics.append(
            CompileDiagnostic(
                level="warning",
                constraint="budget-utilization",
                message=(
                    f"Budget utilization ({round(utilization * 100)}%) "
                    f"is below threshold ({round(threshold * 100)}%)"
                ),
            )
        )
    if utilization > 0.95:
        diagnostics.append(
            CompileDiagnostic(
                level="info",
                constraint="budget-utilization",
                message=(
                    f"Budget utilization ({round(utilization * 100)}%) "
                    f"is very high -- risk of exceeding budget"
                ),
            )
        )
    return diagnostics


def _validate_max_redundancy(
    items: List[ContextItem], constraint: Constraint, slots: List[Slot]
) -> List[CompileDiagnostic]:
    diagnostics: List[CompileDiagnostic] = []
    threshold = constraint.threshold if constraint.threshold is not None else 0.5
    relevant = _items_for_slots(items, slots, constraint.slots)
    word_sets = [set(w for w in item.content.lower().split() if len(w) > 2) for item in relevant]
    for i in range(len(word_sets)):
        for j in range(i + 1, len(word_sets)):
            overlap = _word_overlap(word_sets[i], word_sets[j])
            if overlap > threshold:
                diagnostics.append(
                    CompileDiagnostic(
                        level="warning",
                        constraint="max-redundancy",
                        message=(
                            f'Items "{relevant[i].id}" and "{relevant[j].id}" have high overlap '
                            f"({round(overlap * 100)}%) exceeding threshold ({round(threshold * 100)}%)"
                        ),
                    )
                )
    return diagnostics


def validate_constraints(
    items: List[ContextItem],
    constraints: List[Constraint],
    slots: List[Slot],
    budget: Budget,
) -> List[CompileDiagnostic]:
    """Validate a set of packed items against declared constraints."""
    diagnostics: List[CompileDiagnostic] = []
    for constraint in constraints:
        if constraint.type == "no-contradiction":
            diagnostics.extend(_validate_no_contradiction(items, constraint, slots))
        elif constraint.type == "freshness":
            diagnostics.extend(_validate_freshness(items, constraint, slots))
        elif constraint.type == "coverage":
            diagnostics.extend(_validate_coverage(items, constraint, slots))
        elif constraint.type == "budget-utilization":
            diagnostics.extend(_validate_budget_utilization(items, constraint, slots, budget))
        elif constraint.type == "max-redundancy":
            diagnostics.extend(_validate_max_redundancy(items, constraint, slots))
    return diagnostics


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------


def _jaccard_similarity(a: Set[str], b: Set[str]) -> float:
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def _get_slot_for_item(item: ContextItem, slots: List[Slot]) -> Optional[Slot]:
    for s in slots:
        if s.kind == item.kind:
            return s
    return None


def _position_aware_placement(
    items: List[ContextItem], target: CompileTarget, slots: List[Slot]
) -> Tuple[List[ContextItem], OptimizationPass]:
    first_items: List[ContextItem] = []
    last_items: List[ContextItem] = []
    any_items: List[ContextItem] = []

    for item in items:
        slot = _get_slot_for_item(item, slots)
        position = slot.position if slot else "any"
        if position == "first":
            first_items.append(item)
        elif position == "last":
            last_items.append(item)
        else:
            any_items.append(item)

    if target == "claude":
        sorted_any = sorted(any_items, key=lambda i: i.priority or 0, reverse=True)
        half = math.ceil(len(sorted_any) / 2)
        start = sorted_any[:half]
        end = list(reversed(sorted_any[half:]))
        any_items = start + end
    elif target == "gpt4":
        any_items.sort(key=lambda i: i.priority or 0, reverse=True)
    elif target == "gemini":
        any_items.sort(key=lambda i: i.kind or "")

    result = first_items + any_items + last_items
    total_tokens = sum(item.tokens or estimate_tokens(item.content) for item in result)

    return result, OptimizationPass(
        name="position-aware-placement",
        description=f"Ordered items by position constraints for {target} target",
        items_reordered=len(result),
        tokens_affected=total_tokens,
    )


def _cache_prefix_ordering(
    items: List[ContextItem], _target: CompileTarget, slots: List[Slot]
) -> Tuple[List[ContextItem], OptimizationPass]:
    last_start = len(items)
    for idx, item in enumerate(items):
        slot = _get_slot_for_item(item, slots)
        if slot and slot.position == "last":
            last_start = idx
            break

    prefix = items[:last_start]
    suffix = items[last_start:]

    first_prefix = [
        item
        for item in prefix
        if (_get_slot_for_item(item, slots) or Slot(name="", kind="")).position == "first"
    ]
    any_prefix = [
        item
        for item in prefix
        if (_get_slot_for_item(item, slots) or Slot(name="", kind="")).position != "first"
    ]

    first_prefix.sort(key=lambda i: i.id)

    result = first_prefix + any_prefix + suffix
    tokens_affected = sum(item.tokens or estimate_tokens(item.content) for item in first_prefix)

    return result, OptimizationPass(
        name="cache-prefix-ordering",
        description="Sorted first-position items by ID for deterministic cache-friendly ordering",
        items_reordered=len(first_prefix),
        tokens_affected=tokens_affected,
    )


def _deduplication(
    items: List[ContextItem], _target: CompileTarget, slots: List[Slot]
) -> Tuple[List[ContextItem], OptimizationPass]:
    dedup_kinds = {s.kind for s in slots if s.deduplicate}

    if not dedup_kinds:
        return items, OptimizationPass(
            name="deduplication",
            description="No slots configured for deduplication",
            items_reordered=0,
            tokens_affected=0,
        )

    dedup_items = [i for i in items if i.kind and i.kind in dedup_kinds]
    other_items = [i for i in items if not (i.kind and i.kind in dedup_kinds)]

    kept: List[ContextItem] = []
    kept_word_sets: List[Set[str]] = []
    removed_tokens: List[int] = []

    for item in dedup_items:
        ws = set(w for w in item.content.lower().split() if len(w) > 2)
        is_dup = False
        for existing_ws in kept_word_sets:
            if _jaccard_similarity(ws, existing_ws) > 0.8:
                is_dup = True
                removed_tokens.append(item.tokens or estimate_tokens(item.content))
                break
        if not is_dup:
            kept.append(item)
            kept_word_sets.append(ws)

    kept_ids = {i.id for i in kept}
    other_ids = {i.id for i in other_items}
    result = [i for i in items if i.id in kept_ids or i.id in other_ids]

    total_removed = sum(removed_tokens)

    return result, OptimizationPass(
        name="deduplication",
        description=f"Removed {len(removed_tokens)} duplicate items (>0.8 Jaccard overlap)",
        items_reordered=len(removed_tokens),
        tokens_affected=total_removed,
    )


def _staleness_pruning(
    items: List[ContextItem], _target: CompileTarget, slots: List[Slot]
) -> Tuple[List[ContextItem], OptimizationPass]:
    staleness_map: Dict[str, float] = {}
    for slot in slots:
        if slot.max_staleness is not None:
            staleness_map[slot.kind] = slot.max_staleness

    if not staleness_map:
        return items, OptimizationPass(
            name="staleness-pruning",
            description="No slots configured with max_staleness",
            items_reordered=0,
            tokens_affected=0,
        )

    result: List[ContextItem] = []
    removed_count = 0
    removed_tokens = 0

    for item in items:
        threshold = staleness_map.get(item.kind or "", None)
        if threshold is not None:
            recency = item.recency or 0
            if recency < threshold:
                removed_count += 1
                removed_tokens += item.tokens or estimate_tokens(item.content)
                continue
        result.append(item)

    return result, OptimizationPass(
        name="staleness-pruning",
        description=f"Removed {removed_count} stale items below recency threshold",
        items_reordered=removed_count,
        tokens_affected=removed_tokens,
    )


def optimize_for_target(
    items: List[ContextItem],
    target: CompileTarget,
    slots: List[Slot],
) -> Tuple[List[ContextItem], List[OptimizationPass]]:
    """Apply per-model optimization passes to a set of items."""
    passes: List[OptimizationPass] = []
    current = list(items)

    current, p = _staleness_pruning(current, target, slots)
    passes.append(p)

    current, p = _deduplication(current, target, slots)
    passes.append(p)

    current, p = _position_aware_placement(current, target, slots)
    passes.append(p)

    current, p = _cache_prefix_ordering(current, target, slots)
    passes.append(p)

    return current, passes


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


def _get_item_tokens(item: ContextItem) -> int:
    return item.tokens or estimate_tokens(item.content)


def _select_by_strategy(
    items: List[ContextItem],
    strategy: str,
) -> List[ContextItem]:
    if strategy == "priority":
        return sorted(items, key=lambda i: i.priority or 0, reverse=True)
    elif strategy == "recency":
        return sorted(items, key=lambda i: i.recency or 0, reverse=True)
    elif strategy == "relevance":
        return sorted(items, key=lambda i: i.score or 0, reverse=True)
    return list(items)


def _categorize_items(
    items: List[ContextItem], slots: List[Slot]
) -> Tuple[Dict[str, List[ContextItem]], List[ContextItem]]:
    slot_items: Dict[str, List[ContextItem]] = {s.name: [] for s in slots}
    matched_ids: Set[str] = set()

    for item in items:
        for slot in slots:
            if item.kind == slot.kind:
                slot_items[slot.name].append(item)
                matched_ids.add(item.id)
                break

    uncategorized = [item for item in items if item.id not in matched_ids]
    return slot_items, uncategorized


class ContextCompiler:
    """Compiler that takes a declarative ContextProgram and optimizes layout."""

    def compile(
        self,
        program: ContextProgram,
        target: CompileTarget,
        items: List[ContextItem],
        budget: Budget,
    ) -> CompileResult:
        """Compile a context program into an optimized layout.

        Args:
            program: The declarative context program.
            target: Target model for optimization.
            items: Available context items.
            budget: Token budget.

        Returns:
            CompileResult with optimized items, diagnostics, and metrics.
        """
        max_tokens = budget.max_tokens - (budget.reserve_tokens or 0)
        slot_items, uncategorized = _categorize_items(items, program.slots)

        selected: List[ContextItem] = []
        dropped: List[ContextItem] = []
        slot_stats: Dict[str, SlotStats] = {}
        used_tokens = 0

        # First pass: non-fillRemaining slots
        for slot in program.slots:
            if slot.fill_remaining:
                continue

            candidates = slot_items.get(slot.name, [])
            sorted_candidates = _select_by_strategy(candidates, slot.strategy)

            slot_max = slot.max_tokens if slot.max_tokens is not None else max_tokens
            slot_tokens = 0
            slot_selected: List[ContextItem] = []

            for item in sorted_candidates:
                item_tokens = _get_item_tokens(item)
                if (
                    used_tokens + slot_tokens + item_tokens <= max_tokens
                    and slot_tokens + item_tokens <= slot_max
                ):
                    slot_selected.append(item)
                    slot_tokens += item_tokens
                else:
                    dropped.append(item)

            min_satisfied = slot_tokens >= slot.min_tokens if slot.min_tokens else True
            has_coverage = not slot.required or len(slot_selected) > 0

            slot_stats[slot.name] = SlotStats(
                item_count=len(slot_selected),
                tokens_used=slot_tokens,
                satisfied=min_satisfied and has_coverage,
            )
            selected.extend(slot_selected)
            used_tokens += slot_tokens

        # Second pass: fillRemaining slots.
        # Track ids already chosen so a shared uncategorized item cannot be
        # selected by more than one fill_remaining slot (which would duplicate
        # it in result.items and double-count its tokens). Seed with the ids
        # selected by the first pass.
        claimed: set[str] = {i.id for i in selected}
        for slot in program.slots:
            if not slot.fill_remaining:
                continue

            candidates = slot_items.get(slot.name, []) + uncategorized
            sorted_candidates = _select_by_strategy(candidates, slot.strategy)

            remaining_budget = max_tokens - used_tokens
            slot_max = (
                min(slot.max_tokens, remaining_budget)
                if slot.max_tokens is not None
                else remaining_budget
            )
            slot_tokens = 0
            slot_selected: List[ContextItem] = []

            for item in sorted_candidates:
                if item.id in claimed:
                    continue
                item_tokens = _get_item_tokens(item)
                if (
                    slot_tokens + item_tokens <= slot_max
                    and used_tokens + slot_tokens + item_tokens <= max_tokens
                ):
                    slot_selected.append(item)
                    slot_tokens += item_tokens
                    claimed.add(item.id)
                else:
                    dropped.append(item)

            min_satisfied = slot_tokens >= slot.min_tokens if slot.min_tokens else True
            has_coverage = not slot.required or len(slot_selected) > 0

            slot_stats[slot.name] = SlotStats(
                item_count=len(slot_selected),
                tokens_used=slot_tokens,
                satisfied=min_satisfied and has_coverage,
            )
            selected.extend(slot_selected)
            used_tokens += slot_tokens

        # Drop remaining uncategorized items
        selected_ids = {i.id for i in selected}
        for item in uncategorized:
            if item.id not in selected_ids:
                dropped.append(item)

        # Optimize for target
        optimized_items, passes = optimize_for_target(selected, target, program.slots)

        # Validate constraints
        diagnostics = validate_constraints(
            optimized_items, program.constraints, program.slots, budget
        )

        # Add diagnostics for unsatisfied slots
        for slot_name, stats in slot_stats.items():
            if not stats.satisfied:
                slot = next((s for s in program.slots if s.name == slot_name), None)
                if slot and slot.required:
                    diagnostics.append(
                        CompileDiagnostic(
                            level="error",
                            slot=slot_name,
                            message=(
                                f'Required slot "{slot_name}" is not satisfied '
                                f"({stats.item_count} items, {stats.tokens_used} tokens)"
                            ),
                        )
                    )

        # Quality metrics
        quality = analyze_context(optimized_items)

        # Final token count
        total_tokens = sum(_get_item_tokens(item) for item in optimized_items)

        return CompileResult(
            items=optimized_items,
            dropped=dropped,
            total_tokens=total_tokens,
            diagnostics=diagnostics,
            optimizations=passes,
            target=target,
            slots=slot_stats,
            quality=quality,
        )


def create_context_compiler() -> ContextCompiler:
    """Create a context compiler instance."""
    return ContextCompiler()
