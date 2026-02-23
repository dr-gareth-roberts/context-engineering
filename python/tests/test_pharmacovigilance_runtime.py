from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from context_framework import (
    InMemoryFAERSAdapter,
    InMemoryLotTraceabilityAdapter,
    InMemorySafetyActionAdapter,
    PharmacovigilanceCommander,
    PharmacovigilanceExecutionPolicy,
    TriProviderPipeline,
    USE_CASE_INDEX,
)


class _FlakyFAERSAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def lookup_signal(self, compound: str, symptom: str):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("timeout contacting faers")
        return {
            "compound": compound,
            "symptom": symptom,
            "serious_event_rate": 0.88,
            "recent_case_count": 33,
            "fatal_case_count": 1,
        }


class _SleepyFAERSAdapter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def lookup_signal(self, compound: str, symptom: str):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return {
            "compound": compound,
            "symptom": symptom,
            "serious_event_rate": 0.45,
            "recent_case_count": 12,
            "fatal_case_count": 0,
        }


class PharmacovigilanceRuntimeTests(unittest.TestCase):
    def _pipeline(self) -> TriProviderPipeline:
        spec = USE_CASE_INDEX["pharmacovigilance_events"]
        return TriProviderPipeline(spec)

    def test_extract_signals(self) -> None:
        rows = PharmacovigilanceCommander.extract_signals(
            "AE-1001 LOT-A12 DRUG-XY anaphylaxis 22 reports"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].signal_id, "AE-1001")
        self.assertEqual(rows[0].lot_id, "LOT-A12")
        self.assertEqual(rows[0].compound, "DRUG-XY")
        self.assertEqual(rows[0].symptom, "anaphylaxis")
        self.assertEqual(rows[0].observed_case_count, 22)

    def test_extract_signals_preserves_per_event_alignment(self) -> None:
        rows = PharmacovigilanceCommander.extract_signals(
            "Safety intake: AE-5011 linked to LOT-A112 for DRUG-ZX1 with anaphylaxis and 47 reports, "
            "AE-5012 linked to LOT-B204 for DRUG-ZX1 with arrhythmia and 18 reports, and AE-5013 "
            "linked to LOT-C330 for DRUG-QP9 with rash and 6 reports."
        )
        by_signal = {row.signal_id: row for row in rows}
        self.assertEqual(by_signal["AE-5011"].compound, "DRUG-ZX1")
        self.assertEqual(by_signal["AE-5012"].compound, "DRUG-ZX1")
        self.assertEqual(by_signal["AE-5013"].compound, "DRUG-QP9")
        self.assertEqual(by_signal["AE-5012"].symptom, "arrhythmia")
        self.assertEqual(by_signal["AE-5013"].symptom, "rash")

    def test_dry_mode_gates_actions_by_default(self) -> None:
        commander = PharmacovigilanceCommander(
            pipeline=self._pipeline(),
            faers_adapter=InMemoryFAERSAdapter(
                signals={
                    "DRUG-XY|anaphylaxis": {
                        "serious_event_rate": 0.9,
                        "recent_case_count": 31,
                        "fatal_case_count": 1,
                    }
                }
            ),
            lot_traceability_adapter=InMemoryLotTraceabilityAdapter(
                lots={"LOT-A12": {"deviation_rate": 0.9, "units_shipped": 25000}}
            ),
            safety_action_adapter=InMemorySafetyActionAdapter(),
            execution_policy=PharmacovigilanceExecutionPolicy(execute_actions_in_dry_run=False),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="AE-1001 LOT-A12 DRUG-XY anaphylaxis 31 reports",
            mode="dry",
        )

        self.assertGreaterEqual(len(report.actions), 1)
        self.assertTrue(all(row.status == "skipped" for row in report.actions))
        self.assertIn("dry mode", " ".join(report.warnings).lower())

    def test_idempotency_skips_repeat_actions(self) -> None:
        action_adapter = InMemorySafetyActionAdapter()
        commander = PharmacovigilanceCommander(
            pipeline=self._pipeline(),
            faers_adapter=InMemoryFAERSAdapter(
                signals={
                    "DRUG-XY|anaphylaxis": {
                        "serious_event_rate": 0.95,
                        "recent_case_count": 44,
                        "fatal_case_count": 2,
                    }
                }
            ),
            lot_traceability_adapter=InMemoryLotTraceabilityAdapter(
                lots={"LOT-A12": {"deviation_rate": 0.86, "units_shipped": 50000}}
            ),
            safety_action_adapter=action_adapter,
            execution_policy=PharmacovigilanceExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        scenario = "AE-1001 LOT-A12 DRUG-XY anaphylaxis 44 reports"
        first = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})
        second = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})

        self.assertTrue(any(row.status == "executed" for row in first.actions))
        self.assertTrue(all(row.status == "skipped" for row in second.actions))
        self.assertEqual(len(action_adapter.held_lots), 1)
        self.assertEqual(len(action_adapter.alerts), 1)

    def test_high_risk_routes_lot_hold_and_report(self) -> None:
        commander = PharmacovigilanceCommander(
            pipeline=self._pipeline(),
            faers_adapter=InMemoryFAERSAdapter(
                signals={
                    "DRUG-XY|anaphylaxis": {
                        "serious_event_rate": 0.93,
                        "recent_case_count": 51,
                        "fatal_case_count": 1,
                    }
                }
            ),
            lot_traceability_adapter=InMemoryLotTraceabilityAdapter(
                lots={"LOT-A12": {"deviation_rate": 0.88, "units_shipped": 51000}}
            ),
            safety_action_adapter=InMemorySafetyActionAdapter(),
            execution_policy=PharmacovigilanceExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="AE-1001 LOT-A12 DRUG-XY anaphylaxis 51 reports",
            mode="dry",
        )

        self.assertEqual(report.decisions[0].route, "lot_hold_and_report")
        ops = {row.operation for row in report.actions if row.status == "executed"}
        self.assertIn("hold_lot", ops)
        self.assertIn("submit_regulatory_alert", ops)
        self.assertIn("queue_medical_review", ops)

    def test_retry_recovers_from_transient_faers_failure(self) -> None:
        flaky = _FlakyFAERSAdapter()
        commander = PharmacovigilanceCommander(
            pipeline=self._pipeline(),
            faers_adapter=flaky,
            lot_traceability_adapter=InMemoryLotTraceabilityAdapter(),
            safety_action_adapter=InMemorySafetyActionAdapter(),
            execution_policy=PharmacovigilanceExecutionPolicy(execute_actions_in_dry_run=False),
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="AE-1001 LOT-A12 DRUG-XY anaphylaxis 20 reports",
            mode="dry",
        )

        self.assertEqual(flaky.calls, 2)
        faers_row = next(row for row in report.enrichments if row.integration == "faers")
        self.assertTrue(faers_row.success)
        self.assertEqual(faers_row.retried, 1)
        self.assertEqual(faers_row.attempts, 2)

    def test_parallel_faers_enrichment_reduces_latency(self) -> None:
        sleepy = _SleepyFAERSAdapter(delay_seconds=0.08)
        commander = PharmacovigilanceCommander(
            pipeline=self._pipeline(),
            faers_adapter=sleepy,
            lot_traceability_adapter=InMemoryLotTraceabilityAdapter(),
            safety_action_adapter=InMemorySafetyActionAdapter(),
            execution_policy=PharmacovigilanceExecutionPolicy(
                execute_actions_in_dry_run=False,
                max_parallel_tasks=6,
            ),
            retry_backoff_seconds=0.0,
        )

        scenario = (
            "AE-1001 LOT-A11 DRUG-AA arrhythmia 10 reports "
            "AE-1002 LOT-B22 DRUG-BB arrhythmia 11 reports "
            "AE-1003 LOT-C33 DRUG-CC arrhythmia 12 reports "
            "AE-1004 LOT-D44 DRUG-DD arrhythmia 13 reports"
        )
        started = time.perf_counter()
        report = commander.run(scenario=scenario, mode="dry")
        elapsed = time.perf_counter() - started

        faers_rows = [row for row in report.enrichments if row.integration == "faers"]
        self.assertEqual(len(faers_rows), 4)
        sequential = sleepy.delay_seconds * sleepy.calls
        self.assertLess(elapsed, sequential * 0.8)

    def test_runtime_script_executes_in_dry_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "examples" / "pharmacovigilance_events_runtime.py"
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
