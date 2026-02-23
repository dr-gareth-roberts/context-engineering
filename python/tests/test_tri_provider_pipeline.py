from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from context_framework import TriProviderPipeline, USE_CASES


class TriProviderPipelineTests(unittest.TestCase):
    def test_dry_run_for_all_use_cases(self) -> None:
        for spec in USE_CASES:
            pipeline = TriProviderPipeline(spec)
            report = pipeline.run(
                scenario="Critical cross-system anomaly requiring immediate triage.",
                evidence_documents=("Evidence: suspicious user activity and host anomalies.",),
                mode="dry",
            )

            self.assertEqual(report.use_case_id, spec.use_case_id)
            self.assertTrue(report.openai_stage.success)
            self.assertTrue(report.anthropic_stage.success)
            self.assertTrue(report.cerebras_stage.success)
            self.assertGreater(report.context_tokens_used, 0)
            self.assertTrue(report.final_plan.strip())
            self.assertGreater(len(report.ranked_actions), 0)
            self.assertTrue(report.anthropic_stage.request.get("tools"))

    def test_soc_case_has_rich_ranked_actions(self) -> None:
        spec = next(s for s in USE_CASES if s.use_case_id == "soc_incident_commander")
        report = TriProviderPipeline(spec).run(
            scenario="Critical active compromise with suspected data exfiltration.",
            mode="dry",
        )
        self.assertGreaterEqual(len(report.ranked_actions), 3)
        self.assertIn("Primary Action:", report.final_plan)

    def test_all_use_case_scripts_execute_in_dry_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scripts = sorted((root / "examples" / "use_cases").glob("[0-9][0-9]_*.py"))
        self.assertGreaterEqual(len(scripts), 14)
        for script in scripts:
            result = subprocess.run(
                [sys.executable, str(script), "--mode", "dry", "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(result.stdout)
            self.assertIn("use_case_id", payload)
            self.assertIn("final_plan", payload)
            self.assertEqual(payload["mode"], "dry")

    def test_run_all_use_cases_script(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "examples" / "use_cases" / "run_all_use_cases.py"
        result = subprocess.run(
            [sys.executable, str(script), "--mode", "dry", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertGreaterEqual(len(payload), 14)
        ids = {item["use_case_id"] for item in payload}
        self.assertEqual(len(ids), len(payload))


if __name__ == "__main__":
    unittest.main()
