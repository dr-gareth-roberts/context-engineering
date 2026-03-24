"""Drift Detector -- continuous monitoring of context quality degradation.

Detects when context is silently losing coherence before the model
starts hallucinating.  Mirrors the TypeScript ``@context-engineering/drift``
package.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Literal, Optional

from .core import Budget, ContextItem, ContextPack, estimate_tokens
from .quality import ContextQuality, analyze_context

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class DriftThresholds:
    """Thresholds for each drift dimension."""

    relevance_drift: float = 0.2
    redundancy_creep: float = 0.4
    topic_drift: float = 0.3
    stale_ratio: float = 0.5
    underutilization: float = 0.5
    density_drop: float = 0.25


@dataclass
class DriftMonitorConfig:
    """Configuration for the drift monitor."""

    window_size: int = 10
    thresholds: DriftThresholds = field(default_factory=DriftThresholds)
    on_alert: Optional[Callable[["DriftAlert"], None]] = None
    min_observations: int = 3


@dataclass
class DriftObservation:
    """A single point-in-time observation of context quality."""

    timestamp: float
    quality: ContextQuality
    item_count: int
    total_tokens: int
    budget_utilization: float
    stale_item_count: int
    top_kinds: Dict[str, int]


DriftDimension = Literal[
    "relevance", "redundancy", "diversity", "density", "freshness", "utilization"
]

DriftSeverity = Literal["healthy", "warning", "critical"]


@dataclass
class DriftAlert:
    """An alert generated when drift is detected."""

    dimension: DriftDimension
    severity: DriftSeverity
    current_value: float
    baseline_value: float
    delta: float
    trend: Literal["improving", "stable", "degrading"]
    message: str
    recommendation: str
    observation_index: int


@dataclass
class DimensionReport:
    """Report for a single drift dimension."""

    current: float
    baseline: float
    delta: float
    trend: Literal["improving", "stable", "degrading"]
    severity: DriftSeverity
    history: List[float]


@dataclass
class DriftReport:
    """Full drift report across all dimensions."""

    status: DriftSeverity
    drifting: bool
    since: Optional[float]
    observation_count: int
    dimensions: Dict[DriftDimension, DimensionReport]
    alerts: List[DriftAlert]
    recommendations: List[str]


@dataclass
class DriftMonitorState:
    """Serializable state for persistence."""

    observations: List[DriftObservation]
    config: DriftMonitorConfig


# ---------------------------------------------------------------------------
# Analyzers
# ---------------------------------------------------------------------------


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _compute_trend(
    values: List[float], higher_is_better: bool
) -> Literal["improving", "stable", "degrading"]:
    if len(values) < 2:
        return "stable"
    mid = len(values) // 2
    first_half = _mean(values[:mid])
    second_half = _mean(values[mid:])
    diff = second_half - first_half
    threshold = 0.02
    if abs(diff) < threshold:
        return "stable"
    if higher_is_better:
        return "improving" if diff > 0 else "degrading"
    return "improving" if diff < 0 else "degrading"


def classify_severity(delta: float, threshold: float) -> DriftSeverity:
    """Classify severity based on delta vs threshold."""
    abs_delta = abs(delta)
    if abs_delta >= threshold:
        return "critical"
    if abs_delta >= threshold / 2:
        return "warning"
    return "healthy"


def _empty_report() -> DimensionReport:
    return DimensionReport(
        current=0.0,
        baseline=0.0,
        delta=0.0,
        trend="stable",
        severity="healthy",
        history=[],
    )


def analyze_relevance_drift(
    observations: List[DriftObservation], threshold: float
) -> DimensionReport:
    """Analyze relevance drift: overall quality declining from baseline."""
    if not observations:
        return _empty_report()
    values = [o.quality.overall for o in observations]
    baseline_count = max(1, len(observations) // 3)
    baseline = _mean(values[:baseline_count])
    current = values[-1]
    delta = current - baseline
    trend = _compute_trend(values, higher_is_better=True)
    severity = classify_severity(delta, threshold) if delta < 0 else "healthy"
    return DimensionReport(
        current=current,
        baseline=baseline,
        delta=delta,
        trend=trend,
        severity=severity,
        history=values,
    )


def analyze_redundancy_creep(
    observations: List[DriftObservation], threshold: float
) -> DimensionReport:
    """Analyze redundancy creep: redundancy trending upward."""
    if not observations:
        return _empty_report()
    values = [o.quality.redundancy for o in observations]
    baseline_count = max(1, len(observations) // 3)
    baseline = _mean(values[:baseline_count])
    current = values[-1]
    delta = current - baseline
    trend = _compute_trend(values, higher_is_better=False)
    severity = classify_severity(delta, threshold) if delta > 0 else "healthy"
    return DimensionReport(
        current=current,
        baseline=baseline,
        delta=delta,
        trend=trend,
        severity=severity,
        history=values,
    )


def analyze_topic_drift(observations: List[DriftObservation], threshold: float) -> DimensionReport:
    """Analyze topic drift: diversity declining from baseline."""
    if not observations:
        return _empty_report()
    values = [o.quality.diversity for o in observations]
    baseline_count = max(1, len(observations) // 3)
    baseline = _mean(values[:baseline_count])
    current = values[-1]
    delta = current - baseline
    trend = _compute_trend(values, higher_is_better=True)
    severity = classify_severity(delta, threshold) if delta < 0 else "healthy"
    return DimensionReport(
        current=current,
        baseline=baseline,
        delta=delta,
        trend=trend,
        severity=severity,
        history=values,
    )


def analyze_staleness(observations: List[DriftObservation], threshold: float) -> DimensionReport:
    """Analyze staleness: ratio of stale items increasing."""
    if not observations:
        return _empty_report()
    values = [o.stale_item_count / o.item_count if o.item_count > 0 else 0.0 for o in observations]
    baseline_count = max(1, len(observations) // 3)
    baseline = _mean(values[:baseline_count])
    current = values[-1]
    delta = current - baseline
    trend = _compute_trend(values, higher_is_better=False)
    severity = classify_severity(delta, threshold) if delta > 0 else "healthy"
    return DimensionReport(
        current=current,
        baseline=baseline,
        delta=delta,
        trend=trend,
        severity=severity,
        history=values,
    )


def analyze_utilization(observations: List[DriftObservation], threshold: float) -> DimensionReport:
    """Analyze utilization: budget utilization dropping."""
    if not observations:
        return _empty_report()
    values = [o.budget_utilization for o in observations]
    baseline_count = max(1, len(observations) // 3)
    baseline = _mean(values[:baseline_count])
    current = values[-1]
    delta = current - baseline
    trend = _compute_trend(values, higher_is_better=True)
    severity = classify_severity(delta, threshold) if delta < 0 else "healthy"
    return DimensionReport(
        current=current,
        baseline=baseline,
        delta=delta,
        trend=trend,
        severity=severity,
        history=values,
    )


def analyze_density_drop(observations: List[DriftObservation], threshold: float) -> DimensionReport:
    """Analyze density drop: information density declining."""
    if not observations:
        return _empty_report()
    values = [o.quality.density for o in observations]
    baseline_count = max(1, len(observations) // 3)
    baseline = _mean(values[:baseline_count])
    current = values[-1]
    delta = current - baseline
    trend = _compute_trend(values, higher_is_better=True)
    severity = classify_severity(delta, threshold) if delta < 0 else "healthy"
    return DimensionReport(
        current=current,
        baseline=baseline,
        delta=delta,
        trend=trend,
        severity=severity,
        history=values,
    )


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

_DIMENSION_CONFIG: List[
    tuple[DriftDimension, str, Callable[[List[DriftObservation], float], DimensionReport]]
] = [
    ("relevance", "relevance_drift", analyze_relevance_drift),
    ("redundancy", "redundancy_creep", analyze_redundancy_creep),
    ("diversity", "topic_drift", analyze_topic_drift),
    ("freshness", "stale_ratio", analyze_staleness),
    ("utilization", "underutilization", analyze_utilization),
    ("density", "density_drop", analyze_density_drop),
]


def generate_recommendation(dimension: DriftDimension, severity: DriftSeverity) -> str:
    """Generate a human-readable recommendation for a dimension."""
    urgency = "Immediately" if severity == "critical" else "Consider"
    recommendations: Dict[DriftDimension, str] = {
        "relevance": f"{urgency} re-score and re-rank context items to restore relevance",
        "redundancy": f"{urgency} deduplicate overlapping context items to reduce redundancy",
        "diversity": f"{urgency} broaden retrieval sources to restore topic diversity",
        "freshness": f"{urgency} prune stale retrieval items and refresh context sources",
        "utilization": f"{urgency} increase budget or add more context to improve utilization",
        "density": f"{urgency} compress or summarize low-density items to improve information density",
    }
    return recommendations[dimension]


def _generate_message(dimension: DriftDimension, severity: DriftSeverity, delta: float) -> str:
    if dimension in ("redundancy", "freshness"):
        direction = "increased" if delta > 0 else "decreased"
    else:
        direction = "decreased" if delta < 0 else "increased"

    severity_label = "Critical" if severity == "critical" else "Warning"
    dimension_labels: Dict[DriftDimension, str] = {
        "relevance": "overall relevance",
        "redundancy": "content redundancy",
        "diversity": "topic diversity",
        "freshness": "stale item ratio",
        "utilization": "budget utilization",
        "density": "information density",
    }
    return f"{severity_label}: {dimension_labels[dimension]} has {direction} by {abs(delta):.3f}"


def generate_alerts(
    observations: List[DriftObservation],
    thresholds: Optional[DriftThresholds] = None,
) -> tuple[Dict[DriftDimension, DimensionReport], List[DriftAlert]]:
    """Run all analyzers, generate alerts for dimensions exceeding thresholds."""
    resolved = thresholds or DriftThresholds()
    dimensions: Dict[DriftDimension, DimensionReport] = {}
    alerts: List[DriftAlert] = []

    for dimension, threshold_attr, analyze_fn in _DIMENSION_CONFIG:
        threshold_val = getattr(resolved, threshold_attr)
        report = analyze_fn(observations, threshold_val)
        dimensions[dimension] = report

        if report.severity != "healthy":
            alert = DriftAlert(
                dimension=dimension,
                severity=report.severity,
                current_value=report.current,
                baseline_value=report.baseline,
                delta=report.delta,
                trend=report.trend,
                message=_generate_message(dimension, report.severity, report.delta),
                recommendation=generate_recommendation(dimension, report.severity),
                observation_index=len(observations) - 1,
            )
            alerts.append(alert)

    return dimensions, alerts


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


def _build_observation(items: List[ContextItem], budget: Budget) -> DriftObservation:
    """Build a DriftObservation from items and budget."""
    quality = analyze_context(items)
    total_tokens = sum(item.tokens or estimate_tokens(item.content) for item in items)
    effective_budget = budget.max_tokens - (budget.reserve_tokens or 0)
    budget_utilization = total_tokens / effective_budget if effective_budget > 0 else 0.0
    stale_item_count = sum(1 for item in items if (item.recency or 0) < 0.2)

    top_kinds: Dict[str, int] = {}
    for item in items:
        kind = item.kind or "unknown"
        top_kinds[kind] = top_kinds.get(kind, 0) + 1

    return DriftObservation(
        timestamp=time.time(),
        quality=quality,
        item_count=len(items),
        total_tokens=total_tokens,
        budget_utilization=min(budget_utilization, 1.0),
        stale_item_count=stale_item_count,
        top_kinds=top_kinds,
    )


class DriftMonitor:
    """Monitors context quality over time and detects drift."""

    def __init__(self, config: Optional[DriftMonitorConfig] = None) -> None:
        cfg = config or DriftMonitorConfig()
        self._window_size = cfg.window_size
        self._min_observations = cfg.min_observations
        self._thresholds = cfg.thresholds
        self._on_alert = cfg.on_alert
        self._observations: List[DriftObservation] = []
        self._drift_since: Optional[float] = None

    def _add_observation(self, obs: DriftObservation) -> None:
        self._observations.append(obs)
        if len(self._observations) > self._window_size:
            self._observations = self._observations[-self._window_size :]

        if len(self._observations) >= self._min_observations and self._on_alert:
            _, alerts = generate_alerts(self._observations, self._thresholds)
            for alert in alerts:
                self._on_alert(alert)

    def observe(self, packed: ContextPack, budget: Budget) -> None:
        """Feed a new observation from a context pack."""
        obs = _build_observation(packed.selected, budget)
        self._add_observation(obs)

    def observe_items(self, items: List[ContextItem], budget: Budget) -> None:
        """Feed a new observation from raw items and budget."""
        obs = _build_observation(items, budget)
        self._add_observation(obs)

    def report(self) -> DriftReport:
        """Get the current drift report."""
        if not self._observations:
            return DriftReport(
                status="healthy",
                drifting=False,
                since=None,
                observation_count=0,
                dimensions={
                    "relevance": DimensionReport(0.0, 0.0, 0.0, "stable", "healthy", []),
                    "redundancy": DimensionReport(0.0, 0.0, 0.0, "stable", "healthy", []),
                    "diversity": DimensionReport(0.0, 0.0, 0.0, "stable", "healthy", []),
                    "density": DimensionReport(0.0, 0.0, 0.0, "stable", "healthy", []),
                    "freshness": DimensionReport(0.0, 0.0, 0.0, "stable", "healthy", []),
                    "utilization": DimensionReport(0.0, 0.0, 0.0, "stable", "healthy", []),
                },
                alerts=[],
                recommendations=[],
            )

        dimensions, alerts = generate_alerts(self._observations, self._thresholds)

        effective_alerts = alerts if len(self._observations) >= self._min_observations else []

        severity_order = ["healthy", "warning", "critical"]
        worst_severity: DriftSeverity = "healthy"
        if len(self._observations) >= self._min_observations:
            for dim_report in dimensions.values():
                idx = severity_order.index(dim_report.severity)
                if idx > severity_order.index(worst_severity):
                    worst_severity = dim_report.severity

        is_drifting = worst_severity != "healthy"

        if is_drifting and self._drift_since is None:
            self._drift_since = self._observations[-1].timestamp
        elif not is_drifting:
            self._drift_since = None

        recommendations = list(dict.fromkeys(a.recommendation for a in effective_alerts))

        return DriftReport(
            status=worst_severity,
            drifting=is_drifting,
            since=self._drift_since,
            observation_count=len(self._observations),
            dimensions=dimensions,
            alerts=effective_alerts,
            recommendations=recommendations,
        )

    def reset(self) -> None:
        """Reset all observations and baselines."""
        self._observations = []
        self._drift_since = None

    def history(self) -> List[DriftObservation]:
        """Get the raw observation history (windowed)."""
        return list(self._observations)

    def export_state(self) -> DriftMonitorState:
        """Export state for persistence."""
        return DriftMonitorState(
            observations=list(self._observations),
            config=DriftMonitorConfig(
                window_size=self._window_size,
                thresholds=self._thresholds,
                min_observations=self._min_observations,
            ),
        )

    def import_state(self, state: DriftMonitorState) -> None:
        """Import previously exported state."""
        self._observations = list(state.observations)
        if len(self._observations) > self._window_size:
            self._observations = self._observations[-self._window_size :]
        self._drift_since = None


def create_drift_monitor(config: Optional[DriftMonitorConfig] = None) -> DriftMonitor:
    """Create a drift monitor that tracks context quality over time.

    The monitor maintains a sliding window of observations and analyzes
    them for drift across multiple dimensions. When drift is detected,
    the optional ``on_alert`` callback is invoked.

    Args:
        config: Optional monitor configuration.

    Returns:
        A DriftMonitor instance.

    Example::

        monitor = create_drift_monitor(DriftMonitorConfig(
            window_size=20,
            on_alert=lambda alert: print(alert.message),
        ))

        # After each pack/compile cycle:
        monitor.observe_items(items, budget)
        report = monitor.report()
        if report.drifting:
            print(f"Drift detected since {report.since}")
    """
    return DriftMonitor(config)
