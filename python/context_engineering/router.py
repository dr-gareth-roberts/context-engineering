"""Model Router — routes to the cheapest model that can handle the complexity.

Analyzes context complexity across multiple dimensions and selects
an appropriate model tier, with adaptive learning from outcome feedback.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from .core import Budget, ContextItem, estimate_tokens
from .quality import analyze_context

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class ModelTier:
    """Definition of a model tier with pricing and capabilities."""

    model: str
    max_complexity: float
    cost_per_1k_input: float
    cost_per_1k_output: float
    max_tokens: int
    capabilities: list[str] | None = None


@dataclass
class ComplexityBreakdown:
    """Multi-dimensional complexity analysis."""

    overall: float
    diversity: float
    density: float
    dependency_depth: float
    tool_call_count: float
    multilinguality: float
    average_item_length: float


@dataclass
class RoutingDecision:
    """Result of a routing decision."""

    model: str
    complexity: float
    complexity_breakdown: ComplexityBreakdown
    reasoning: str
    estimated_cost_input: float
    estimated_cost_output: float
    alternative_model: str | None = None
    alternative_cost_delta: float | None = None


@dataclass
class RouterInsights:
    """Aggregated routing analytics."""

    total_decisions: int
    model_stats: dict[str, dict[str, float]]  # model -> {uses, avg_quality, avg_complexity}
    potential_savings: float


# ---------------------------------------------------------------------------
# Complexity analysis
# ---------------------------------------------------------------------------

DEFAULT_COMPLEXITY_WEIGHTS: dict[str, float] = {
    "diversity": 0.20,
    "density": 0.15,
    "dependency_depth": 0.25,
    "tool_call_count": 0.15,
    "multilinguality": 0.10,
    "average_item_length": 0.15,
}


def _compute_dependency_depth(items: list[ContextItem]) -> int:
    """Walk dependsOn chains to find the maximum depth."""
    id_map = {item.id: item for item in items}
    cache: dict[str, int] = {}

    def depth(item_id: str, visited: set[str] | None = None) -> int:
        if item_id in cache:
            return cache[item_id]
        if visited is None:
            visited = set()
        if item_id in visited or item_id not in id_map:
            return 0
        visited.add(item_id)
        item = id_map[item_id]
        if not item.depends_on:
            cache[item_id] = 0
            return 0
        max_dep = 0
        for dep_id in item.depends_on:
            max_dep = max(max_dep, depth(dep_id, visited) + 1)
        cache[item_id] = max_dep
        return max_dep

    if not items:
        return 0
    return max(depth(item.id) for item in items)


def _detect_scripts(text: str) -> set[str]:
    """Detect distinct Unicode script categories in text."""
    scripts: set[str] = set()
    for char in text:
        if char.isalpha():
            # Use the script block name for grouping.
            try:
                name = unicodedata.name(char, "")
                # Extract script from character name (e.g., "LATIN SMALL LETTER A" -> "LATIN").
                parts = name.split()
                if parts:
                    scripts.add(parts[0])
            except ValueError:
                pass
    return scripts


def _count_tool_kinds(items: list[ContextItem]) -> int:
    """Count items with tool-related kinds."""
    tool_kinds = {"tool", "tool_result", "function", "function_call", "tool_call", "action"}
    return sum(1 for item in items if item.kind and item.kind.lower() in tool_kinds)


def analyze_complexity(
    items: list[ContextItem],
    weights: dict[str, float] | None = None,
) -> ComplexityBreakdown:
    """Analyze the complexity of a set of context items.

    Considers diversity, density, dependency depth, tool call count,
    multilinguality, and average item length.

    Args:
        items: Context items to analyze.
        weights: Optional custom weights for each dimension (default uses
                 DEFAULT_COMPLEXITY_WEIGHTS).

    Returns:
        ComplexityBreakdown with per-dimension and overall scores (0-1).
    """
    if not items:
        return ComplexityBreakdown(
            overall=0.0,
            diversity=0.0,
            density=0.0,
            dependency_depth=0.0,
            tool_call_count=0.0,
            multilinguality=0.0,
            average_item_length=0.0,
        )

    w = weights or DEFAULT_COMPLEXITY_WEIGHTS

    # Use analyze_context for diversity and density.
    quality = analyze_context(items)
    diversity = quality.diversity
    density = quality.density

    # Dependency depth — normalized to 0-1 (cap at depth 10).
    raw_depth = _compute_dependency_depth(items)
    dependency_depth = min(raw_depth / 10.0, 1.0)

    # Tool call count — normalized to 0-1 (cap at 20).
    raw_tool_count = _count_tool_kinds(items)
    tool_call_count = min(raw_tool_count / 20.0, 1.0)

    # Multilinguality — number of distinct scripts normalized (cap at 5).
    all_text = " ".join(item.content for item in items)
    scripts = _detect_scripts(all_text)
    multilinguality = min(max(len(scripts) - 1, 0) / 4.0, 1.0)

    # Average item length — normalized by token count (cap at 2000 tokens).
    total_tokens = sum(item.tokens or estimate_tokens(item.content) for item in items)
    avg_tokens = total_tokens / len(items)
    average_item_length = min(avg_tokens / 2000.0, 1.0)

    # Weighted overall score.
    overall = (
        diversity * w.get("diversity", 0.2)
        + density * w.get("density", 0.15)
        + dependency_depth * w.get("dependency_depth", 0.25)
        + tool_call_count * w.get("tool_call_count", 0.15)
        + multilinguality * w.get("multilinguality", 0.10)
        + average_item_length * w.get("average_item_length", 0.15)
    )

    return ComplexityBreakdown(
        overall=round(min(overall, 1.0), 4),
        diversity=round(diversity, 4),
        density=round(density, 4),
        dependency_depth=round(dependency_depth, 4),
        tool_call_count=round(tool_call_count, 4),
        multilinguality=round(multilinguality, 4),
        average_item_length=round(average_item_length, 4),
    )


# ---------------------------------------------------------------------------
# ContextRouter
# ---------------------------------------------------------------------------


class ContextRouter:
    """Routes context to the cheapest model that handles its complexity."""

    def __init__(
        self,
        models: list[ModelTier],
        default_model: str | None = None,
        complexity_weights: dict[str, float] | None = None,
    ) -> None:
        # Sort by max_complexity ascending for routing.
        self._models = sorted(models, key=lambda m: m.max_complexity)
        self._default_model = default_model or (self._models[-1].model if self._models else "")
        self._complexity_weights = complexity_weights

    def route(
        self,
        items: list[ContextItem],
        budget: Budget,
        required_capabilities: list[str] | None = None,
    ) -> RoutingDecision:
        """Route to the cheapest model that can handle the context complexity.

        Args:
            items: Context items to analyze.
            budget: Token budget for the request.
            required_capabilities: Capabilities the model must support.

        Returns:
            RoutingDecision with model selection and cost estimates.
        """
        breakdown = analyze_complexity(items, self._complexity_weights)
        total_tokens = sum(item.tokens or estimate_tokens(item.content) for item in items)
        required_caps = set(required_capabilities or [])

        # Find the cheapest eligible model.
        selected: ModelTier | None = None
        alternative: ModelTier | None = None

        for tier in self._models:
            # Check complexity ceiling.
            if tier.max_complexity < breakdown.overall:
                continue
            # Check token capacity.
            if tier.max_tokens < total_tokens:
                continue
            # Check capabilities.
            tier_caps = set(tier.capabilities or [])
            if required_caps and not required_caps.issubset(tier_caps):
                continue

            if selected is None:
                selected = tier
            elif alternative is None:
                alternative = tier
                break

        # Fallback to default.
        if selected is None:
            selected = self._find_model(self._default_model) or self._models[-1]

        # Cost estimates (assuming 500 output tokens).
        output_tokens = 500
        estimated_cost_input = (total_tokens / 1000) * selected.cost_per_1k_input
        estimated_cost_output = (output_tokens / 1000) * selected.cost_per_1k_output

        alt_model: str | None = None
        alt_cost_delta: float | None = None
        if alternative:
            alt_cost = (total_tokens / 1000) * alternative.cost_per_1k_input + (
                output_tokens / 1000
            ) * alternative.cost_per_1k_output
            current_cost = estimated_cost_input + estimated_cost_output
            alt_model = alternative.model
            alt_cost_delta = round(alt_cost - current_cost, 6)

        reasoning = self._build_reasoning(breakdown, selected, total_tokens, required_caps)

        return RoutingDecision(
            model=selected.model,
            complexity=breakdown.overall,
            complexity_breakdown=breakdown,
            reasoning=reasoning,
            estimated_cost_input=round(estimated_cost_input, 6),
            estimated_cost_output=round(estimated_cost_output, 6),
            alternative_model=alt_model,
            alternative_cost_delta=alt_cost_delta,
        )

    def _find_model(self, name: str) -> ModelTier | None:
        for tier in self._models:
            if tier.model == name:
                return tier
        return None

    def _build_reasoning(
        self,
        breakdown: ComplexityBreakdown,
        selected: ModelTier,
        total_tokens: int,
        required_caps: set[str],
    ) -> str:
        parts = [
            f"Complexity {breakdown.overall:.2f} fits {selected.model} (max {selected.max_complexity:.2f})"
        ]
        if breakdown.dependency_depth > 0.3:
            parts.append(f"deep dependency chain ({breakdown.dependency_depth:.2f})")
        if breakdown.tool_call_count > 0.2:
            parts.append(f"tool-heavy context ({breakdown.tool_call_count:.2f})")
        if required_caps:
            parts.append(f"requires: {', '.join(sorted(required_caps))}")
        return "; ".join(parts)


def create_context_router(
    models: list[ModelTier],
    default_model: str | None = None,
    complexity_weights: dict[str, float] | None = None,
) -> ContextRouter:
    """Factory for context router."""
    return ContextRouter(models, default_model, complexity_weights)


# ---------------------------------------------------------------------------
# AdaptiveRouter — learns from outcomes
# ---------------------------------------------------------------------------


@dataclass
class _OutcomeRecord:
    """Internal record of a routing outcome."""

    model: str
    complexity: float
    quality: float


class AdaptiveRouter(ContextRouter):
    """Router that adjusts complexity thresholds based on outcome feedback."""

    def __init__(
        self,
        models: list[ModelTier],
        default_model: str | None = None,
        complexity_weights: dict[str, float] | None = None,
        min_samples: int = 20,
    ) -> None:
        super().__init__(models, default_model, complexity_weights)
        self._min_samples = min_samples
        self._outcomes: list[_OutcomeRecord] = []

    def report_outcome(self, decision: RoutingDecision, quality: float) -> None:
        """Report the quality of a model output for learning.

        Args:
            decision: The routing decision that was used.
            quality: Quality score (0-1) of the model output.
        """
        self._outcomes.append(
            _OutcomeRecord(
                model=decision.model,
                complexity=decision.complexity,
                quality=quality,
            )
        )

    def get_insights(self) -> RouterInsights:
        """Return routing analytics and potential savings.

        Returns:
            RouterInsights with per-model stats and savings estimate.
        """
        model_records: dict[str, list[_OutcomeRecord]] = {}
        for record in self._outcomes:
            model_records.setdefault(record.model, []).append(record)

        model_stats: dict[str, dict[str, float]] = {}
        for model, records in model_records.items():
            qualities = [r.quality for r in records]
            complexities = [r.complexity for r in records]
            model_stats[model] = {
                "uses": float(len(records)),
                "avg_quality": round(sum(qualities) / len(qualities), 4) if qualities else 0.0,
                "avg_complexity": round(sum(complexities) / len(complexities), 4)
                if complexities
                else 0.0,
            }

        # Estimate potential savings: for high-quality outcomes from expensive
        # models on low-complexity tasks, a cheaper model might have sufficed.
        potential_savings = 0.0
        if len(self._outcomes) >= self._min_samples:
            for record in self._outcomes:
                if record.quality >= 0.8:
                    # Find if a cheaper model could handle this complexity.
                    current = self._find_model(record.model)
                    if current is None:
                        continue
                    for tier in self._models:
                        if tier.model == record.model:
                            break
                        if tier.max_complexity >= record.complexity:
                            # This cheaper model could have handled it.
                            savings = current.cost_per_1k_input - tier.cost_per_1k_input
                            potential_savings += max(0.0, savings)
                            break

        return RouterInsights(
            total_decisions=len(self._outcomes),
            model_stats=model_stats,
            potential_savings=round(potential_savings, 4),
        )


def create_adaptive_router(
    models: list[ModelTier],
    min_samples: int = 20,
    default_model: str | None = None,
    complexity_weights: dict[str, float] | None = None,
) -> AdaptiveRouter:
    """Factory for adaptive router with outcome learning."""
    return AdaptiveRouter(
        models=models,
        default_model=default_model,
        complexity_weights=complexity_weights,
        min_samples=min_samples,
    )
