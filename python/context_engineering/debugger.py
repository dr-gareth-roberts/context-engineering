"""Context Debugger — diagnoses bad model outputs by analyzing context quality.

Inspects a ContextPack for common issues (redundancy, staleness, low diversity,
budget waste, wrong priorities) and produces actionable recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .core import Budget, ContextItem, ContextPack, pack
from .quality import ContextQuality, analyze_context
from .relevance import compute_relevance, normalize_query

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class QualityThresholds:
    """Thresholds for diagnostic checks."""

    min_density: float = 0.3
    min_diversity: float = 0.4
    max_redundancy: float = 0.3
    min_freshness: float = 0.2
    min_utilization: float = 0.5
    max_utilization: float = 0.95


@dataclass
class DiagnosticIssue:
    """A single diagnostic finding."""

    severity: str  # "info" | "warning" | "critical"
    category: str  # "missing-context" | "redundancy" | "stale-context" | "budget-waste" | "wrong-priorities" | "low-diversity"
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class Recommendation:
    """An actionable recommendation to improve context quality."""

    action: str  # "adjust-weights" | "increase-budget" | "add-kind" | "remove-kind" | "enable-compression" | "enable-redundancy-filter"
    description: str
    suggested_change: dict[str, Any] = field(default_factory=dict)
    estimated_impact: str = ""


@dataclass
class DroppedAnalysis:
    """Analysis of items that were dropped during packing."""

    total_dropped: int
    dropped_by_kind: dict[str, int]
    high_priority_dropped: list[ContextItem]
    potentially_relevant: list[ContextItem]


@dataclass
class Diagnosis:
    """Complete diagnostic result for a context pack."""

    overall_health: str  # "good" | "warning" | "critical"
    quality: ContextQuality
    issues: list[DiagnosticIssue]
    recommendations: list[Recommendation]
    dropped_analysis: DroppedAnalysis


@dataclass
class ComparisonResult:
    """Result of comparing two context packs."""

    pack_a_quality: ContextQuality
    pack_b_quality: ContextQuality
    item_diff: dict[str, list[str]]  # only_in_a, only_in_b, shared
    quality_delta: float
    insights: list[str]


# ---------------------------------------------------------------------------
# Analyzers (private helpers)
# ---------------------------------------------------------------------------


def _analyze_redundancy(
    quality: ContextQuality,
    thresholds: QualityThresholds,
    issues: list[DiagnosticIssue],
    recommendations: list[Recommendation],
) -> None:
    """Check for excessive redundancy."""
    if quality.redundancy > thresholds.max_redundancy:
        severity = "critical" if quality.redundancy > thresholds.max_redundancy * 1.5 else "warning"
        issues.append(
            DiagnosticIssue(
                severity=severity,
                category="redundancy",
                message=f"High redundancy ({quality.redundancy:.2f}) exceeds threshold ({thresholds.max_redundancy:.2f})",
                evidence={"redundancy": quality.redundancy, "threshold": thresholds.max_redundancy},
            )
        )
        recommendations.append(
            Recommendation(
                action="enable-redundancy-filter",
                description="Enable redundancy elimination to remove duplicate information",
                suggested_change={"redundancy_threshold": 0.8},
                estimated_impact="Could reduce context size by 10-30% while preserving information",
            )
        )


def _analyze_freshness(
    quality: ContextQuality,
    thresholds: QualityThresholds,
    issues: list[DiagnosticIssue],
    recommendations: list[Recommendation],
) -> None:
    """Check for stale context."""
    if quality.freshness < thresholds.min_freshness:
        severity = "warning" if quality.freshness > 0.0 else "critical"
        issues.append(
            DiagnosticIssue(
                severity=severity,
                category="stale-context",
                message=f"Low freshness ({quality.freshness:.2f}) below threshold ({thresholds.min_freshness:.2f})",
                evidence={"freshness": quality.freshness, "threshold": thresholds.min_freshness},
            )
        )
        recommendations.append(
            Recommendation(
                action="adjust-weights",
                description="Increase recency weight to prioritize fresher context",
                suggested_change={"recency": 1.5},
                estimated_impact="Model will use more up-to-date information",
            )
        )


def _analyze_diversity(
    quality: ContextQuality,
    thresholds: QualityThresholds,
    issues: list[DiagnosticIssue],
    recommendations: list[Recommendation],
) -> None:
    """Check for low diversity."""
    if quality.diversity < thresholds.min_diversity:
        issues.append(
            DiagnosticIssue(
                severity="warning",
                category="low-diversity",
                message=f"Low diversity ({quality.diversity:.2f}) below threshold ({thresholds.min_diversity:.2f})",
                evidence={"diversity": quality.diversity, "threshold": thresholds.min_diversity},
            )
        )
        recommendations.append(
            Recommendation(
                action="add-kind",
                description="Include more diverse item kinds to improve context variety",
                suggested_change={"add_kinds": ["docs", "examples", "memory"]},
                estimated_impact="Broader context diversity improves model reasoning",
            )
        )


def _analyze_utilization(
    pack_result: ContextPack,
    thresholds: QualityThresholds,
    issues: list[DiagnosticIssue],
    recommendations: list[Recommendation],
) -> None:
    """Check budget utilization."""
    utilization = (
        pack_result.total_tokens / pack_result.budget.max_tokens
        if pack_result.budget.max_tokens > 0
        else 0.0
    )

    if utilization < thresholds.min_utilization:
        issues.append(
            DiagnosticIssue(
                severity="info",
                category="budget-waste",
                message=f"Low budget utilization ({utilization:.1%}) — context window is underused",
                evidence={
                    "utilization": round(utilization, 3),
                    "tokens_used": pack_result.total_tokens,
                    "budget": pack_result.budget.max_tokens,
                },
            )
        )
        recommendations.append(
            Recommendation(
                action="increase-budget",
                description="Budget is significantly underused; consider adding more context or reducing budget",
                suggested_change={"max_tokens": pack_result.total_tokens + 500},
                estimated_impact="Right-sizing budget saves cost without losing context",
            )
        )

    if utilization > thresholds.max_utilization:
        issues.append(
            DiagnosticIssue(
                severity="warning",
                category="budget-waste",
                message=f"Budget nearly full ({utilization:.1%}) — important items may be dropped",
                evidence={
                    "utilization": round(utilization, 3),
                    "dropped_count": len(pack_result.dropped),
                },
            )
        )
        recommendations.append(
            Recommendation(
                action="enable-compression",
                description="Enable compression to fit more items within budget",
                suggested_change={"allow_compression": True},
                estimated_impact="Compression can save 20-50% tokens per item",
            )
        )


def _analyze_dropped(
    pack_result: ContextPack,
    query: str | None,
) -> DroppedAnalysis:
    """Analyze dropped items for diagnostic insight."""
    dropped = pack_result.dropped
    dropped_by_kind: dict[str, int] = {}
    for item in dropped:
        kind = item.kind or "unknown"
        dropped_by_kind[kind] = dropped_by_kind.get(kind, 0) + 1

    # High-priority dropped items (priority >= 7 on 0-10 scale).
    high_priority_dropped = [item for item in dropped if (item.priority or 0) >= 7]

    # Potentially relevant dropped items (if query provided).
    potentially_relevant: list[ContextItem] = []
    if query and dropped:
        q = normalize_query(query)
        for item in dropped:
            relevance = compute_relevance(q, item)
            if relevance > 0.3:
                potentially_relevant.append(item)

    return DroppedAnalysis(
        total_dropped=len(dropped),
        dropped_by_kind=dropped_by_kind,
        high_priority_dropped=high_priority_dropped,
        potentially_relevant=potentially_relevant,
    )


def _analyze_priorities(
    pack_result: ContextPack,
    issues: list[DiagnosticIssue],
    recommendations: list[Recommendation],
) -> None:
    """Check whether high-priority items were dropped while low-priority kept."""
    if not pack_result.dropped:
        return

    max_dropped_priority = max((item.priority or 0.0) for item in pack_result.dropped)
    if not pack_result.selected:
        return
    min_selected_priority = min((item.priority or 0.0) for item in pack_result.selected)

    if max_dropped_priority > min_selected_priority and max_dropped_priority >= 5.0:
        issues.append(
            DiagnosticIssue(
                severity="warning",
                category="wrong-priorities",
                message=(
                    f"High-priority items dropped (max={max_dropped_priority:.1f}) "
                    f"while lower-priority items kept (min={min_selected_priority:.1f})"
                ),
                evidence={
                    "max_dropped_priority": max_dropped_priority,
                    "min_selected_priority": min_selected_priority,
                },
            )
        )
        recommendations.append(
            Recommendation(
                action="adjust-weights",
                description="Increase priority weight to ensure important items are selected first",
                suggested_change={"priority": 2.0},
                estimated_impact="Critical context items will be consistently included",
            )
        )


def _analyze_missing_context(
    quality: ContextQuality,
    thresholds: QualityThresholds,
    issues: list[DiagnosticIssue],
    recommendations: list[Recommendation],
) -> None:
    """Check for low density indicating missing useful context."""
    if quality.density < thresholds.min_density:
        issues.append(
            DiagnosticIssue(
                severity="warning",
                category="missing-context",
                message=f"Low information density ({quality.density:.2f}) below threshold ({thresholds.min_density:.2f})",
                evidence={"density": quality.density, "threshold": thresholds.min_density},
            )
        )
        recommendations.append(
            Recommendation(
                action="add-kind",
                description="Add more information-rich context items to improve density",
                suggested_change={"add_kinds": ["code", "docs"]},
                estimated_impact="Higher density context leads to more accurate model outputs",
            )
        )


def _determine_health(issues: list[DiagnosticIssue]) -> str:
    """Determine overall health from issues."""
    severities = {issue.severity for issue in issues}
    if "critical" in severities:
        return "critical"
    if "warning" in severities:
        return "warning"
    return "good"


# ---------------------------------------------------------------------------
# ContextDebugger
# ---------------------------------------------------------------------------


class ContextDebugger:
    """Diagnoses context quality issues and produces recommendations."""

    def __init__(self, thresholds: QualityThresholds | None = None) -> None:
        self._thresholds = thresholds or QualityThresholds()

    def diagnose(self, pack_result: ContextPack, query: str | None = None) -> Diagnosis:
        """Run a full diagnostic on a context pack.

        1. Analyze quality metrics via analyze_context().
        2. Analyze dropped items.
        3. Run all analyzers (redundancy, freshness, diversity, utilization,
           priorities, missing context).
        4. Determine overall health.

        Args:
            pack_result: The ContextPack to diagnose.
            query: Optional query for relevance-based checks.

        Returns:
            Diagnosis with health status, issues, and recommendations.
        """
        quality = analyze_context(pack_result.selected)
        issues: list[DiagnosticIssue] = []
        recommendations: list[Recommendation] = []

        # Run all analyzers.
        _analyze_redundancy(quality, self._thresholds, issues, recommendations)
        _analyze_freshness(quality, self._thresholds, issues, recommendations)
        _analyze_diversity(quality, self._thresholds, issues, recommendations)
        _analyze_utilization(pack_result, self._thresholds, issues, recommendations)
        _analyze_priorities(pack_result, issues, recommendations)
        _analyze_missing_context(quality, self._thresholds, issues, recommendations)

        # Dropped analysis.
        dropped_analysis = _analyze_dropped(pack_result, query)
        if dropped_analysis.high_priority_dropped:
            issues.append(
                DiagnosticIssue(
                    severity="critical",
                    category="wrong-priorities",
                    message=f"{len(dropped_analysis.high_priority_dropped)} high-priority items were dropped",
                    evidence={
                        "dropped_ids": [item.id for item in dropped_analysis.high_priority_dropped],
                    },
                )
            )

        overall_health = _determine_health(issues)

        return Diagnosis(
            overall_health=overall_health,
            quality=quality,
            issues=issues,
            recommendations=recommendations,
            dropped_analysis=dropped_analysis,
        )

    def proactive_check(
        self,
        items: list[ContextItem],
        budget: Budget,
        query: str | None = None,
    ) -> Diagnosis:
        """Simulate packing and diagnose the result proactively.

        Args:
            items: Items to pack.
            budget: Token budget.
            query: Optional query for relevance checks.

        Returns:
            Diagnosis of the simulated pack.
        """
        result = pack(items, budget)
        return self.diagnose(result, query)

    def compare_responses(
        self,
        pack_a: ContextPack,
        quality_a: float,
        pack_b: ContextPack,
        quality_b: float,
    ) -> ComparisonResult:
        """Compare two context packs and their output quality.

        Args:
            pack_a: First context pack.
            quality_a: Quality score (0-1) of outputs from pack_a.
            pack_b: Second context pack.
            quality_b: Quality score (0-1) of outputs from pack_b.

        Returns:
            ComparisonResult with quality analysis and insights.
        """
        qa = analyze_context(pack_a.selected)
        qb = analyze_context(pack_b.selected)

        ids_a = {item.id for item in pack_a.selected}
        ids_b = {item.id for item in pack_b.selected}

        item_diff = {
            "only_in_a": sorted(ids_a - ids_b),
            "only_in_b": sorted(ids_b - ids_a),
            "shared": sorted(ids_a & ids_b),
        }

        quality_delta = quality_b - quality_a
        insights: list[str] = []

        # Generate insights.
        if abs(quality_delta) > 0.1:
            better = "B" if quality_delta > 0 else "A"
            insights.append(
                f"Pack {better} produced significantly better outputs (delta={quality_delta:+.2f})"
            )

        if qa.redundancy > qb.redundancy + 0.1:
            insights.append("Pack A has higher redundancy — deduplication may help")
        elif qb.redundancy > qa.redundancy + 0.1:
            insights.append("Pack B has higher redundancy — deduplication may help")

        if qa.diversity > qb.diversity + 0.1:
            insights.append("Pack A has more diverse context")
        elif qb.diversity > qa.diversity + 0.1:
            insights.append("Pack B has more diverse context")

        if qa.freshness > qb.freshness + 0.1:
            insights.append("Pack A has fresher context")
        elif qb.freshness > qa.freshness + 0.1:
            insights.append("Pack B has fresher context")

        only_in_better = item_diff["only_in_b"] if quality_delta > 0 else item_diff["only_in_a"]
        if only_in_better:
            insights.append(f"Items unique to the better pack: {', '.join(only_in_better[:5])}")

        return ComparisonResult(
            pack_a_quality=qa,
            pack_b_quality=qb,
            item_diff=item_diff,
            quality_delta=round(quality_delta, 4),
            insights=insights,
        )


def create_context_debugger(
    thresholds: QualityThresholds | None = None,
) -> ContextDebugger:
    """Factory for context debugger."""
    return ContextDebugger(thresholds)
