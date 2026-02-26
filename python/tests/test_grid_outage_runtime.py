from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from context_framework import (
    USE_CASE_INDEX,
    GridExecutionPolicy,
    GridOutageCommander,
    InMemoryCriticalLoadAdapter,
    InMemoryGridActionAdapter,
    InMemoryGridTelemetryAdapter,
    TriProviderPipeline,
)


class _FlakyTelemetryAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def lookup_substation(self, substation_id: str):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("timeout contacting telemetry service")
        return {
            "substation_id": substation_id,
            "instability_score": 0.86,
            "restoration_eta_minutes": 170,
            "customers_affected": 410000,
        }


class _SleepyTelemetryAdapter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def lookup_substation(self, substation_id: str):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return {
            "substation_id": substation_id,
            "instability_score": 0.44,
            "restoration_eta_minutes": 90,
            "customers_affected": 54000,
        }


class GridOutageRuntimeTests(unittest.TestCase):
    def _pipeline(self) -> TriProviderPipeline:
        spec = USE_CASE_INDEX["grid_outage_response"]
        return TriProviderPipeline(spec)

    def test_extract_signals(self) -> None:
        rows = GridOutageCommander.extract_signals(
            "OUT-1001 SUB-A12 FEEDER-F21 120000 customers ETA 90 minutes hospital impact"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].incident_id, "OUT-1001")
        self.assertEqual(rows[0].substation_id, "SUB-A12")
        self.assertEqual(rows[0].feeder_id, "FEEDER-F21")
        self.assertEqual(rows[0].observed_customers_affected, 120000)
        self.assertEqual(rows[0].observed_restoration_eta_minutes, 90)
        self.assertEqual(rows[0].critical_facility_hint, "hospital")

    def test_extract_signals_preserves_event_alignment(self) -> None:
        rows = GridOutageCommander.extract_signals(
            "OUT-9001 on SUB-A12 and FEEDER-F21 impacting 620000 customers in 220 minutes with hospital load. "
            "OUT-9002 on SUB-B44 and FEEDER-G11 impacting 95000 customers in 70 minutes with airport impact."
        )
        by_incident = {row.incident_id: row for row in rows}
        self.assertEqual(by_incident["OUT-9001"].substation_id, "SUB-A12")
        self.assertEqual(by_incident["OUT-9001"].feeder_id, "FEEDER-F21")
        self.assertEqual(by_incident["OUT-9002"].substation_id, "SUB-B44")
        self.assertEqual(by_incident["OUT-9002"].feeder_id, "FEEDER-G11")
        self.assertEqual(by_incident["OUT-9002"].observed_customers_affected, 95000)

    def test_extract_signals_avoids_generic_outage_word_false_positive(self) -> None:
        rows = GridOutageCommander.extract_signals(
            "Outage briefing: OUT-9001 tied to SUB-A12 and FEEDER-F21, then OUT-9002 tied to SUB-B44 and FEEDER-G11."
        )
        ids = [row.incident_id for row in rows]
        self.assertEqual(ids, ["OUT-9001", "OUT-9002"])

    def test_dry_mode_gates_actions_by_default(self) -> None:
        commander = GridOutageCommander(
            pipeline=self._pipeline(),
            telemetry_adapter=InMemoryGridTelemetryAdapter(
                substations={
                    "SUB-A12": {
                        "instability_score": 0.91,
                        "restoration_eta_minutes": 210,
                        "customers_affected": 550000,
                    }
                }
            ),
            critical_load_adapter=InMemoryCriticalLoadAdapter(
                feeders={
                    "FEEDER-F21": {
                        "critical_sites_count": 4,
                        "hospitals_impacted": 2,
                        "life_safety_load_mw": 72,
                    }
                }
            ),
            action_adapter=InMemoryGridActionAdapter(),
            execution_policy=GridExecutionPolicy(execute_actions_in_dry_run=False),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="OUT-1001 SUB-A12 FEEDER-F21 550000 customers ETA 210 minutes cascading",
            mode="dry",
        )

        self.assertGreaterEqual(len(report.actions), 1)
        self.assertTrue(all(row.status == "skipped" for row in report.actions))
        self.assertIn("dry mode", " ".join(report.warnings).lower())

    def test_idempotency_skips_repeat_actions(self) -> None:
        action_adapter = InMemoryGridActionAdapter()
        commander = GridOutageCommander(
            pipeline=self._pipeline(),
            telemetry_adapter=InMemoryGridTelemetryAdapter(
                substations={
                    "SUB-A12": {
                        "instability_score": 0.95,
                        "restoration_eta_minutes": 240,
                        "customers_affected": 640000,
                    }
                }
            ),
            critical_load_adapter=InMemoryCriticalLoadAdapter(
                feeders={
                    "FEEDER-F21": {
                        "critical_sites_count": 5,
                        "hospitals_impacted": 2,
                        "life_safety_load_mw": 80,
                    }
                }
            ),
            action_adapter=action_adapter,
            execution_policy=GridExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        scenario = "OUT-1001 SUB-A12 FEEDER-F21 640000 customers ETA 240 minutes cascading hospital"
        first = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})
        second = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})

        self.assertTrue(any(row.status == "executed" for row in first.actions))
        self.assertTrue(all(row.status == "skipped" for row in second.actions))
        self.assertEqual(len(action_adapter.dispatched_substations), 1)
        self.assertEqual(len(action_adapter.prioritized_feeders), 1)
        self.assertEqual(len(action_adapter.notified_incidents), 1)

    def test_high_risk_routes_blackstart_escalation(self) -> None:
        commander = GridOutageCommander(
            pipeline=self._pipeline(),
            telemetry_adapter=InMemoryGridTelemetryAdapter(
                substations={
                    "SUB-A12": {
                        "instability_score": 0.96,
                        "restoration_eta_minutes": 260,
                        "customers_affected": 730000,
                    }
                }
            ),
            critical_load_adapter=InMemoryCriticalLoadAdapter(
                feeders={
                    "FEEDER-F21": {
                        "critical_sites_count": 6,
                        "hospitals_impacted": 3,
                        "life_safety_load_mw": 90,
                    }
                }
            ),
            action_adapter=InMemoryGridActionAdapter(),
            execution_policy=GridExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="OUT-1001 SUB-A12 FEEDER-F21 730000 customers ETA 260 minutes cascading hospital",
            mode="dry",
        )

        self.assertEqual(report.decisions[0].route, "blackstart_escalation")
        ops = {row.operation for row in report.actions if row.status == "executed"}
        self.assertIn("dispatch_repair_crew", ops)
        self.assertIn("prioritize_feeder", ops)
        self.assertIn("notify_emergency_ops", ops)

    def test_retry_recovers_from_transient_telemetry_failure(self) -> None:
        flaky = _FlakyTelemetryAdapter()
        commander = GridOutageCommander(
            pipeline=self._pipeline(),
            telemetry_adapter=flaky,
            critical_load_adapter=InMemoryCriticalLoadAdapter(),
            action_adapter=InMemoryGridActionAdapter(),
            execution_policy=GridExecutionPolicy(execute_actions_in_dry_run=False),
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="OUT-1001 SUB-A12 FEEDER-F21 410000 customers ETA 170 minutes",
            mode="dry",
        )

        self.assertEqual(flaky.calls, 2)
        telemetry_row = next(row for row in report.enrichments if row.integration == "telemetry")
        self.assertTrue(telemetry_row.success)
        self.assertEqual(telemetry_row.retried, 1)
        self.assertEqual(telemetry_row.attempts, 2)

    def test_parallel_telemetry_enrichment_reduces_latency(self) -> None:
        sleepy = _SleepyTelemetryAdapter(delay_seconds=0.08)
        commander = GridOutageCommander(
            pipeline=self._pipeline(),
            telemetry_adapter=sleepy,
            critical_load_adapter=InMemoryCriticalLoadAdapter(),
            action_adapter=InMemoryGridActionAdapter(),
            execution_policy=GridExecutionPolicy(
                execute_actions_in_dry_run=False,
                max_parallel_tasks=6,
            ),
            retry_backoff_seconds=0.0,
        )

        scenario = (
            "OUT-1001 SUB-A11 FEEDER-F11 10000 customers ETA 60 minutes "
            "OUT-1002 SUB-B22 FEEDER-F22 11000 customers ETA 70 minutes "
            "OUT-1003 SUB-C33 FEEDER-F33 12000 customers ETA 80 minutes "
            "OUT-1004 SUB-D44 FEEDER-F44 13000 customers ETA 90 minutes"
        )
        started = time.perf_counter()
        report = commander.run(scenario=scenario, mode="dry")
        elapsed = time.perf_counter() - started

        telemetry_rows = [row for row in report.enrichments if row.integration == "telemetry"]
        self.assertEqual(len(telemetry_rows), 4)
        sequential = sleepy.delay_seconds * sleepy.calls
        self.assertLess(elapsed, sequential * 0.8)

    def test_runtime_script_executes_in_dry_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "examples" / "grid_outage_response_runtime.py"
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
