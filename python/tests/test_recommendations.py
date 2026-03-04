"""Tests for closed-loop budget tuning and A/B scoring weights."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from context_engineering.recommendations import (
    BudgetRecommendation,
    RecommendationOptions,
    WeightConfig,
    fetch_budget_recommendation,
    fetch_weight_config,
    recommendation_options_from_env,
)


# ---------------------------------------------------------------------------
# Budget Recommendation
# ---------------------------------------------------------------------------


class TestFetchBudgetRecommendation:
    def test_returns_fallback_when_no_url_configured(self):
        rec = fetch_budget_recommendation("sess-1")

        assert rec.max_tokens == 128_000
        assert rec.confidence == 0
        assert rec.source == "default"
        assert "No recommendation source" in (rec.reason or "")

    def test_returns_custom_fallback_budget(self):
        opts = RecommendationOptions(fallback_budget=64_000)
        rec = fetch_budget_recommendation("sess-1", opts)

        assert rec.max_tokens == 64_000

    @patch("context_engineering.recommendations.httpx")
    def test_returns_fallback_on_fetch_failure(self, mock_httpx):
        mock_httpx.get.side_effect = httpx.ConnectError("connection refused")

        opts = RecommendationOptions(budget_url="https://example.com/budget")
        rec = fetch_budget_recommendation("sess-1", opts)

        assert rec.max_tokens == 128_000
        assert rec.confidence == 0
        assert rec.source == "default"

    @patch("context_engineering.recommendations.httpx")
    def test_returns_fallback_on_timeout(self, mock_httpx):
        mock_httpx.get.side_effect = httpx.TimeoutException("timed out")

        opts = RecommendationOptions(
            budget_url="https://example.com/budget",
            timeout_s=0.01,
        )
        rec = fetch_budget_recommendation("sess-1", opts)

        assert rec.max_tokens == 128_000
        assert rec.source == "default"

    @patch("context_engineering.recommendations.httpx")
    def test_returns_fallback_on_non_ok_response(self, mock_httpx):
        response = MagicMock()
        response.status_code = 404
        mock_httpx.get.return_value = response

        opts = RecommendationOptions(budget_url="https://example.com/budget")
        rec = fetch_budget_recommendation("sess-1", opts)

        assert rec.max_tokens == 128_000
        assert rec.source == "default"

    @patch("context_engineering.recommendations.httpx")
    def test_returns_recommendation_from_valid_response(self, mock_httpx):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "maxTokens": 96_000,
            "reserveTokens": 4_000,
            "confidence": 0.85,
            "source": "make.com",
            "reason": "Based on recent usage patterns",
        }
        mock_httpx.get.return_value = response

        opts = RecommendationOptions(budget_url="https://example.com/budget")
        rec = fetch_budget_recommendation("sess-1", opts)

        assert rec.max_tokens == 96_000
        assert rec.reserve_tokens == 4_000
        assert rec.confidence == 0.85
        assert rec.source == "make.com"
        assert rec.reason == "Based on recent usage patterns"

    @patch("context_engineering.recommendations.httpx")
    def test_clamps_confidence_to_0_1(self, mock_httpx):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"maxTokens": 50_000, "confidence": 1.5}
        mock_httpx.get.return_value = response

        opts = RecommendationOptions(budget_url="https://example.com/budget")
        rec = fetch_budget_recommendation("sess-1", opts)

        assert rec.confidence == 1.0

    @patch("context_engineering.recommendations.httpx")
    def test_handles_malformed_json(self, mock_httpx):
        response = MagicMock()
        response.status_code = 200
        response.json.side_effect = ValueError("bad json")
        mock_httpx.get.return_value = response

        opts = RecommendationOptions(budget_url="https://example.com/budget")
        rec = fetch_budget_recommendation("sess-1", opts)

        assert rec.max_tokens == 128_000
        assert rec.source == "default"

    @patch.dict("os.environ", {"CE_BUDGET_URL": "https://env.example.com/budget"})
    @patch("context_engineering.recommendations.httpx")
    def test_reads_from_env_vars(self, mock_httpx):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "maxTokens": 80_000,
            "confidence": 0.6,
            "source": "env",
        }
        mock_httpx.get.return_value = response

        rec = fetch_budget_recommendation("sess-1")

        mock_httpx.get.assert_called_once()
        call_url = mock_httpx.get.call_args[0][0]
        assert "env.example.com" in call_url
        assert rec.max_tokens == 80_000

    @patch.dict("os.environ", {"CE_BUDGET_URL": "https://env.example.com/budget"})
    @patch("context_engineering.recommendations.httpx")
    def test_explicit_url_overrides_env_var(self, mock_httpx):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"maxTokens": 70_000, "confidence": 0.9}
        mock_httpx.get.return_value = response

        opts = RecommendationOptions(
            budget_url="https://explicit.example.com/budget"
        )
        rec = fetch_budget_recommendation("sess-1", opts)

        call_url = mock_httpx.get.call_args[0][0]
        assert "explicit.example.com" in call_url
        assert "env.example.com" not in call_url
        assert rec.max_tokens == 70_000

    @patch("context_engineering.recommendations.httpx")
    def test_appends_session_id_as_query_param(self, mock_httpx):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"maxTokens": 50_000, "confidence": 0.5}
        mock_httpx.get.return_value = response

        opts = RecommendationOptions(budget_url="https://example.com/budget")
        fetch_budget_recommendation("my-session", opts)

        call_url = mock_httpx.get.call_args[0][0]
        assert "sessionId=my-session" in call_url

    @patch("context_engineering.recommendations.httpx")
    def test_sends_custom_headers(self, mock_httpx):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"maxTokens": 50_000, "confidence": 0.5}
        mock_httpx.get.return_value = response

        opts = RecommendationOptions(
            budget_url="https://example.com/budget",
            headers={"Authorization": "Bearer test-token"},
        )
        fetch_budget_recommendation("sess-1", opts)

        call_kwargs = mock_httpx.get.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer test-token"


# ---------------------------------------------------------------------------
# Weight Config
# ---------------------------------------------------------------------------


class TestFetchWeightConfig:
    def test_returns_fallback_when_no_url_configured(self):
        config = fetch_weight_config("sess-1")

        assert config.id == "default"
        assert config.priority == 1.0
        assert config.recency == 0.7
        assert config.salience == 0.5

    def test_returns_custom_fallback_weights(self):
        opts = RecommendationOptions(
            fallback_weights={"priority": 2.0, "recency": 0.5, "salience": 0.3}
        )
        config = fetch_weight_config("sess-1", opts)

        assert config.priority == 2.0
        assert config.recency == 0.5
        assert config.salience == 0.3

    @patch("context_engineering.recommendations.httpx")
    def test_returns_weight_config_from_valid_response(self, mock_httpx):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "id": "experiment-42",
            "priority": 1.5,
            "recency": 0.3,
            "salience": 0.8,
            "metadata": {"variant": "B"},
        }
        mock_httpx.get.return_value = response

        opts = RecommendationOptions(weights_url="https://example.com/weights")
        config = fetch_weight_config("sess-1", opts)

        assert config.id == "experiment-42"
        assert config.priority == 1.5
        assert config.recency == 0.3
        assert config.salience == 0.8
        assert config.metadata == {"variant": "B"}

    @patch("context_engineering.recommendations.httpx")
    def test_returns_fallback_on_fetch_failure(self, mock_httpx):
        mock_httpx.get.side_effect = httpx.ConnectError("connection refused")

        opts = RecommendationOptions(weights_url="https://example.com/weights")
        config = fetch_weight_config("sess-1", opts)

        assert config.id == "default"
        assert config.priority == 1.0
        assert config.recency == 0.7
        assert config.salience == 0.5

    @patch("context_engineering.recommendations.httpx")
    def test_handles_malformed_json(self, mock_httpx):
        response = MagicMock()
        response.status_code = 200
        response.json.side_effect = ValueError("bad json")
        mock_httpx.get.return_value = response

        opts = RecommendationOptions(weights_url="https://example.com/weights")
        config = fetch_weight_config("sess-1", opts)

        assert config.id == "default"
        assert config.priority == 1.0

    @patch.dict("os.environ", {"CE_WEIGHTS_URL": "https://env.example.com/weights"})
    @patch("context_engineering.recommendations.httpx")
    def test_reads_from_env_vars(self, mock_httpx):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "id": "env-config",
            "priority": 2.0,
            "recency": 0.1,
            "salience": 0.9,
        }
        mock_httpx.get.return_value = response

        config = fetch_weight_config("sess-1")

        mock_httpx.get.assert_called_once()
        call_url = mock_httpx.get.call_args[0][0]
        assert "env.example.com" in call_url
        assert config.id == "env-config"

    @patch.dict("os.environ", {"CE_WEIGHTS_URL": "https://env.example.com/weights"})
    @patch("context_engineering.recommendations.httpx")
    def test_explicit_url_overrides_env_var(self, mock_httpx):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "id": "explicit-config",
            "priority": 1.2,
            "recency": 0.6,
            "salience": 0.4,
        }
        mock_httpx.get.return_value = response

        opts = RecommendationOptions(
            weights_url="https://explicit.example.com/weights"
        )
        config = fetch_weight_config("sess-1", opts)

        call_url = mock_httpx.get.call_args[0][0]
        assert "explicit.example.com" in call_url
        assert "env.example.com" not in call_url
        assert config.id == "explicit-config"


# ---------------------------------------------------------------------------
# recommendationOptionsFromEnv
# ---------------------------------------------------------------------------


class TestRecommendationOptionsFromEnv:
    @patch.dict(
        "os.environ",
        {
            "CE_BUDGET_URL": "https://budget.example.com",
            "CE_WEIGHTS_URL": "https://weights.example.com",
        },
    )
    def test_reads_env_vars(self):
        opts = recommendation_options_from_env()

        assert opts.budget_url == "https://budget.example.com"
        assert opts.weights_url == "https://weights.example.com"

    @patch.dict("os.environ", {}, clear=True)
    def test_returns_none_for_missing_env_vars(self):
        opts = recommendation_options_from_env()

        assert opts.budget_url is None
        assert opts.weights_url is None
