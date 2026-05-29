"""
Closed-Loop Budget Tuning & A/B Scoring Weights

Fetches budget recommendations and scoring weight configurations from
external HTTP endpoints, enabling:
1. Closed-loop budget tuning - telemetry informs future budget decisions
2. A/B testing of scoring weights - experiment with different packing strategies

Design: never raises. Returns fallback values on any failure (network,
timeout, malformed response).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

try:
    import httpx
except ImportError:  # httpx is an optional extra (providers / server / webhooks)
    httpx = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class BudgetRecommendation:
    """A budget recommendation from an external source."""

    max_tokens: int
    confidence: float
    """0-1, how confident the recommendation is."""
    source: str
    """'make.com' | 'custom' | 'default'"""
    reserve_tokens: Optional[int] = None
    reason: Optional[str] = None
    """Human-readable reason for the recommendation."""


@dataclass
class WeightConfig:
    """Scoring weight configuration for A/B testing."""

    id: str
    """Config identifier for A/B tracking."""
    priority: float
    recency: float
    salience: float
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class RecommendationOptions:
    """Configuration for recommendation fetching."""

    budget_url: Optional[str] = None
    """URL to fetch budget recommendations from."""
    weights_url: Optional[str] = None
    """URL to fetch weight configs from."""
    timeout_s: float = 3.0
    """Timeout in seconds (default: 3.0)."""
    headers: Dict[str, str] = field(default_factory=dict)
    """Headers to send with requests."""
    fallback_budget: Optional[int] = None
    """Fallback budget if fetch fails."""
    fallback_weights: Optional[Dict[str, float]] = None
    """Fallback weights if fetch fails (keys: priority, recency, salience)."""


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_BUDGET = 128_000
_DEFAULT_WEIGHTS = {"priority": 1.0, "recency": 0.7, "salience": 0.5}


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def recommendation_options_from_env() -> RecommendationOptions:
    """Create RecommendationOptions from environment variables.

    Reads ``CE_BUDGET_URL`` and ``CE_WEIGHTS_URL``.
    """
    return RecommendationOptions(
        budget_url=os.environ.get("CE_BUDGET_URL"),
        weights_url=os.environ.get("CE_WEIGHTS_URL"),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_url(base_url: str, session_id: str) -> str:
    """Append sessionId query parameter to a URL."""
    parsed = urlparse(base_url)
    existing = parse_qs(parsed.query)
    existing["sessionId"] = [session_id]
    new_query = urlencode(existing, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _fetch_json(
    url: str,
    timeout_s: float,
    headers: Dict[str, str],
) -> Any:
    """Fetch JSON from a URL. Returns None on any failure."""
    if httpx is None:
        logger.warning(
            "Recommendation fetch skipped for %s: httpx is not installed "
            "(install context-engineering[providers])",
            url,
        )
        return None
    try:
        merged_headers = {"Accept": "application/json", **headers}
        response = httpx.get(url, headers=merged_headers, timeout=timeout_s)

        if response.status_code != 200:
            logger.warning(
                "Recommendation fetch returned non-OK status: %d from %s",
                response.status_code,
                url,
            )
            return None

        return response.json()
    except Exception as exc:
        logger.warning("Recommendation fetch failed for %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_budget_recommendation(
    session_id: str,
    options: Optional[RecommendationOptions] = None,
) -> BudgetRecommendation:
    """Fetch a budget recommendation from an external source.

    Returns the recommendation, or a fallback if the fetch fails.
    Never raises -- always returns a usable value.

    Args:
        session_id: Session identifier sent as a query parameter.
        options: Configuration (URLs, timeout, fallbacks).

    Example::

        rec = fetch_budget_recommendation("session-123", RecommendationOptions(
            budget_url="https://hook.make.com/budget",
        ))
        budget = Budget(max_tokens=rec.max_tokens, reserve_tokens=rec.reserve_tokens)
    """
    opts = options or RecommendationOptions()
    env = recommendation_options_from_env()
    url = opts.budget_url or env.budget_url
    fallback_budget = opts.fallback_budget or _DEFAULT_BUDGET

    if not url:
        logger.debug("No budget URL configured, returning fallback")
        return BudgetRecommendation(
            max_tokens=fallback_budget,
            confidence=0,
            source="default",
            reason="No recommendation source configured",
        )

    full_url = _build_url(url, session_id)
    data = _fetch_json(full_url, opts.timeout_s, opts.headers)

    if not isinstance(data, dict):
        return BudgetRecommendation(
            max_tokens=fallback_budget,
            confidence=0,
            source="default",
            reason="Fetch failed or returned invalid data",
        )

    max_tokens = data.get("maxTokens")
    if not isinstance(max_tokens, (int, float)) or max_tokens <= 0:
        max_tokens = fallback_budget
    else:
        max_tokens = int(max_tokens)

    reserve_tokens = data.get("reserveTokens")
    if not isinstance(reserve_tokens, (int, float)):
        reserve_tokens = None
    else:
        reserve_tokens = int(reserve_tokens)

    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = 0.5
    else:
        confidence = max(0.0, min(1.0, float(confidence)))

    source = data.get("source")
    if not isinstance(source, str):
        source = "custom"

    reason = data.get("reason")
    if not isinstance(reason, str):
        reason = None

    return BudgetRecommendation(
        max_tokens=max_tokens,
        reserve_tokens=reserve_tokens,
        confidence=confidence,
        source=source,
        reason=reason,
    )


def fetch_weight_config(
    session_id: str,
    options: Optional[RecommendationOptions] = None,
) -> WeightConfig:
    """Fetch scoring weight config from an external source (for A/B testing).

    Returns a weight config with an ID for analytics tracking.
    Never raises -- always returns a usable value.

    Args:
        session_id: Session identifier sent as a query parameter.
        options: Configuration (URLs, timeout, fallbacks).

    Example::

        config = fetch_weight_config("session-123", RecommendationOptions(
            weights_url="https://hook.make.com/weights",
        ))
        scorer = create_scorer(ScoringWeights(
            priority=config.priority,
            recency=config.recency,
            salience=config.salience,
        ))
    """
    opts = options or RecommendationOptions()
    env = recommendation_options_from_env()
    url = opts.weights_url or env.weights_url
    fallback = opts.fallback_weights or _DEFAULT_WEIGHTS

    if not url:
        logger.debug("No weights URL configured, returning fallback")
        return WeightConfig(
            id="default",
            priority=fallback["priority"],
            recency=fallback["recency"],
            salience=fallback["salience"],
        )

    full_url = _build_url(url, session_id)
    data = _fetch_json(full_url, opts.timeout_s, opts.headers)

    if not isinstance(data, dict):
        return WeightConfig(
            id="default",
            priority=fallback["priority"],
            recency=fallback["recency"],
            salience=fallback["salience"],
        )

    config_id = data.get("id")
    if not isinstance(config_id, str):
        config_id = "default"

    priority = data.get("priority")
    if not isinstance(priority, (int, float)):
        priority = fallback["priority"]
    else:
        priority = float(priority)

    recency = data.get("recency")
    if not isinstance(recency, (int, float)):
        recency = fallback["recency"]
    else:
        recency = float(recency)

    salience = data.get("salience")
    if not isinstance(salience, (int, float)):
        salience = fallback["salience"]
    else:
        salience = float(salience)

    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        metadata = None

    return WeightConfig(
        id=config_id,
        priority=priority,
        recency=recency,
        salience=salience,
        metadata=metadata,
    )
