"""Tests for webhook telemetry integration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from context_engineering.core import Budget, ContextItem, ContextPack, ContextTrace, TraceStep
from context_engineering.quality import ContextQuality
from context_engineering.cost import CostEstimate
from context_engineering.webhook import (
    PackReportExtras,
    HandoffReportExtras,
    WebhookReporter,
    _NoopReporter,
    _fire_webhook,
    create_webhook_reporter,
    noop_reporter,
)


def _make_pack(**overrides) -> ContextPack:
    defaults = dict(
        budget=Budget(maxTokens=4096),
        selected=[
            ContextItem(id="a", content="hello", tokens=100),
            ContextItem(id="b", content="world", tokens=200),
        ],
        dropped=[ContextItem(id="c", content="dropped", tokens=500)],
        totalTokens=300,
    )
    defaults.update(overrides)
    return ContextPack(**defaults)


def _make_trace() -> ContextTrace:
    return ContextTrace(
        pack=_make_pack(),
        steps=[
            TraceStep(id="a", decision="include", tokens=100, reason="fits_budget"),
            TraceStep(id="b", decision="include", tokens=200, reason="fits_budget"),
            TraceStep(id="c", decision="exclude", tokens=500, reason="over_budget"),
        ],
        created_at="2026-01-01T00:00:00.000Z",
    )


@dataclass
class _FakeHandoff:
    jsonl: str = '{"id":"ce-handoff-test"}\n{"id":"ce-a"}'
    stats: Dict[str, Any] = None

    def __post_init__(self):
        if self.stats is None:
            self.stats = {
                "totalIssues": 2,
                "activeItems": 1,
                "deferredItems": 0,
            }


class TestCreateWebhookReporter:
    def test_returns_noop_when_no_url(self, monkeypatch):
        monkeypatch.delenv("CE_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("CE_WEBHOOK_HANDOFF_URL", raising=False)
        monkeypatch.delenv("CE_WEBHOOK_QUALITY_URL", raising=False)
        monkeypatch.delenv("CE_WEBHOOK_COST_URL", raising=False)
        reporter = create_webhook_reporter()
        assert isinstance(reporter, _NoopReporter)

    def test_reads_env_analytics_url(self, monkeypatch):
        monkeypatch.setenv("CE_WEBHOOK_URL", "https://hook.example.com/analytics")
        monkeypatch.delenv("CE_WEBHOOK_HANDOFF_URL", raising=False)
        reporter = create_webhook_reporter()
        assert isinstance(reporter, WebhookReporter)
        assert reporter._analytics_url == "https://hook.example.com/analytics"

    def test_reads_env_handoff_url(self, monkeypatch):
        monkeypatch.delenv("CE_WEBHOOK_URL", raising=False)
        monkeypatch.setenv("CE_WEBHOOK_HANDOFF_URL", "https://hook.example.com/handoff")
        reporter = create_webhook_reporter()
        assert isinstance(reporter, WebhookReporter)
        assert reporter._handoff_url == "https://hook.example.com/handoff"

    def test_prefers_explicit_url(self, monkeypatch):
        monkeypatch.setenv("CE_WEBHOOK_URL", "https://env.example.com")
        reporter = create_webhook_reporter(analytics_url="https://explicit.example.com")
        assert isinstance(reporter, WebhookReporter)
        assert reporter._analytics_url == "https://explicit.example.com"


class TestReportPack:
    @patch("context_engineering.webhook._fire_webhook")
    def test_sends_correct_payload(self, mock_fire):
        reporter = WebhookReporter(
            analytics_url="https://hook.example.com",
            handoff_url="",
            quality_url="",
            cost_url="",
            session_id="test-session",
            model="claude-sonnet-4-6",
            strategy="greedy-score",
            timeout_s=5.0,
            headers={},
        )

        reporter.report_pack(_make_pack())

        mock_fire.assert_called_once()
        url, payload, _, _ = mock_fire.call_args[0]
        assert url == "https://hook.example.com"
        assert payload["event_type"] == "pack"
        assert payload["session_id"] == "test-session"
        assert payload["model"] == "claude-sonnet-4-6"
        assert payload["budget_max_tokens"] == 4096
        assert payload["budget_reserve_tokens"] == 0
        assert payload["total_tokens"] == 300
        assert payload["selected_count"] == 2
        assert payload["dropped_count"] == 1
        assert payload["remaining_tokens"] == 3796

    @patch("context_engineering.webhook._fire_webhook")
    def test_computes_utilization(self, mock_fire):
        reporter = WebhookReporter(
            analytics_url="https://hook.example.com",
            handoff_url="",
            quality_url="",
            cost_url="",
            session_id="s",
            model="m",
            strategy="s",
            timeout_s=5.0,
            headers={},
        )

        pack = _make_pack(
            budget=Budget(maxTokens=1000, reserveTokens=200),
            totalTokens=640,
        )
        reporter.report_pack(pack)

        _, payload, _, _ = mock_fire.call_args[0]
        # 640 / (1000-200) = 80%
        assert payload["budget_utilization_pct"] == 80.0

    @patch("context_engineering.webhook._fire_webhook")
    def test_includes_extras(self, mock_fire):
        reporter = WebhookReporter(
            analytics_url="https://hook.example.com",
            handoff_url="",
            quality_url="",
            cost_url="",
            session_id="s",
            model="m",
            strategy="s",
            timeout_s=5.0,
            headers={},
        )

        extras = PackReportExtras(
            quality=ContextQuality(
                item_count=2,
                total_tokens=300,
                density=0.8,
                diversity=0.6,
                freshness=0.9,
                redundancy=0.1,
                overall=0.75,
            ),
            cost=CostEstimate(
                model="claude-sonnet-4-6",
                input_tokens=300,
                cached_tokens=200,
                uncached_tokens=100,
                output_tokens=500,
                cost_without_cache=0.02,
                cost_with_cache=0.01,
                savings=0.01,
                savings_percent=50.0,
                cache_efficiency=0.67,
            ),
            cache_hit_ratio=0.67,
        )
        reporter.report_pack(_make_pack(), extras)

        _, payload, _, _ = mock_fire.call_args[0]
        assert payload["quality_overall"] == 0.75
        assert payload["quality_density"] == 0.8
        assert payload["cost_with_cache"] == 0.01
        assert payload["cost_without_cache"] == 0.02
        assert payload["cache_hit_ratio"] == 0.67

    @patch("context_engineering.webhook._fire_webhook")
    def test_no_call_when_no_analytics_url(self, mock_fire):
        reporter = WebhookReporter(
            analytics_url="",
            handoff_url="https://hook.example.com/handoff",
            quality_url="",
            cost_url="",
            session_id="s",
            model="m",
            strategy="s",
            timeout_s=5.0,
            headers={},
        )
        reporter.report_pack(_make_pack())
        mock_fire.assert_not_called()


class TestReportTrace:
    @patch("context_engineering.webhook._fire_webhook")
    def test_includes_trace_decisions(self, mock_fire):
        reporter = WebhookReporter(
            analytics_url="https://hook.example.com",
            handoff_url="",
            quality_url="",
            cost_url="",
            session_id="s",
            model="m",
            strategy="s",
            timeout_s=5.0,
            headers={},
        )

        reporter.report_trace(_make_trace())

        _, payload, _, _ = mock_fire.call_args[0]
        assert payload["event_type"] == "trace"
        assert "trace_decisions" in payload

        decisions = json.loads(payload["trace_decisions"])
        assert len(decisions) == 3
        assert decisions[0]["id"] == "a"
        assert decisions[0]["decision"] == "include"
        assert decisions[2]["decision"] == "exclude"


class TestReportHandoff:
    @patch("context_engineering.webhook._fire_webhook")
    def test_sends_to_handoff_url(self, mock_fire):
        reporter = WebhookReporter(
            analytics_url="",
            handoff_url="https://hook.example.com/handoff",
            quality_url="",
            cost_url="",
            session_id="sess-1",
            model="m",
            strategy="s",
            timeout_s=5.0,
            headers={},
        )

        reporter.report_handoff(
            _FakeHandoff(),
            HandoffReportExtras(source_agent="agent-a", target_url="https://target.example.com"),
        )

        mock_fire.assert_called_once()
        url, payload, _, _ = mock_fire.call_args[0]
        assert url == "https://hook.example.com/handoff"
        assert payload["event_type"] == "handoff"
        assert payload["session_id"] == "sess-1"
        assert payload["total_issues"] == 2
        assert payload["active_items"] == 1
        assert payload["source_agent"] == "agent-a"
        assert payload["target_url"] == "https://target.example.com"
        assert payload["jsonl_size_bytes"] > 0

    @patch("context_engineering.webhook._fire_webhook")
    def test_no_call_when_no_handoff_url(self, mock_fire):
        reporter = WebhookReporter(
            analytics_url="https://hook.example.com",
            handoff_url="",
            quality_url="",
            cost_url="",
            session_id="s",
            model="m",
            strategy="s",
            timeout_s=5.0,
            headers={},
        )
        reporter.report_handoff(_FakeHandoff())
        mock_fire.assert_not_called()


class TestReportPipeline:
    @patch("context_engineering.webhook._fire_webhook")
    def test_sends_pipeline_payload(self, mock_fire):
        reporter = WebhookReporter(
            analytics_url="https://hook.example.com",
            handoff_url="",
            quality_url="",
            cost_url="",
            session_id="s",
            model="m",
            strategy="s",
            timeout_s=5.0,
            headers={},
        )

        @dataclass
        class FakePipelineResult:
            selected: list = None
            dropped: list = None
            total_tokens: int = 450
            budget: Budget = None
            quality: Any = None
            cache_key: Any = None
            cache_efficiency: Any = None
            cacheable_tokens: Any = None
            delta: Any = None
            allocations: Any = None
            allocation_efficiency: Any = None
            input_count: int = 5
            stages: list = None

            def __post_init__(self):
                self.selected = self.selected or [ContextItem(id="a", content="x", tokens=450)]
                self.dropped = self.dropped or [ContextItem(id="b", content="y", tokens=100)]
                self.budget = self.budget or Budget(maxTokens=1000, reserveTokens=100)
                self.stages = self.stages or ["pack", "quality"]

        result = FakePipelineResult()
        reporter.report_pipeline(result)

        mock_fire.assert_called_once()
        _, payload, _, _ = mock_fire.call_args[0]
        assert payload["event_type"] == "pipeline"
        assert payload["stages"] == ["pack", "quality"]
        assert payload["input_count"] == 5
        assert payload["selected_count"] == 1
        assert payload["total_tokens"] == 450
        assert payload["budget_utilization_pct"] == 50.0

    @patch("context_engineering.webhook._fire_webhook")
    def test_no_call_when_no_analytics_url(self, mock_fire):
        reporter = WebhookReporter(
            analytics_url="",
            handoff_url="https://hook.example.com/handoff",
            quality_url="",
            cost_url="",
            session_id="s",
            model="m",
            strategy="s",
            timeout_s=5.0,
            headers={},
        )

        @dataclass
        class FakePipelineResult:
            selected: list = None
            dropped: list = None
            total_tokens: int = 0
            budget: Budget = None
            quality: Any = None
            cache_key: Any = None
            cache_efficiency: Any = None
            cacheable_tokens: Any = None
            delta: Any = None
            allocations: Any = None
            allocation_efficiency: Any = None
            input_count: int = 0
            stages: list = None

            def __post_init__(self):
                self.selected = self.selected or []
                self.dropped = self.dropped or []
                self.budget = self.budget or Budget(maxTokens=1000)
                self.stages = self.stages or []

        reporter.report_pipeline(FakePipelineResult())
        mock_fire.assert_not_called()


class TestReportQuality:
    @patch("context_engineering.webhook._fire_webhook")
    def test_sends_quality_payload(self, mock_fire):
        reporter = WebhookReporter(
            analytics_url="",
            handoff_url="",
            quality_url="https://hook.example.com/quality",
            cost_url="",
            session_id="s",
            model="m",
            strategy="s",
            timeout_s=5.0,
            headers={},
        )

        quality = ContextQuality(
            item_count=2,
            total_tokens=300,
            density=0.8,
            diversity=0.6,
            freshness=0.9,
            redundancy=0.1,
            overall=0.75,
        )
        reporter.report_quality(_make_pack(), quality)

        mock_fire.assert_called_once()
        url, payload, _, _ = mock_fire.call_args[0]
        assert url == "https://hook.example.com/quality"
        assert payload["event_type"] == "quality"
        assert payload["quality_overall"] == 0.75
        assert payload["quality_density"] == 0.8
        assert payload["quality_diversity"] == 0.6
        assert payload["selected_count"] == 2

    @patch("context_engineering.webhook._fire_webhook")
    def test_no_call_when_no_quality_url(self, mock_fire):
        reporter = WebhookReporter(
            analytics_url="https://hook.example.com",
            handoff_url="",
            quality_url="",
            cost_url="",
            session_id="s",
            model="m",
            strategy="s",
            timeout_s=5.0,
            headers={},
        )

        quality = ContextQuality(
            item_count=2, total_tokens=300, density=0.8,
            diversity=0.6, freshness=0.9, redundancy=0.1, overall=0.75,
        )
        reporter.report_quality(_make_pack(), quality)
        mock_fire.assert_not_called()


class TestReportCost:
    @patch("context_engineering.webhook._fire_webhook")
    def test_sends_cost_payload(self, mock_fire):
        reporter = WebhookReporter(
            analytics_url="",
            handoff_url="",
            quality_url="",
            cost_url="https://hook.example.com/cost",
            session_id="s",
            model="m",
            strategy="s",
            timeout_s=5.0,
            headers={},
        )

        cost = CostEstimate(
            model="claude-sonnet-4-6",
            input_tokens=300,
            cached_tokens=200,
            uncached_tokens=100,
            output_tokens=500,
            cost_without_cache=0.02,
            cost_with_cache=0.01,
            savings=0.01,
            savings_percent=50.0,
            cache_efficiency=0.67,
        )
        reporter.report_cost(_make_pack(), cost, cache_hit_ratio=0.8)

        mock_fire.assert_called_once()
        url, payload, _, _ = mock_fire.call_args[0]
        assert url == "https://hook.example.com/cost"
        assert payload["event_type"] == "cost"
        assert payload["cost_with_cache"] == 0.01
        assert payload["cost_without_cache"] == 0.02
        assert payload["cache_hit_ratio"] == 0.8
        assert payload["total_tokens"] == 300

    @patch("context_engineering.webhook._fire_webhook")
    def test_no_call_when_no_cost_url(self, mock_fire):
        reporter = WebhookReporter(
            analytics_url="https://hook.example.com",
            handoff_url="",
            quality_url="",
            cost_url="",
            session_id="s",
            model="m",
            strategy="s",
            timeout_s=5.0,
            headers={},
        )

        cost = CostEstimate(
            model="m", input_tokens=300, cached_tokens=200, uncached_tokens=100,
            output_tokens=500, cost_without_cache=0.02, cost_with_cache=0.01,
            savings=0.01, savings_percent=50.0, cache_efficiency=0.67,
        )
        reporter.report_cost(_make_pack(), cost)
        mock_fire.assert_not_called()


class TestNoopReporter:
    @patch("context_engineering.webhook._fire_webhook")
    def test_makes_no_calls(self, mock_fire):
        noop_reporter.report_pack(_make_pack())
        noop_reporter.report_trace(_make_trace())
        noop_reporter.report_handoff(_FakeHandoff())
        noop_reporter.report_pipeline(None)
        noop_reporter.report_quality(_make_pack(), None)
        noop_reporter.report_cost(_make_pack(), None)
        mock_fire.assert_not_called()
