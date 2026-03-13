"""
Webhook Telemetry Integration

Fire-and-forget webhook reporting for pack/trace/handoff/pipeline/quality/cost.
Designed for Make.com scenario ingestion but works with any HTTP endpoint.

Usage::

    reporter = create_webhook_reporter(analytics_url="https://...")
    result = pack(items, budget)
    reporter.report_pack(result)

Or rely on env vars::

    # reads CE_WEBHOOK_URL, CE_WEBHOOK_HANDOFF_URL, CE_WEBHOOK_QUALITY_URL, CE_WEBHOOK_COST_URL
    reporter = create_webhook_reporter()
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from .core import ContextPack, ContextTrace
from .cost import CostEstimate
from .quality import ContextQuality

logger = logging.getLogger(__name__)

# ─── Payload Types ────────────────────────────────────────────────────


@dataclass
class WebhookAnalyticsPayload:
    event_type: str  # "pack" | "trace"
    session_id: str
    model: str
    strategy: str
    timestamp: str
    budget_max_tokens: int
    budget_reserve_tokens: int
    total_tokens: int
    selected_count: int
    dropped_count: int
    budget_utilization_pct: float
    remaining_tokens: int
    quality_overall: Optional[float] = None
    quality_density: Optional[float] = None
    quality_diversity: Optional[float] = None
    cost_with_cache: Optional[float] = None
    cost_without_cache: Optional[float] = None
    cache_hit_ratio: Optional[float] = None
    trace_decisions: Optional[str] = None


@dataclass
class WebhookHandoffPayload:
    event_type: str  # "handoff"
    session_id: str
    timestamp: str
    total_issues: int
    active_items: int
    deferred_items: int
    source_agent: Optional[str] = None
    target_url: Optional[str] = None
    jsonl_size_bytes: int = 0


@dataclass
class WebhookPipelinePayload:
    event_type: str  # "pipeline"
    session_id: str
    timestamp: str
    model: str
    strategy: str
    stages: List[str] = field(default_factory=list)
    input_count: int = 0
    selected_count: int = 0
    dropped_count: int = 0
    total_tokens: int = 0
    budget_max_tokens: int = 0
    budget_reserve_tokens: int = 0
    budget_utilization_pct: float = 0
    quality_overall: Optional[float] = None
    quality_density: Optional[float] = None
    quality_diversity: Optional[float] = None
    cache_efficiency: Optional[float] = None
    cacheable_tokens: Optional[int] = None
    cache_key: Optional[str] = None
    allocation_efficiency: Optional[float] = None
    allocations_json: Optional[str] = None
    placement_strategy: Optional[str] = None


@dataclass
class WebhookQualityPayload:
    event_type: str  # "quality"
    session_id: str
    timestamp: str
    model: str
    quality_overall: float = 0
    quality_density: float = 0
    quality_diversity: float = 0
    selected_count: int = 0
    dropped_count: int = 0
    budget_utilization_pct: float = 0


@dataclass
class WebhookCostPayload:
    event_type: str  # "cost"
    session_id: str
    timestamp: str
    model: str
    cost_with_cache: float = 0
    cost_without_cache: float = 0
    cache_hit_ratio: float = 0
    total_tokens: int = 0
    budget_max_tokens: int = 0


@dataclass
class PackReportExtras:
    quality: Optional[ContextQuality] = None
    cost: Optional[CostEstimate] = None
    cache_hit_ratio: Optional[float] = None


@dataclass
class HandoffReportExtras:
    source_agent: Optional[str] = None
    target_url: Optional[str] = None


@dataclass
class PipelineReportExtras:
    cost: Optional[CostEstimate] = None
    cache_hit_ratio: Optional[float] = None
    placement_strategy: Optional[str] = None


@dataclass
class WebhookOptions:
    analytics_url: Optional[str] = None
    handoff_url: Optional[str] = None
    quality_url: Optional[str] = None
    cost_url: Optional[str] = None
    session_id: Optional[str] = None
    model: Optional[str] = None
    strategy: Optional[str] = None
    timeout_s: float = 5.0
    headers: Dict[str, str] = field(default_factory=dict)


# ─── Internal Helpers ─────────────────────────────────────────────────


def _compute_utilization(total_tokens: int, max_tokens: int, reserve_tokens: int) -> float:
    effective = max_tokens - reserve_tokens
    return round((total_tokens / effective) * 10000) / 100 if effective > 0 else 0


def _fire_webhook(
    url: str,
    payload: Dict[str, Any],
    timeout_s: float,
    headers: Dict[str, str],
) -> None:
    """Send webhook in a daemon thread (fire-and-forget)."""

    def _send() -> None:
        try:
            httpx.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json", **headers},
                timeout=timeout_s,
            )
        except Exception as exc:
            logger.warning("webhook:send_failed url=%s error=%s", url, exc)

    t = threading.Thread(target=_send, daemon=True)
    t.start()


def _strip_none(d: Dict[str, Any]) -> Dict[str, Any]:
    """Remove None values from a dict for cleaner payloads."""
    return {k: v for k, v in d.items() if v is not None}


def _build_analytics_payload(
    pack: ContextPack,
    event_type: str,
    session_id: str,
    model: str,
    strategy: str,
    extras: Optional[PackReportExtras] = None,
    trace_decisions: Optional[str] = None,
) -> Dict[str, Any]:
    max_tokens = pack.budget.max_tokens
    reserve_tokens = pack.budget.reserve_tokens or 0
    utilization_pct = _compute_utilization(pack.total_tokens, max_tokens, reserve_tokens)

    payload: Dict[str, Any] = {
        "event_type": event_type,
        "session_id": session_id,
        "model": model,
        "strategy": strategy,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "budget_max_tokens": max_tokens,
        "budget_reserve_tokens": reserve_tokens,
        "total_tokens": pack.total_tokens,
        "selected_count": len(pack.selected),
        "dropped_count": len(pack.dropped),
        "budget_utilization_pct": utilization_pct,
        "remaining_tokens": max(0, max_tokens - reserve_tokens - pack.total_tokens),
    }

    if extras:
        if extras.quality:
            payload["quality_overall"] = extras.quality.overall
            payload["quality_density"] = extras.quality.density
            payload["quality_diversity"] = extras.quality.diversity
        if extras.cost:
            payload["cost_with_cache"] = extras.cost.cost_with_cache
            payload["cost_without_cache"] = extras.cost.cost_without_cache
        if extras.cache_hit_ratio is not None:
            payload["cache_hit_ratio"] = extras.cache_hit_ratio

    if trace_decisions is not None:
        payload["trace_decisions"] = trace_decisions

    return payload


def _build_pipeline_payload(
    result: Any,
    session_id: str,
    model: str,
    strategy: str,
    extras: Optional[PipelineReportExtras] = None,
) -> Dict[str, Any]:
    max_tokens = result.budget.max_tokens
    reserve_tokens = result.budget.reserve_tokens or 0

    payload: Dict[str, Any] = {
        "event_type": "pipeline",
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "strategy": strategy,
        "stages": list(result.stages),
        "input_count": result.input_count,
        "selected_count": len(result.selected),
        "dropped_count": len(result.dropped),
        "total_tokens": result.total_tokens,
        "budget_max_tokens": max_tokens,
        "budget_reserve_tokens": reserve_tokens,
        "budget_utilization_pct": _compute_utilization(
            result.total_tokens, max_tokens, reserve_tokens
        ),
    }

    if result.quality is not None:
        payload["quality_overall"] = result.quality.overall
        payload["quality_density"] = result.quality.density
        payload["quality_diversity"] = result.quality.diversity
    if result.cache_efficiency is not None:
        payload["cache_efficiency"] = result.cache_efficiency
    if result.cacheable_tokens is not None:
        payload["cacheable_tokens"] = result.cacheable_tokens
    if result.cache_key is not None:
        payload["cache_key"] = result.cache_key
    if result.allocation_efficiency is not None:
        payload["allocation_efficiency"] = result.allocation_efficiency
    if result.allocations is not None:
        payload["allocations_json"] = json.dumps(result.allocations)
    if extras and extras.placement_strategy:
        payload["placement_strategy"] = extras.placement_strategy

    return payload


# ─── Reporter Protocol ────────────────────────────────────────────────


class WebhookReporter:
    """Webhook reporter that sends telemetry for pack/trace/handoff/pipeline/quality/cost."""

    def __init__(
        self,
        analytics_url: str,
        handoff_url: str,
        quality_url: str,
        cost_url: str,
        session_id: str,
        model: str,
        strategy: str,
        timeout_s: float,
        headers: Dict[str, str],
    ) -> None:
        self._analytics_url = analytics_url
        self._handoff_url = handoff_url
        self._quality_url = quality_url
        self._cost_url = cost_url
        self._session_id = session_id
        self._model = model
        self._strategy = strategy
        self._timeout_s = timeout_s
        self._headers = headers

    def report_pack(
        self,
        pack: ContextPack,
        extras: Optional[PackReportExtras] = None,
    ) -> None:
        if not self._analytics_url:
            return
        payload = _build_analytics_payload(
            pack, "pack", self._session_id, self._model, self._strategy, extras
        )
        _fire_webhook(self._analytics_url, payload, self._timeout_s, self._headers)

    def report_trace(
        self,
        trace: ContextTrace,
        extras: Optional[PackReportExtras] = None,
    ) -> None:
        if not self._analytics_url:
            return
        decisions = json.dumps(
            [
                {
                    "id": s.id,
                    "decision": s.decision,
                    "tokens": s.tokens,
                    "reason": s.reason,
                }
                for s in trace.steps
            ]
        )
        payload = _build_analytics_payload(
            trace.pack,
            "trace",
            self._session_id,
            self._model,
            self._strategy,
            extras,
            decisions,
        )
        _fire_webhook(self._analytics_url, payload, self._timeout_s, self._headers)

    def report_handoff(
        self,
        handoff: Any,
        extras: Optional[HandoffReportExtras] = None,
    ) -> None:
        if not self._handoff_url:
            return
        stats = handoff.stats if hasattr(handoff, "stats") else handoff.get("stats", {})
        jsonl = handoff.jsonl if hasattr(handoff, "jsonl") else handoff.get("jsonl", "")
        payload: Dict[str, Any] = {
            "event_type": "handoff",
            "session_id": self._session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_issues": stats.get("totalIssues", 0)
            if isinstance(stats, dict)
            else getattr(stats, "total_issues", 0),
            "active_items": stats.get("activeItems", 0)
            if isinstance(stats, dict)
            else getattr(stats, "active_items", 0),
            "deferred_items": stats.get("deferredItems", 0)
            if isinstance(stats, dict)
            else getattr(stats, "deferred_items", 0),
            "jsonl_size_bytes": len(jsonl.encode("utf-8")),
        }
        if extras:
            if extras.source_agent:
                payload["source_agent"] = extras.source_agent
            if extras.target_url:
                payload["target_url"] = extras.target_url
        _fire_webhook(self._handoff_url, payload, self._timeout_s, self._headers)

    def report_pipeline(
        self,
        result: Any,
        extras: Optional[PipelineReportExtras] = None,
    ) -> None:
        if not self._analytics_url:
            return
        payload = _build_pipeline_payload(
            result, self._session_id, self._model, self._strategy, extras
        )
        _fire_webhook(self._analytics_url, payload, self._timeout_s, self._headers)

    def report_quality(
        self,
        pack: ContextPack,
        quality: ContextQuality,
    ) -> None:
        if not self._quality_url:
            return
        max_tokens = pack.budget.max_tokens
        reserve_tokens = pack.budget.reserve_tokens or 0
        payload: Dict[str, Any] = {
            "event_type": "quality",
            "session_id": self._session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": self._model,
            "quality_overall": quality.overall,
            "quality_density": quality.density,
            "quality_diversity": quality.diversity,
            "selected_count": len(pack.selected),
            "dropped_count": len(pack.dropped),
            "budget_utilization_pct": _compute_utilization(
                pack.total_tokens, max_tokens, reserve_tokens
            ),
        }
        _fire_webhook(self._quality_url, payload, self._timeout_s, self._headers)

    def report_cost(
        self,
        pack: ContextPack,
        cost: CostEstimate,
        cache_hit_ratio: Optional[float] = None,
    ) -> None:
        if not self._cost_url:
            return
        payload: Dict[str, Any] = {
            "event_type": "cost",
            "session_id": self._session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": self._model,
            "cost_with_cache": cost.cost_with_cache,
            "cost_without_cache": cost.cost_without_cache,
            "cache_hit_ratio": cache_hit_ratio
            if cache_hit_ratio is not None
            else cost.cache_efficiency,
            "total_tokens": cost.input_tokens,
            "budget_max_tokens": pack.budget.max_tokens,
        }
        _fire_webhook(self._cost_url, payload, self._timeout_s, self._headers)


class _NoopReporter:
    """No-op reporter that never sends anything."""

    def report_pack(self, pack: Any, extras: Any = None) -> None:
        pass

    def report_trace(self, trace: Any, extras: Any = None) -> None:
        pass

    def report_handoff(self, handoff: Any, extras: Any = None) -> None:
        pass

    def report_pipeline(self, result: Any, extras: Any = None) -> None:
        pass

    def report_quality(self, pack: Any, quality: Any) -> None:
        pass

    def report_cost(self, pack: Any, cost: Any, cache_hit_ratio: Any = None) -> None:
        pass


noop_reporter = _NoopReporter()


# ─── Factory ──────────────────────────────────────────────────────────


def create_webhook_reporter(
    analytics_url: Optional[str] = None,
    handoff_url: Optional[str] = None,
    quality_url: Optional[str] = None,
    cost_url: Optional[str] = None,
    session_id: Optional[str] = None,
    model: Optional[str] = None,
    strategy: Optional[str] = None,
    timeout_s: float = 5.0,
    headers: Optional[Dict[str, str]] = None,
) -> WebhookReporter | _NoopReporter:
    """Create a webhook reporter for telemetry.

    Reads env vars as defaults:
    - ``CE_WEBHOOK_URL`` -- pack/trace analytics
    - ``CE_WEBHOOK_HANDOFF_URL`` -- handoff events
    - ``CE_WEBHOOK_QUALITY_URL`` -- quality regression reports
    - ``CE_WEBHOOK_COST_URL`` -- cost anomaly reports

    Returns a no-op reporter when no URL is configured.
    """
    resolved_analytics = analytics_url or os.environ.get("CE_WEBHOOK_URL", "")
    resolved_handoff = handoff_url or os.environ.get("CE_WEBHOOK_HANDOFF_URL", "")
    resolved_quality = quality_url or os.environ.get("CE_WEBHOOK_QUALITY_URL", "")
    resolved_cost = cost_url or os.environ.get("CE_WEBHOOK_COST_URL", "")

    if (
        not resolved_analytics
        and not resolved_handoff
        and not resolved_quality
        and not resolved_cost
    ):
        return noop_reporter

    import time

    resolved_session = session_id or f"ce-{int(time.time()):x}"

    return WebhookReporter(
        analytics_url=resolved_analytics,
        handoff_url=resolved_handoff,
        quality_url=resolved_quality,
        cost_url=resolved_cost,
        session_id=resolved_session,
        model=model or "unknown",
        strategy=strategy or "greedy-score",
        timeout_s=timeout_s,
        headers=headers or {},
    )
