from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from context_framework import (
    ClinicalExecutionPolicy,
    ClinicalOperationsCommander,
    InMemoryAcuityIntelAdapter,
    InMemoryBedCapacityAdapter,
    InMemoryClinicalActionAdapter,
    TriProviderPipeline,
    USE_CASE_INDEX,
)


class _FlakyBedCapacityAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def lookup_unit(self, unit_id: str):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("timeout contacting bed-capacity service")
        return {
            "unit_id": unit_id,
            "occupancy_pct": 95,
            "staffed_bed_ratio": 0.66,
            "discharge_backlog": 44,
            "diversion_risk": 0.86,
        }


class _SleepyBedCapacityAdapter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def lookup_unit(self, unit_id: str):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return {
            "unit_id": unit_id,
            "occupancy_pct": 86,
            "staffed_bed_ratio": 0.78,
            "discharge_backlog": 22,
            "diversion_risk": 0.42,
        }


class ClinicalOperationsRuntimeTests(unittest.TestCase):
    def _pipeline(self) -> TriProviderPipeline:
        spec = USE_CASE_INDEX["clinical_operations_optimizer"]
        return TriProviderPipeline(spec)

    def test_extract_signals(self) -> None:
        rows = ClinicalOperationsCommander.extract_signals(
            "UNIT-ICU-01 TEAM-CRITICAL LINE-NEURO 96% occupancy 11 hours 34 patients high acuity diversion sepsis"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].unit_id, "UNIT-ICU-01")
        self.assertEqual(rows[0].team_id, "TEAM-CRITICAL")
        self.assertEqual(rows[0].service_line_id, "LINE-NEURO")
        self.assertEqual(rows[0].observed_occupancy_pct, 96)
        self.assertEqual(rows[0].observed_boarding_hours, 11)
        self.assertEqual(rows[0].observed_waiting_patients, 34)
        self.assertEqual(rows[0].acuity_hint, "sepsis")
        self.assertTrue(rows[0].high_acuity_indicator)
        self.assertTrue(rows[0].diversion_risk_indicator)

    def test_extract_signals_preserves_event_alignment(self) -> None:
        rows = ClinicalOperationsCommander.extract_signals(
            "UNIT-ICU-01 TEAM-CRITICAL LINE-NEURO 96% occupancy 11 hours 34 patients. "
            "UNIT-MED-03 TEAM-MEDICINE LINE-GENERAL 84% occupancy 4 hours 16 patients."
        )
        by_unit = {row.unit_id: row for row in rows}
        self.assertEqual(by_unit["UNIT-ICU-01"].team_id, "TEAM-CRITICAL")
        self.assertEqual(by_unit["UNIT-ICU-01"].service_line_id, "LINE-NEURO")
        self.assertEqual(by_unit["UNIT-MED-03"].team_id, "TEAM-MEDICINE")
        self.assertEqual(by_unit["UNIT-MED-03"].service_line_id, "LINE-GENERAL")
        self.assertEqual(by_unit["UNIT-MED-03"].observed_occupancy_pct, 84)

    def test_extract_signals_avoids_generic_phrase_false_positive(self) -> None:
        rows = ClinicalOperationsCommander.extract_signals(
            "Bed management review includes UNIT-ICU-01 and UNIT-MED-03 for triage."
        )
        ids = [row.unit_id for row in rows]
        self.assertEqual(ids, ["UNIT-ICU-01", "UNIT-MED-03"])

    def test_dry_mode_gates_actions_by_default(self) -> None:
        commander = ClinicalOperationsCommander(
            pipeline=self._pipeline(),
            bed_capacity_adapter=InMemoryBedCapacityAdapter(
                units={
                    "UNIT-ICU-01": {
                        "occupancy_pct": 96,
                        "staffed_bed_ratio": 0.66,
                        "discharge_backlog": 44,
                        "diversion_risk": 0.86,
                    }
                }
            ),
            acuity_intel_adapter=InMemoryAcuityIntelAdapter(
                units={
                    "UNIT-ICU-01": {
                        "high_acuity_ratio": 0.92,
                        "deteriorating_patients": 14,
                        "transfer_blockers": 0.83,
                        "surge_probability": 0.90,
                    }
                }
            ),
            action_adapter=InMemoryClinicalActionAdapter(),
            execution_policy=ClinicalExecutionPolicy(execute_actions_in_dry_run=False),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="UNIT-ICU-01 TEAM-CRITICAL LINE-NEURO 96% occupancy 11 hours 34 patients high acuity diversion sepsis",
            mode="dry",
        )

        self.assertGreaterEqual(len(report.actions), 1)
        self.assertTrue(all(row.status == "skipped" for row in report.actions))
        self.assertIn("dry mode", " ".join(report.warnings).lower())

    def test_idempotency_skips_repeat_actions(self) -> None:
        action_adapter = InMemoryClinicalActionAdapter()
        commander = ClinicalOperationsCommander(
            pipeline=self._pipeline(),
            bed_capacity_adapter=InMemoryBedCapacityAdapter(
                units={
                    "UNIT-ICU-01": {
                        "occupancy_pct": 96,
                        "staffed_bed_ratio": 0.66,
                        "discharge_backlog": 44,
                        "diversion_risk": 0.86,
                    }
                }
            ),
            acuity_intel_adapter=InMemoryAcuityIntelAdapter(
                units={
                    "UNIT-ICU-01": {
                        "high_acuity_ratio": 0.92,
                        "deteriorating_patients": 14,
                        "transfer_blockers": 0.83,
                        "surge_probability": 0.90,
                    }
                }
            ),
            action_adapter=action_adapter,
            execution_policy=ClinicalExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        scenario = "UNIT-ICU-01 TEAM-CRITICAL LINE-NEURO 96% occupancy 11 hours 34 patients high acuity diversion sepsis"
        first = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})
        second = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})

        self.assertTrue(any(row.status == "executed" for row in first.actions))
        self.assertTrue(all(row.status == "skipped" for row in second.actions))
        self.assertEqual(len(action_adapter.surge_staffing_units), 1)
        self.assertEqual(len(action_adapter.discharge_huddle_units), 1)
        self.assertEqual(len(action_adapter.transfer_coordination_units), 1)
        self.assertEqual(len(action_adapter.hospital_command_units), 1)

    def test_high_risk_routes_critical_capacity_command(self) -> None:
        commander = ClinicalOperationsCommander(
            pipeline=self._pipeline(),
            bed_capacity_adapter=InMemoryBedCapacityAdapter(
                units={
                    "UNIT-ICU-01": {
                        "occupancy_pct": 97,
                        "staffed_bed_ratio": 0.64,
                        "discharge_backlog": 48,
                        "diversion_risk": 0.90,
                    }
                }
            ),
            acuity_intel_adapter=InMemoryAcuityIntelAdapter(
                units={
                    "UNIT-ICU-01": {
                        "high_acuity_ratio": 0.94,
                        "deteriorating_patients": 16,
                        "transfer_blockers": 0.86,
                        "surge_probability": 0.92,
                    }
                }
            ),
            action_adapter=InMemoryClinicalActionAdapter(),
            execution_policy=ClinicalExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="UNIT-ICU-01 TEAM-CRITICAL LINE-NEURO 97% occupancy 12 hours 36 patients high acuity diversion sepsis",
            mode="dry",
        )

        self.assertEqual(report.decisions[0].route, "critical_capacity_command")
        ops = {row.operation for row in report.actions if row.status == "executed"}
        self.assertIn("activate_surge_staffing", ops)
        self.assertIn("prioritize_discharge_huddle", ops)
        self.assertIn("open_transfer_coordination", ops)
        self.assertIn("escalate_hospital_command", ops)
        self.assertIn("rebalance_clinician_coverage", ops)

    def test_retry_recovers_from_transient_bed_capacity_failure(self) -> None:
        flaky = _FlakyBedCapacityAdapter()
        commander = ClinicalOperationsCommander(
            pipeline=self._pipeline(),
            bed_capacity_adapter=flaky,
            acuity_intel_adapter=InMemoryAcuityIntelAdapter(),
            action_adapter=InMemoryClinicalActionAdapter(),
            execution_policy=ClinicalExecutionPolicy(execute_actions_in_dry_run=False),
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="UNIT-MED-03 TEAM-MEDICINE LINE-GENERAL 84% occupancy 4 hours 16 patients",
            mode="dry",
        )

        self.assertEqual(flaky.calls, 2)
        row = next(r for r in report.enrichments if r.integration == "bed_capacity")
        self.assertTrue(row.success)
        self.assertEqual(row.retried, 1)
        self.assertEqual(row.attempts, 2)

    def test_parallel_bed_capacity_enrichment_reduces_latency(self) -> None:
        sleepy = _SleepyBedCapacityAdapter(delay_seconds=0.08)
        commander = ClinicalOperationsCommander(
            pipeline=self._pipeline(),
            bed_capacity_adapter=sleepy,
            acuity_intel_adapter=InMemoryAcuityIntelAdapter(),
            action_adapter=InMemoryClinicalActionAdapter(),
            execution_policy=ClinicalExecutionPolicy(
                execute_actions_in_dry_run=False,
                max_parallel_tasks=8,
            ),
            retry_backoff_seconds=0.0,
        )

        scenario = (
            "UNIT-A-1001 TEAM-ONE LINE-A 84% occupancy 4 hours 12 patients "
            "UNIT-B-1002 TEAM-TWO LINE-B 86% occupancy 5 hours 14 patients "
            "UNIT-C-1003 TEAM-THREE LINE-C 88% occupancy 6 hours 16 patients "
            "UNIT-D-1004 TEAM-FOUR LINE-D 90% occupancy 7 hours 18 patients"
        )

        started = time.perf_counter()
        report = commander.run(scenario=scenario, mode="dry")
        elapsed = time.perf_counter() - started

        capacity_rows = [row for row in report.enrichments if row.integration == "bed_capacity"]
        self.assertEqual(len(capacity_rows), 4)
        sequential = sleepy.delay_seconds * sleepy.calls
        self.assertLess(elapsed, sequential * 0.9)

    def test_runtime_script_executes_in_dry_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "examples" / "clinical_operations_optimizer_runtime.py"
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
