from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from context_framework import (
    USE_CASE_INDEX,
    EmergencyOperationsCommander,
    EOCExecutionPolicy,
    InMemoryEOCActionAdapter,
    InMemoryHazardIntelAdapter,
    InMemoryLogisticsCapacityAdapter,
    TriProviderPipeline,
)


class _FlakyHazardAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def lookup_zone(self, zone_id: str):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("timeout contacting hazard service")
        return {
            "zone_id": zone_id,
            "hazard_severity": 0.82,
            "spread_velocity": 0.72,
            "weather_volatility": 0.55,
            "time_to_impact_minutes": 110,
        }


class _SleepyHazardAdapter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def lookup_zone(self, zone_id: str):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return {
            "zone_id": zone_id,
            "hazard_severity": 0.55,
            "spread_velocity": 0.45,
            "weather_volatility": 0.32,
            "time_to_impact_minutes": 160,
        }


class EmergencyOperationsRuntimeTests(unittest.TestCase):
    def _pipeline(self) -> TriProviderPipeline:
        spec = USE_CASE_INDEX["emergency_operations_center"]
        return TriProviderPipeline(spec)

    def test_extract_signals(self) -> None:
        rows = EmergencyOperationsCommander.extract_signals(
            "EOC-7001 in ZONE-NORTH with UNIT-A11 wildfire 120000 residents 90 minutes hospital mandatory evacuation"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].incident_id, "EOC-7001")
        self.assertEqual(rows[0].zone_id, "ZONE-NORTH")
        self.assertEqual(rows[0].resource_unit_id, "UNIT-A11")
        self.assertEqual(rows[0].hazard_hint, "wildfire")
        self.assertEqual(rows[0].observed_population_exposed, 120000)
        self.assertEqual(rows[0].observed_time_to_impact_minutes, 90)
        self.assertEqual(rows[0].vulnerable_population_hint, "hospital")
        self.assertTrue(rows[0].mandatory_evacuation_hint)

    def test_extract_signals_preserves_event_alignment(self) -> None:
        rows = EmergencyOperationsCommander.extract_signals(
            "EOC-7001 in ZONE-NORTH with UNIT-A11 wildfire and 280000 residents in 90 minutes with hospital exposure. "
            "EOC-7002 in ZONE-EAST with UNIT-B22 flood and 65000 residents in 4 hours."
        )
        by_incident = {row.incident_id: row for row in rows}
        self.assertEqual(by_incident["EOC-7001"].zone_id, "ZONE-NORTH")
        self.assertEqual(by_incident["EOC-7001"].resource_unit_id, "UNIT-A11")
        self.assertEqual(by_incident["EOC-7002"].zone_id, "ZONE-EAST")
        self.assertEqual(by_incident["EOC-7002"].resource_unit_id, "UNIT-B22")
        self.assertEqual(by_incident["EOC-7002"].observed_population_exposed, 65000)
        self.assertEqual(by_incident["EOC-7002"].observed_time_to_impact_minutes, 240)

    def test_extract_signals_avoids_generic_phrase_false_positive(self) -> None:
        rows = EmergencyOperationsCommander.extract_signals(
            "Emergency operations center briefing: EOC-7001 in ZONE-NORTH and EOC-7002 in ZONE-EAST."
        )
        ids = [row.incident_id for row in rows]
        self.assertEqual(ids, ["EOC-7001", "EOC-7002"])

    def test_dry_mode_gates_actions_by_default(self) -> None:
        commander = EmergencyOperationsCommander(
            pipeline=self._pipeline(),
            hazard_adapter=InMemoryHazardIntelAdapter(
                zones={
                    "ZONE-NORTH": {
                        "hazard_severity": 0.88,
                        "spread_velocity": 0.81,
                        "weather_volatility": 0.65,
                        "time_to_impact_minutes": 95,
                    }
                }
            ),
            logistics_adapter=InMemoryLogisticsCapacityAdapter(
                zones={
                    "ZONE-NORTH": {
                        "population_exposed": 240000,
                        "vulnerable_sites_count": 3,
                        "shelter_capacity_pct": 0.44,
                        "route_access_score": 0.32,
                    }
                }
            ),
            action_adapter=InMemoryEOCActionAdapter(),
            execution_policy=EOCExecutionPolicy(execute_actions_in_dry_run=False),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="EOC-7001 ZONE-NORTH UNIT-A11 wildfire 240000 residents 95 minutes hospital",
            mode="dry",
        )

        self.assertGreaterEqual(len(report.actions), 1)
        self.assertTrue(all(row.status == "skipped" for row in report.actions))
        self.assertIn("dry mode", " ".join(report.warnings).lower())

    def test_idempotency_skips_repeat_actions(self) -> None:
        action_adapter = InMemoryEOCActionAdapter()
        commander = EmergencyOperationsCommander(
            pipeline=self._pipeline(),
            hazard_adapter=InMemoryHazardIntelAdapter(
                zones={
                    "ZONE-NORTH": {
                        "hazard_severity": 0.94,
                        "spread_velocity": 0.88,
                        "weather_volatility": 0.66,
                        "time_to_impact_minutes": 85,
                    }
                }
            ),
            logistics_adapter=InMemoryLogisticsCapacityAdapter(
                zones={
                    "ZONE-NORTH": {
                        "population_exposed": 310000,
                        "vulnerable_sites_count": 4,
                        "shelter_capacity_pct": 0.36,
                        "route_access_score": 0.28,
                    }
                }
            ),
            action_adapter=action_adapter,
            execution_policy=EOCExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        scenario = (
            "EOC-7001 ZONE-NORTH UNIT-A11 wildfire 310000 residents 85 minutes "
            "hospital mandatory evacuation"
        )
        first = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})
        second = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})

        self.assertTrue(any(row.status == "executed" for row in first.actions))
        self.assertTrue(all(row.status == "skipped" for row in second.actions))
        self.assertEqual(len(action_adapter.evacuation_zones), 1)
        self.assertEqual(len(action_adapter.opened_shelter_zones), 1)
        self.assertEqual(len(action_adapter.prepositioned_units), 1)
        self.assertEqual(len(action_adapter.alerted_incidents), 1)

    def test_high_risk_routes_full_evacuation_activation(self) -> None:
        commander = EmergencyOperationsCommander(
            pipeline=self._pipeline(),
            hazard_adapter=InMemoryHazardIntelAdapter(
                zones={
                    "ZONE-NORTH": {
                        "hazard_severity": 0.96,
                        "spread_velocity": 0.90,
                        "weather_volatility": 0.72,
                        "time_to_impact_minutes": 70,
                    }
                }
            ),
            logistics_adapter=InMemoryLogisticsCapacityAdapter(
                zones={
                    "ZONE-NORTH": {
                        "population_exposed": 380000,
                        "vulnerable_sites_count": 5,
                        "shelter_capacity_pct": 0.30,
                        "route_access_score": 0.25,
                    }
                }
            ),
            action_adapter=InMemoryEOCActionAdapter(),
            execution_policy=EOCExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario=(
                "EOC-7001 ZONE-NORTH UNIT-A11 wildfire 380000 residents 70 minutes "
                "hospital mandatory evacuation"
            ),
            mode="dry",
        )

        self.assertEqual(report.decisions[0].route, "full_evacuation_activation")
        ops = {row.operation for row in report.actions if row.status == "executed"}
        self.assertIn("activate_evacuation", ops)
        self.assertIn("open_shelter", ops)
        self.assertIn("preposition_resources", ops)
        self.assertIn("issue_public_alert", ops)

    def test_retry_recovers_from_transient_hazard_failure(self) -> None:
        flaky = _FlakyHazardAdapter()
        commander = EmergencyOperationsCommander(
            pipeline=self._pipeline(),
            hazard_adapter=flaky,
            logistics_adapter=InMemoryLogisticsCapacityAdapter(),
            action_adapter=InMemoryEOCActionAdapter(),
            execution_policy=EOCExecutionPolicy(execute_actions_in_dry_run=False),
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="EOC-7001 ZONE-NORTH UNIT-A11 wildfire 120000 residents 110 minutes",
            mode="dry",
        )

        self.assertEqual(flaky.calls, 2)
        hazard_row = next(row for row in report.enrichments if row.integration == "hazard_intel")
        self.assertTrue(hazard_row.success)
        self.assertEqual(hazard_row.retried, 1)
        self.assertEqual(hazard_row.attempts, 2)

    def test_parallel_hazard_enrichment_reduces_latency(self) -> None:
        sleepy = _SleepyHazardAdapter(delay_seconds=0.08)
        commander = EmergencyOperationsCommander(
            pipeline=self._pipeline(),
            hazard_adapter=sleepy,
            logistics_adapter=InMemoryLogisticsCapacityAdapter(),
            action_adapter=InMemoryEOCActionAdapter(),
            execution_policy=EOCExecutionPolicy(
                execute_actions_in_dry_run=False,
                max_parallel_tasks=8,
            ),
            retry_backoff_seconds=0.0,
        )

        scenario = (
            "EOC-7001 ZONE-N1 UNIT-A1 wildfire 20000 residents 60 minutes "
            "EOC-7002 ZONE-N2 UNIT-A2 flood 21000 residents 70 minutes "
            "EOC-7003 ZONE-N3 UNIT-A3 wildfire 22000 residents 80 minutes "
            "EOC-7004 ZONE-N4 UNIT-A4 flood 23000 residents 90 minutes"
        )

        started = time.perf_counter()
        report = commander.run(scenario=scenario, mode="dry")
        elapsed = time.perf_counter() - started

        hazard_rows = [row for row in report.enrichments if row.integration == "hazard_intel"]
        self.assertEqual(len(hazard_rows), 4)
        sequential = sleepy.delay_seconds * sleepy.calls
        self.assertLess(elapsed, sequential * 0.8)

    def test_runtime_script_executes_in_dry_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "examples" / "emergency_operations_center_runtime.py"
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
