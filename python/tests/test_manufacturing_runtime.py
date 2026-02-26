from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from context_framework import (
    USE_CASE_INDEX,
    InMemoryLineTelemetryAdapter,
    InMemoryMaintenanceHistoryAdapter,
    InMemoryManufacturingActionAdapter,
    ManufacturingExecutionPolicy,
    ManufacturingRootCauseCommander,
    TriProviderPipeline,
)


class _FlakyLineTelemetryAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def lookup_line(self, line_id: str):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("timeout contacting line telemetry service")
        return {
            "line_id": line_id,
            "yield_rate": 0.80,
            "vibration_risk": 0.82,
            "thermal_risk": 0.74,
            "fault_rate_per_hour": 3.1,
        }


class _SleepyLineTelemetryAdapter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def lookup_line(self, line_id: str):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return {
            "line_id": line_id,
            "yield_rate": 0.91,
            "vibration_risk": 0.41,
            "thermal_risk": 0.33,
            "fault_rate_per_hour": 1.1,
        }


class ManufacturingRuntimeTests(unittest.TestCase):
    def _pipeline(self) -> TriProviderPipeline:
        spec = USE_CASE_INDEX["manufacturing_root_cause"]
        return TriProviderPipeline(spec)

    def test_extract_signals(self) -> None:
        rows = ManufacturingRootCauseCommander.extract_signals(
            "MFG-8101 LINE-A12 ASSET-R77 shift B firmware 18% yield drop 10.8 mm/s 94 C safety interlock"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].anomaly_id, "MFG-8101")
        self.assertEqual(rows[0].line_id, "LINE-A12")
        self.assertEqual(rows[0].asset_id, "ASSET-R77")
        self.assertEqual(rows[0].shift_id, "SHIFT-B")
        self.assertEqual(rows[0].root_cause_hint, "firmware")
        self.assertAlmostEqual(rows[0].observed_yield_drop_pct or 0, 0.18, places=4)
        self.assertAlmostEqual(rows[0].observed_vibration_value or 0, 10.8, places=3)
        self.assertAlmostEqual(rows[0].observed_thermal_value or 0, 94.0, places=3)
        self.assertTrue(rows[0].safety_indicator)

    def test_extract_signals_preserves_event_alignment(self) -> None:
        rows = ManufacturingRootCauseCommander.extract_signals(
            "MFG-8101 on LINE-A12 with ASSET-R77 firmware and 18% yield drop. "
            "MFG-8102 on LINE-C31 with ASSET-P12 bearing and 7% yield drop."
        )
        by_anomaly = {row.anomaly_id: row for row in rows}
        self.assertEqual(by_anomaly["MFG-8101"].line_id, "LINE-A12")
        self.assertEqual(by_anomaly["MFG-8101"].asset_id, "ASSET-R77")
        self.assertEqual(by_anomaly["MFG-8102"].line_id, "LINE-C31")
        self.assertEqual(by_anomaly["MFG-8102"].asset_id, "ASSET-P12")

    def test_extract_signals_avoids_generic_phrase_false_positive(self) -> None:
        rows = ManufacturingRootCauseCommander.extract_signals(
            "Manufacturing root cause briefing: MFG-8101 on LINE-A12 and MFG-8102 on LINE-C31."
        )
        ids = [row.anomaly_id for row in rows]
        self.assertEqual(ids, ["MFG-8101", "MFG-8102"])

    def test_dry_mode_gates_actions_by_default(self) -> None:
        commander = ManufacturingRootCauseCommander(
            pipeline=self._pipeline(),
            line_telemetry_adapter=InMemoryLineTelemetryAdapter(
                lines={
                    "LINE-A12": {
                        "yield_rate": 0.78,
                        "vibration_risk": 0.86,
                        "thermal_risk": 0.79,
                        "fault_rate_per_hour": 3.4,
                    }
                }
            ),
            maintenance_history_adapter=InMemoryMaintenanceHistoryAdapter(
                assets={
                    "ASSET-R77": {
                        "recent_failures_30d": 4,
                        "overdue_pm_days": 35,
                        "firmware_change_recent": True,
                    }
                }
            ),
            action_adapter=InMemoryManufacturingActionAdapter(),
            execution_policy=ManufacturingExecutionPolicy(execute_actions_in_dry_run=False),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="MFG-8101 LINE-A12 ASSET-R77 firmware 22% yield drop safety interlock",
            mode="dry",
        )

        self.assertGreaterEqual(len(report.actions), 1)
        self.assertTrue(all(row.status == "skipped" for row in report.actions))
        self.assertIn("dry mode", " ".join(report.warnings).lower())

    def test_idempotency_skips_repeat_actions(self) -> None:
        action_adapter = InMemoryManufacturingActionAdapter()
        commander = ManufacturingRootCauseCommander(
            pipeline=self._pipeline(),
            line_telemetry_adapter=InMemoryLineTelemetryAdapter(
                lines={
                    "LINE-A12": {
                        "yield_rate": 0.77,
                        "vibration_risk": 0.88,
                        "thermal_risk": 0.81,
                        "fault_rate_per_hour": 3.6,
                    }
                }
            ),
            maintenance_history_adapter=InMemoryMaintenanceHistoryAdapter(
                assets={
                    "ASSET-R77": {
                        "recent_failures_30d": 5,
                        "overdue_pm_days": 42,
                        "firmware_change_recent": True,
                    }
                }
            ),
            action_adapter=action_adapter,
            execution_policy=ManufacturingExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        scenario = "MFG-8101 LINE-A12 ASSET-R77 firmware 23% yield drop safety interlock"
        first = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})
        second = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})

        self.assertTrue(any(row.status == "executed" for row in first.actions))
        self.assertTrue(all(row.status == "skipped" for row in second.actions))
        self.assertEqual(len(action_adapter.paused_lines), 1)
        self.assertEqual(len(action_adapter.rollback_lines), 1)
        self.assertEqual(len(action_adapter.dispatched_assets), 1)

    def test_high_risk_routes_contain_and_rollback(self) -> None:
        commander = ManufacturingRootCauseCommander(
            pipeline=self._pipeline(),
            line_telemetry_adapter=InMemoryLineTelemetryAdapter(
                lines={
                    "LINE-A12": {
                        "yield_rate": 0.75,
                        "vibration_risk": 0.90,
                        "thermal_risk": 0.85,
                        "fault_rate_per_hour": 3.9,
                    }
                }
            ),
            maintenance_history_adapter=InMemoryMaintenanceHistoryAdapter(
                assets={
                    "ASSET-R77": {
                        "recent_failures_30d": 6,
                        "overdue_pm_days": 50,
                        "firmware_change_recent": True,
                    }
                }
            ),
            action_adapter=InMemoryManufacturingActionAdapter(),
            execution_policy=ManufacturingExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="MFG-8101 LINE-A12 ASSET-R77 firmware 25% yield drop safety interlock",
            mode="dry",
        )

        self.assertEqual(report.decisions[0].route, "contain_and_rollback")
        ops = {row.operation for row in report.actions if row.status == "executed"}
        self.assertIn("pause_line", ops)
        self.assertIn("rollback_firmware", ops)
        self.assertIn("dispatch_reliability_engineer", ops)

    def test_retry_recovers_from_transient_line_telemetry_failure(self) -> None:
        flaky = _FlakyLineTelemetryAdapter()
        commander = ManufacturingRootCauseCommander(
            pipeline=self._pipeline(),
            line_telemetry_adapter=flaky,
            maintenance_history_adapter=InMemoryMaintenanceHistoryAdapter(),
            action_adapter=InMemoryManufacturingActionAdapter(),
            execution_policy=ManufacturingExecutionPolicy(execute_actions_in_dry_run=False),
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="MFG-8101 LINE-A12 ASSET-R77 firmware 18% yield drop",
            mode="dry",
        )

        self.assertEqual(flaky.calls, 2)
        line_row = next(row for row in report.enrichments if row.integration == "line_telemetry")
        self.assertTrue(line_row.success)
        self.assertEqual(line_row.retried, 1)
        self.assertEqual(line_row.attempts, 2)

    def test_parallel_line_telemetry_enrichment_reduces_latency(self) -> None:
        sleepy = _SleepyLineTelemetryAdapter(delay_seconds=0.08)
        commander = ManufacturingRootCauseCommander(
            pipeline=self._pipeline(),
            line_telemetry_adapter=sleepy,
            maintenance_history_adapter=InMemoryMaintenanceHistoryAdapter(),
            action_adapter=InMemoryManufacturingActionAdapter(),
            execution_policy=ManufacturingExecutionPolicy(
                execute_actions_in_dry_run=False,
                max_parallel_tasks=8,
            ),
            retry_backoff_seconds=0.0,
        )

        scenario = (
            "MFG-8101 LINE-A11 ASSET-R11 8% yield drop "
            "MFG-8102 LINE-A22 ASSET-R22 9% yield drop "
            "MFG-8103 LINE-A33 ASSET-R33 10% yield drop "
            "MFG-8104 LINE-A44 ASSET-R44 11% yield drop"
        )

        started = time.perf_counter()
        report = commander.run(scenario=scenario, mode="dry")
        elapsed = time.perf_counter() - started

        line_rows = [row for row in report.enrichments if row.integration == "line_telemetry"]
        self.assertEqual(len(line_rows), 4)
        sequential = sleepy.delay_seconds * sleepy.calls
        self.assertLess(elapsed, sequential * 0.8)

    def test_runtime_script_executes_in_dry_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "examples" / "manufacturing_root_cause_runtime.py"
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
