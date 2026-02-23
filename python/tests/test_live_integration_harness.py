from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from context_framework.live_integration_harness import LiveIntegrationHarness


class LiveIntegrationHarnessTests(unittest.TestCase):
    def test_available_checks(self) -> None:
        harness = LiveIntegrationHarness()
        checks = harness.available_checks()
        self.assertIn("framework_bridges", checks)
        self.assertIn("ollama_local", checks)
        self.assertIn("ollama_cloud", checks)
        self.assertIn("anthropic_agentic", checks)
        self.assertIn("tri_provider_live", checks)

    def test_run_subset_framework_only(self) -> None:
        harness = LiveIntegrationHarness()
        report = harness.run(["framework_bridges"])

        self.assertTrue(report.success)
        self.assertEqual(report.passed, 1)
        self.assertEqual(report.failed, 0)
        self.assertEqual(report.skipped, 0)
        self.assertEqual(report.checks[0].check, "framework_bridges")

    def test_run_default_with_env_gates(self) -> None:
        harness = LiveIntegrationHarness()
        with patch.dict(os.environ, {}, clear=True):
            report = harness.run()

        statuses = {row.check: row.status for row in report.checks}
        self.assertEqual(statuses["framework_bridges"], "passed")
        self.assertEqual(statuses["ollama_local"], "skipped")
        self.assertEqual(statuses["ollama_cloud"], "skipped")
        self.assertEqual(statuses["anthropic_agentic"], "skipped")
        self.assertEqual(statuses["tri_provider_live"], "skipped")

    def test_strict_fails_when_skipped(self) -> None:
        harness = LiveIntegrationHarness(strict=True)
        with patch.dict(os.environ, {}, clear=True):
            report = harness.run(["ollama_local"])

        self.assertFalse(report.success)
        self.assertEqual(report.skipped, 1)

    def test_unknown_check_raises(self) -> None:
        harness = LiveIntegrationHarness()
        with self.assertRaises(ValueError):
            harness.run(["unknown_check"])

    def test_select_ollama_model_prefers_available_when_default_missing(self) -> None:
        class _Bridge:
            model = "llama3.1:8b"

        with patch.dict(os.environ, {}, clear=True):
            selected = LiveIntegrationHarness._select_ollama_model(
                _Bridge(),
                ("gpt-oss:120b",),
            )
        self.assertEqual(selected, "gpt-oss:120b")


if __name__ == "__main__":
    unittest.main()
