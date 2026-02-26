from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from context_framework import (
    USE_CASE_INDEX,
    InMemoryComplianceActionAdapter,
    InMemoryControlCoverageAdapter,
    InMemoryRegulationIntelAdapter,
    RegulatoryChangeCommander,
    RegulatoryExecutionPolicy,
    TriProviderPipeline,
)


class _FlakyRegulationIntelAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def lookup_requirement(self, requirement_id: str):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("timeout contacting regulation-intel service")
        return {
            "requirement_id": requirement_id,
            "obligation_severity": 0.86,
            "deadline_days": 40,
            "penalty_risk": 0.82,
            "obligations_count": 9,
        }


class _SleepyRegulationIntelAdapter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def lookup_requirement(self, requirement_id: str):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return {
            "requirement_id": requirement_id,
            "obligation_severity": 0.52,
            "deadline_days": 130,
            "penalty_risk": 0.40,
            "obligations_count": 5,
        }


class RegulatoryChangeRuntimeTests(unittest.TestCase):
    def _pipeline(self) -> TriProviderPipeline:
        spec = USE_CASE_INDEX["regulatory_change_impact"]
        return TriProviderPipeline(spec)

    def test_extract_signals(self) -> None:
        rows = RegulatoryChangeCommander.extract_signals(
            "REG-AI-2026 DOMAIN-MODEL-RISK TEAM-GOV mandatory 120 days model inventory obligations"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].requirement_id, "REG-AI-2026")
        self.assertEqual(rows[0].domain_id, "DOMAIN-MODEL-RISK")
        self.assertEqual(rows[0].owner_id, "TEAM-GOV")
        self.assertEqual(rows[0].observed_deadline_days, 120)
        self.assertEqual(rows[0].obligation_hint, "model inventory")
        self.assertTrue(rows[0].enforcement_indicator)

    def test_extract_signals_preserves_event_alignment(self) -> None:
        rows = RegulatoryChangeCommander.extract_signals(
            "REG-AI-2026 applies to DOMAIN-MODEL-RISK owned by TEAM-GOV with 120 days. "
            "REG-OPS-771 applies to DOMAIN-INCIDENT-REPORTING owned by TEAM-SEC with 45 days."
        )
        by_req = {row.requirement_id: row for row in rows}
        self.assertEqual(by_req["REG-AI-2026"].domain_id, "DOMAIN-MODEL-RISK")
        self.assertEqual(by_req["REG-AI-2026"].owner_id, "TEAM-GOV")
        self.assertEqual(by_req["REG-OPS-771"].domain_id, "DOMAIN-INCIDENT-REPORTING")
        self.assertEqual(by_req["REG-OPS-771"].owner_id, "TEAM-SEC")
        self.assertEqual(by_req["REG-OPS-771"].observed_deadline_days, 45)

    def test_extract_signals_avoids_generic_phrase_false_positive(self) -> None:
        rows = RegulatoryChangeCommander.extract_signals(
            "Regulatory change briefing: REG-AI-2026 and REG-OPS-771 affect two policy domains."
        )
        ids = [row.requirement_id for row in rows]
        self.assertEqual(ids, ["REG-AI-2026", "REG-OPS-771"])

    def test_dry_mode_gates_actions_by_default(self) -> None:
        commander = RegulatoryChangeCommander(
            pipeline=self._pipeline(),
            regulation_intel_adapter=InMemoryRegulationIntelAdapter(
                requirements={
                    "REG-AI-2026": {
                        "obligation_severity": 0.76,
                        "deadline_days": 90,
                        "penalty_risk": 0.62,
                        "obligations_count": 10,
                    }
                }
            ),
            control_coverage_adapter=InMemoryControlCoverageAdapter(
                domains={
                    "DOMAIN-MODEL-RISK": {
                        "coverage_pct": 0.56,
                        "open_findings": 6,
                        "evidence_freshness_days": 112,
                    }
                }
            ),
            compliance_action_adapter=InMemoryComplianceActionAdapter(),
            execution_policy=RegulatoryExecutionPolicy(execute_actions_in_dry_run=False),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="REG-AI-2026 DOMAIN-MODEL-RISK TEAM-GOV mandatory 90 days",
            mode="dry",
        )

        self.assertGreaterEqual(len(report.actions), 1)
        self.assertTrue(all(row.status == "skipped" for row in report.actions))
        self.assertIn("dry mode", " ".join(report.warnings).lower())

    def test_idempotency_skips_repeat_actions(self) -> None:
        action_adapter = InMemoryComplianceActionAdapter()
        commander = RegulatoryChangeCommander(
            pipeline=self._pipeline(),
            regulation_intel_adapter=InMemoryRegulationIntelAdapter(
                requirements={
                    "REG-OPS-771": {
                        "obligation_severity": 0.90,
                        "deadline_days": 30,
                        "penalty_risk": 0.88,
                        "obligations_count": 11,
                    }
                }
            ),
            control_coverage_adapter=InMemoryControlCoverageAdapter(
                domains={
                    "DOMAIN-INCIDENT-REPORTING": {
                        "coverage_pct": 0.44,
                        "open_findings": 9,
                        "evidence_freshness_days": 120,
                    }
                }
            ),
            compliance_action_adapter=action_adapter,
            execution_policy=RegulatoryExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        scenario = "REG-OPS-771 DOMAIN-INCIDENT-REPORTING TEAM-SEC mandatory 30 days"
        first = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})
        second = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})

        self.assertTrue(any(row.status == "executed" for row in first.actions))
        self.assertTrue(all(row.status == "skipped" for row in second.actions))
        self.assertEqual(len(action_adapter.remediation_programs), 1)
        self.assertEqual(len(action_adapter.control_gap_domains), 1)
        self.assertEqual(len(action_adapter.policy_updates), 1)
        self.assertEqual(len(action_adapter.attestations), 1)

    def test_high_risk_routes_immediate_remediation_program(self) -> None:
        commander = RegulatoryChangeCommander(
            pipeline=self._pipeline(),
            regulation_intel_adapter=InMemoryRegulationIntelAdapter(
                requirements={
                    "REG-OPS-771": {
                        "obligation_severity": 0.92,
                        "deadline_days": 35,
                        "penalty_risk": 0.90,
                        "obligations_count": 12,
                    }
                }
            ),
            control_coverage_adapter=InMemoryControlCoverageAdapter(
                domains={
                    "DOMAIN-INCIDENT-REPORTING": {
                        "coverage_pct": 0.39,
                        "open_findings": 10,
                        "evidence_freshness_days": 134,
                    }
                }
            ),
            compliance_action_adapter=InMemoryComplianceActionAdapter(),
            execution_policy=RegulatoryExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="REG-OPS-771 DOMAIN-INCIDENT-REPORTING TEAM-SEC mandatory 35 days",
            mode="dry",
        )

        self.assertEqual(report.decisions[0].route, "immediate_remediation_program")
        ops = {row.operation for row in report.actions if row.status == "executed"}
        self.assertIn("open_remediation_program", ops)
        self.assertIn("create_control_gap_tasks", ops)
        self.assertIn("publish_policy_update", ops)
        self.assertIn("schedule_attestation", ops)
        self.assertIn("assign_training", ops)

    def test_retry_recovers_from_transient_regulation_intel_failure(self) -> None:
        flaky = _FlakyRegulationIntelAdapter()
        commander = RegulatoryChangeCommander(
            pipeline=self._pipeline(),
            regulation_intel_adapter=flaky,
            control_coverage_adapter=InMemoryControlCoverageAdapter(),
            compliance_action_adapter=InMemoryComplianceActionAdapter(),
            execution_policy=RegulatoryExecutionPolicy(execute_actions_in_dry_run=False),
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="REG-OPS-771 DOMAIN-INCIDENT-REPORTING TEAM-SEC mandatory 40 days",
            mode="dry",
        )

        self.assertEqual(flaky.calls, 2)
        intel_row = next(row for row in report.enrichments if row.integration == "regulation_intel")
        self.assertTrue(intel_row.success)
        self.assertEqual(intel_row.retried, 1)
        self.assertEqual(intel_row.attempts, 2)

    def test_parallel_regulation_intel_enrichment_reduces_latency(self) -> None:
        sleepy = _SleepyRegulationIntelAdapter(delay_seconds=0.08)
        commander = RegulatoryChangeCommander(
            pipeline=self._pipeline(),
            regulation_intel_adapter=sleepy,
            control_coverage_adapter=InMemoryControlCoverageAdapter(),
            compliance_action_adapter=InMemoryComplianceActionAdapter(),
            execution_policy=RegulatoryExecutionPolicy(
                execute_actions_in_dry_run=False,
                max_parallel_tasks=8,
            ),
            retry_backoff_seconds=0.0,
        )

        scenario = (
            "REG-AI-2001 DOMAIN-A1 TEAM-ONE 120 days "
            "REG-AI-2002 DOMAIN-A2 TEAM-TWO 110 days "
            "REG-AI-2003 DOMAIN-A3 TEAM-THREE 100 days "
            "REG-AI-2004 DOMAIN-A4 TEAM-FOUR 90 days"
        )

        started = time.perf_counter()
        report = commander.run(scenario=scenario, mode="dry")
        elapsed = time.perf_counter() - started

        intel_rows = [row for row in report.enrichments if row.integration == "regulation_intel"]
        self.assertEqual(len(intel_rows), 4)
        sequential = sleepy.delay_seconds * sleepy.calls
        self.assertLess(elapsed, sequential * 0.8)

    def test_runtime_script_executes_in_dry_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "examples" / "regulatory_change_impact_runtime.py"
        result = subprocess.run(
            [sys.executable, str(script), "--mode", "dry", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertIn("batch_id", payload)
        self.assertIn("decisions", payload)
        self.assertEqual(payload["mode"], "dry")


if __name__ == "__main__":
    unittest.main()
