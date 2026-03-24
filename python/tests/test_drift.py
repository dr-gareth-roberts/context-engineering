"""Tests for the drift detection module."""

from __future__ import annotations

from context_engineering.core import Budget, ContextItem
from context_engineering.drift import (
    DriftAlert,
    DriftMonitorConfig,
    DriftObservation,
    DriftThresholds,
    analyze_density_drop,
    analyze_redundancy_creep,
    analyze_relevance_drift,
    analyze_staleness,
    classify_severity,
    create_drift_monitor,
    generate_alerts,
    generate_recommendation,
)
from context_engineering.quality import ContextQuality


def _make_quality(**overrides) -> ContextQuality:
    defaults = dict(
        item_count=5,
        total_tokens=500,
        density=0.6,
        diversity=0.7,
        freshness=0.8,
        redundancy=0.1,
        overall=0.75,
    )
    defaults.update(overrides)
    return ContextQuality(**defaults)


def _make_observation(**overrides) -> DriftObservation:
    quality_overrides = overrides.pop("quality_overrides", {})
    defaults = dict(
        timestamp=1000.0,
        quality=_make_quality(**quality_overrides),
        item_count=5,
        total_tokens=500,
        budget_utilization=0.8,
        stale_item_count=0,
        top_kinds={"code": 3, "docs": 2},
    )
    defaults.update(overrides)
    return DriftObservation(**defaults)


def _make_item(id: str, content: str, **kwargs) -> ContextItem:
    tokens = kwargs.pop("tokens", max(1, int(len(content.split()) * 1.3)))
    return ContextItem(id=id, content=content, tokens=tokens, **kwargs)


DEFAULT_BUDGET = Budget(maxTokens=4000)


# ---------------------------------------------------------------------------
# classify_severity
# ---------------------------------------------------------------------------


class TestClassifySeverity:
    def test_healthy_below_half_threshold(self):
        assert classify_severity(0.05, 0.2) == "healthy"

    def test_warning_between_half_and_full(self):
        assert classify_severity(0.15, 0.2) == "warning"

    def test_critical_at_or_above_threshold(self):
        assert classify_severity(0.2, 0.2) == "critical"
        assert classify_severity(0.3, 0.2) == "critical"

    def test_uses_absolute_value(self):
        assert classify_severity(-0.15, 0.2) == "warning"
        assert classify_severity(-0.25, 0.2) == "critical"


# ---------------------------------------------------------------------------
# Analyzers
# ---------------------------------------------------------------------------


class TestAnalyzeRelevanceDrift:
    def test_empty_observations_returns_healthy(self):
        report = analyze_relevance_drift([], 0.2)
        assert report.severity == "healthy"
        assert report.history == []

    def test_detects_declining_quality(self):
        observations = [
            _make_observation(quality_overrides={"overall": v})
            for v in [0.8, 0.75, 0.7, 0.6, 0.5, 0.4]
        ]
        report = analyze_relevance_drift(observations, 0.2)
        assert report.severity != "healthy"
        assert report.trend == "degrading"
        assert report.delta < 0

    def test_stable_quality_stays_healthy(self):
        observations = [_make_observation(quality_overrides={"overall": 0.75}) for _ in range(6)]
        report = analyze_relevance_drift(observations, 0.2)
        assert report.severity == "healthy"
        assert report.trend == "stable"


class TestAnalyzeRedundancyCreep:
    def test_detects_rising_redundancy(self):
        observations = [
            _make_observation(quality_overrides={"redundancy": v})
            for v in [0.1, 0.15, 0.3, 0.5, 0.7, 0.8]
        ]
        report = analyze_redundancy_creep(observations, 0.4)
        assert report.severity != "healthy"
        assert report.delta > 0


class TestAnalyzeStaleness:
    def test_detects_increasing_stale_ratio(self):
        observations = [
            _make_observation(item_count=10, stale_item_count=sc) for sc in [1, 2, 4, 6, 8, 9]
        ]
        report = analyze_staleness(observations, 0.5)
        assert report.severity != "healthy"

    def test_handles_zero_items(self):
        observations = [_make_observation(item_count=0, stale_item_count=0)]
        report = analyze_staleness(observations, 0.5)
        assert report.current == 0.0


class TestAnalyzeDensityDrop:
    def test_returns_density_history(self):
        observations = [
            _make_observation(quality_overrides={"density": v}) for v in [0.8, 0.7, 0.6]
        ]
        report = analyze_density_drop(observations, 0.25)
        assert report.history == [0.8, 0.7, 0.6]


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


class TestGenerateAlerts:
    def test_no_alerts_for_stable_observations(self):
        observations = [_make_observation() for _ in range(6)]
        _, alerts = generate_alerts(observations)
        assert alerts == []

    def test_generates_relevance_alert_on_degradation(self):
        observations = [
            _make_observation(quality_overrides={"overall": v})
            for v in [0.9, 0.85, 0.7, 0.55, 0.4, 0.3]
        ]
        _, alerts = generate_alerts(observations)
        relevance = [a for a in alerts if a.dimension == "relevance"]
        assert len(relevance) == 1
        assert relevance[0].delta < 0

    def test_all_six_dimensions_reported(self):
        observations = [_make_observation() for _ in range(6)]
        dimensions, _ = generate_alerts(observations)
        assert len(dimensions) == 6
        assert set(dimensions.keys()) == {
            "relevance",
            "redundancy",
            "diversity",
            "freshness",
            "utilization",
            "density",
        }

    def test_custom_thresholds(self):
        observations = [
            _make_observation(quality_overrides={"overall": v})
            for v in [0.8, 0.78, 0.75, 0.73, 0.7, 0.68]
        ]
        _, tight_alerts = generate_alerts(observations, DriftThresholds(relevance_drift=0.05))
        tight_relevance = [a for a in tight_alerts if a.dimension == "relevance"]
        assert len(tight_relevance) > 0


class TestGenerateRecommendation:
    def test_warning_uses_consider(self):
        rec = generate_recommendation("relevance", "warning")
        assert "Consider" in rec

    def test_critical_uses_immediately(self):
        rec = generate_recommendation("relevance", "critical")
        assert "Immediately" in rec

    def test_freshness_mentions_stale(self):
        rec = generate_recommendation("freshness", "warning")
        assert "stale" in rec.lower()


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


class TestDriftMonitor:
    def test_healthy_with_no_observations(self):
        monitor = create_drift_monitor()
        report = monitor.report()
        assert report.status == "healthy"
        assert report.drifting is False
        assert report.since is None
        assert report.observation_count == 0

    def test_single_observation_no_alert(self):
        monitor = create_drift_monitor(DriftMonitorConfig(min_observations=3))
        items = [_make_item("a", "some test content here")]
        monitor.observe_items(items, DEFAULT_BUDGET)
        report = monitor.report()
        assert report.alerts == []
        assert report.drifting is False

    def test_reset_clears_state(self):
        monitor = create_drift_monitor()
        items = [_make_item("a", "some content for testing")]
        monitor.observe_items(items, DEFAULT_BUDGET)
        monitor.observe_items(items, DEFAULT_BUDGET)
        assert len(monitor.history()) == 2

        monitor.reset()
        assert len(monitor.history()) == 0
        assert monitor.report().status == "healthy"

    def test_window_size_limits_retention(self):
        monitor = create_drift_monitor(DriftMonitorConfig(window_size=3))
        items = [_make_item("a", "content for window size test")]
        for _ in range(10):
            monitor.observe_items(items, DEFAULT_BUDGET)
        assert len(monitor.history()) == 3

    def test_export_import_round_trip(self):
        monitor = create_drift_monitor(DriftMonitorConfig(window_size=10))
        items = [
            _make_item("a", "first unique context content"),
            _make_item("b", "second different vocabulary"),
        ]
        for _ in range(3):
            monitor.observe_items(items, DEFAULT_BUDGET)

        state = monitor.export_state()
        assert len(state.observations) == 3

        monitor2 = create_drift_monitor(DriftMonitorConfig(window_size=10))
        monitor2.import_state(state)
        assert len(monitor2.history()) == 3

    def test_import_trims_to_window_size(self):
        from context_engineering.drift import DriftMonitorState

        monitor = create_drift_monitor(DriftMonitorConfig(window_size=5))
        observations = [_make_observation(timestamp=float(i)) for i in range(20)]
        state = DriftMonitorState(
            observations=observations,
            config=DriftMonitorConfig(window_size=20),
        )
        monitor.import_state(state)
        assert len(monitor.history()) == 5

    def test_history_returns_copy(self):
        monitor = create_drift_monitor()
        items = [_make_item("a", "test content for history")]
        monitor.observe_items(items, DEFAULT_BUDGET)
        h1 = monitor.history()
        h2 = monitor.history()
        assert h1 is not h2
        assert len(h1) == len(h2)

    def test_on_alert_callback_fires(self):
        fired_alerts: list[DriftAlert] = []
        monitor = create_drift_monitor(
            DriftMonitorConfig(
                min_observations=2,
                thresholds=DriftThresholds(relevance_drift=0.05),
                on_alert=lambda a: fired_alerts.append(a),
            )
        )
        good_items = [
            _make_item("a", "comprehensive architecture documentation notes", recency=8),
            _make_item("b", "database migration strategy overview planning", recency=9),
            _make_item("c", "unique performance benchmarks optimization", recency=7),
        ]
        monitor.observe_items(good_items, DEFAULT_BUDGET)
        monitor.observe_items(good_items, DEFAULT_BUDGET)

        bad_items = [_make_item("x", "x x x x x x x x x x x x x x x x", recency=0)]
        for _ in range(5):
            monitor.observe_items(bad_items, DEFAULT_BUDGET)

        assert len(fired_alerts) > 0

    def test_stale_items_counted_by_recency(self):
        monitor = create_drift_monitor()
        items = [
            _make_item("a", "fresh content here", recency=8.0),
            _make_item("b", "slightly old now", recency=0.5),
            _make_item("c", "stale content data", recency=0.1),
            _make_item("d", "very stale item", recency=0.0),
        ]
        monitor.observe_items(items, DEFAULT_BUDGET)
        obs = monitor.history()[0]
        # recency < 0.2: c (0.1) and d (0.0)
        assert obs.stale_item_count == 2

    def test_empty_items_valid_observation(self):
        monitor = create_drift_monitor()
        monitor.observe_items([], DEFAULT_BUDGET)
        obs = monitor.history()[0]
        assert obs.item_count == 0
        assert obs.total_tokens == 0

    def test_recommendations_are_unique(self):
        monitor = create_drift_monitor(
            DriftMonitorConfig(
                min_observations=2,
                thresholds=DriftThresholds(relevance_drift=0.01),
            )
        )
        good_items = [
            _make_item("a", "excellent architecture documentation notes", recency=9),
            _make_item("b", "database planning strategy migration", recency=8),
        ]
        monitor.observe_items(good_items, DEFAULT_BUDGET)
        monitor.observe_items(good_items, DEFAULT_BUDGET)

        bad_items = [_make_item("z", "repetitive repetitive repetitive repetitive", recency=0)]
        for _ in range(5):
            monitor.observe_items(bad_items, DEFAULT_BUDGET)

        report = monitor.report()
        assert len(report.recommendations) == len(set(report.recommendations))
