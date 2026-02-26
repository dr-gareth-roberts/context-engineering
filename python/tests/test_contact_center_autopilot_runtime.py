from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from context_framework import (
    USE_CASE_INDEX,
    ContactCenterAutopilotCommander,
    ContactCenterExecutionPolicy,
    InMemoryContactResolutionActionAdapter,
    InMemoryCustomerProfileAdapter,
    InMemoryPolicyGuardrailAdapter,
    TriProviderPipeline,
)


class _FlakyCustomerProfileAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def lookup_customer(self, customer_id: str):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("timeout contacting customer-profile service")
        return {
            "customer_id": customer_id,
            "churn_risk": 0.86,
            "fraud_risk": 0.24,
            "lifetime_value_tier": 0.92,
        }


class _SleepyCustomerProfileAdapter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def lookup_customer(self, customer_id: str):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return {
            "customer_id": customer_id,
            "churn_risk": 0.50,
            "fraud_risk": 0.18,
            "lifetime_value_tier": 0.44,
        }


class ContactCenterAutopilotRuntimeTests(unittest.TestCase):
    def _pipeline(self) -> TriProviderPipeline:
        spec = USE_CASE_INDEX["contact_center_autopilot"]
        return TriProviderPipeline(spec)

    def test_extract_signals(self) -> None:
        rows = ContactCenterAutopilotCommander.extract_signals(
            "TICKET-BILL-1001 CUSTOMER-ENT-77 QUEUE-RETENTION 62 minutes 4 recontacts CSAT 35 billing dispute angry vip"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ticket_id, "TICKET-BILL-1001")
        self.assertEqual(rows[0].customer_id, "CUSTOMER-ENT-77")
        self.assertEqual(rows[0].queue_id, "QUEUE-RETENTION")
        self.assertEqual(rows[0].observed_wait_minutes, 62)
        self.assertEqual(rows[0].observed_recontact_count, 4)
        self.assertEqual(rows[0].observed_csat_score, 35)
        self.assertEqual(rows[0].issue_hint, "billing dispute")
        self.assertTrue(rows[0].severe_sentiment_indicator)
        self.assertTrue(rows[0].vip_indicator)

    def test_extract_signals_preserves_event_alignment(self) -> None:
        rows = ContactCenterAutopilotCommander.extract_signals(
            "TICKET-BILL-1001 CUSTOMER-ENT-77 QUEUE-RETENTION 62 minutes 4 recontacts CSAT 35. "
            "TICKET-SUPPORT-2002 CUSTOMER-SMB-12 QUEUE-GENERAL 18 minutes 1 recontacts CSAT 78."
        )
        by_ticket = {row.ticket_id: row for row in rows}
        self.assertEqual(by_ticket["TICKET-BILL-1001"].customer_id, "CUSTOMER-ENT-77")
        self.assertEqual(by_ticket["TICKET-BILL-1001"].queue_id, "QUEUE-RETENTION")
        self.assertEqual(by_ticket["TICKET-SUPPORT-2002"].customer_id, "CUSTOMER-SMB-12")
        self.assertEqual(by_ticket["TICKET-SUPPORT-2002"].queue_id, "QUEUE-GENERAL")
        self.assertEqual(by_ticket["TICKET-SUPPORT-2002"].observed_wait_minutes, 18)

    def test_extract_signals_avoids_generic_phrase_false_positive(self) -> None:
        rows = ContactCenterAutopilotCommander.extract_signals(
            "Contact center triage includes TICKET-BILL-1001 and TICKET-SUPPORT-2002 for review."
        )
        ids = [row.ticket_id for row in rows]
        self.assertEqual(ids, ["TICKET-BILL-1001", "TICKET-SUPPORT-2002"])

    def test_dry_mode_gates_actions_by_default(self) -> None:
        commander = ContactCenterAutopilotCommander(
            pipeline=self._pipeline(),
            customer_profile_adapter=InMemoryCustomerProfileAdapter(
                customers={
                    "CUSTOMER-ENT-77": {
                        "churn_risk": 0.88,
                        "fraud_risk": 0.26,
                        "lifetime_value_tier": 0.94,
                    }
                }
            ),
            policy_guardrail_adapter=InMemoryPolicyGuardrailAdapter(
                tickets={
                    "TICKET-BILL-1001": {
                        "compliance_risk": 0.80,
                        "autopilot_allowed": False,
                        "supervisor_required": True,
                        "refund_flexibility": 0.62,
                        "recommended_response_template": "Escalate with compliant callback commitment.",
                    }
                }
            ),
            action_adapter=InMemoryContactResolutionActionAdapter(),
            execution_policy=ContactCenterExecutionPolicy(execute_actions_in_dry_run=False),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="TICKET-BILL-1001 CUSTOMER-ENT-77 QUEUE-RETENTION 62 minutes 4 recontacts CSAT 35 billing dispute angry vip",
            mode="dry",
        )

        self.assertGreaterEqual(len(report.actions), 1)
        self.assertTrue(all(row.status == "skipped" for row in report.actions))
        self.assertIn("dry mode", " ".join(report.warnings).lower())

    def test_idempotency_skips_repeat_actions(self) -> None:
        action_adapter = InMemoryContactResolutionActionAdapter()
        commander = ContactCenterAutopilotCommander(
            pipeline=self._pipeline(),
            customer_profile_adapter=InMemoryCustomerProfileAdapter(
                customers={
                    "CUSTOMER-ENT-77": {
                        "churn_risk": 0.90,
                        "fraud_risk": 0.28,
                        "lifetime_value_tier": 0.96,
                    }
                }
            ),
            policy_guardrail_adapter=InMemoryPolicyGuardrailAdapter(
                tickets={
                    "TICKET-BILL-1001": {
                        "compliance_risk": 0.82,
                        "autopilot_allowed": False,
                        "supervisor_required": True,
                        "refund_flexibility": 0.66,
                        "recommended_response_template": "Escalate and confirm callback SLA.",
                    }
                }
            ),
            action_adapter=action_adapter,
            execution_policy=ContactCenterExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        scenario = "TICKET-BILL-1001 CUSTOMER-ENT-77 QUEUE-RETENTION 62 minutes 4 recontacts CSAT 35 billing dispute angry vip"
        first = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})
        second = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})

        self.assertTrue(any(row.status == "executed" for row in first.actions))
        self.assertTrue(all(row.status == "skipped" for row in second.actions))
        self.assertEqual(len(action_adapter.supervisor_escalations), 1)
        self.assertEqual(len(action_adapter.drafted_responses), 1)
        self.assertEqual(len(action_adapter.callbacks), 1)

    def test_high_risk_routes_immediate_supervisor_intervention(self) -> None:
        commander = ContactCenterAutopilotCommander(
            pipeline=self._pipeline(),
            customer_profile_adapter=InMemoryCustomerProfileAdapter(
                customers={
                    "CUSTOMER-ENT-77": {
                        "churn_risk": 0.92,
                        "fraud_risk": 0.30,
                        "lifetime_value_tier": 0.96,
                    }
                }
            ),
            policy_guardrail_adapter=InMemoryPolicyGuardrailAdapter(
                tickets={
                    "TICKET-BILL-1001": {
                        "compliance_risk": 0.86,
                        "autopilot_allowed": False,
                        "supervisor_required": True,
                        "refund_flexibility": 0.68,
                        "recommended_response_template": "Escalate immediately.",
                    }
                }
            ),
            action_adapter=InMemoryContactResolutionActionAdapter(),
            execution_policy=ContactCenterExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="TICKET-BILL-1001 CUSTOMER-ENT-77 QUEUE-RETENTION 62 minutes 4 recontacts CSAT 30 regulatory complaint angry vip",
            mode="dry",
        )

        self.assertEqual(report.decisions[0].route, "immediate_supervisor_intervention")
        ops = {row.operation for row in report.actions if row.status == "executed"}
        self.assertIn("create_supervisor_escalation", ops)
        self.assertIn("draft_compliant_response", ops)
        self.assertIn("schedule_priority_callback", ops)
        self.assertIn("issue_compensation_offer", ops)
        self.assertIn("open_quality_review", ops)

    def test_retry_recovers_from_transient_customer_profile_failure(self) -> None:
        flaky = _FlakyCustomerProfileAdapter()
        commander = ContactCenterAutopilotCommander(
            pipeline=self._pipeline(),
            customer_profile_adapter=flaky,
            policy_guardrail_adapter=InMemoryPolicyGuardrailAdapter(),
            action_adapter=InMemoryContactResolutionActionAdapter(),
            execution_policy=ContactCenterExecutionPolicy(execute_actions_in_dry_run=False),
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="TICKET-SUPPORT-2002 CUSTOMER-SMB-12 QUEUE-GENERAL 18 minutes 1 recontacts CSAT 78",
            mode="dry",
        )

        self.assertEqual(flaky.calls, 2)
        row = next(r for r in report.enrichments if r.integration == "customer_profile")
        self.assertTrue(row.success)
        self.assertEqual(row.retried, 1)
        self.assertEqual(row.attempts, 2)

    def test_parallel_customer_profile_enrichment_reduces_latency(self) -> None:
        sleepy = _SleepyCustomerProfileAdapter(delay_seconds=0.08)
        commander = ContactCenterAutopilotCommander(
            pipeline=self._pipeline(),
            customer_profile_adapter=sleepy,
            policy_guardrail_adapter=InMemoryPolicyGuardrailAdapter(),
            action_adapter=InMemoryContactResolutionActionAdapter(),
            execution_policy=ContactCenterExecutionPolicy(
                execute_actions_in_dry_run=False,
                max_parallel_tasks=8,
            ),
            retry_backoff_seconds=0.0,
        )

        scenario = (
            "TICKET-A-1001 CUSTOMER-A-01 QUEUE-ONE 14 minutes 1 recontacts CSAT 80 "
            "TICKET-B-1002 CUSTOMER-B-02 QUEUE-TWO 16 minutes 1 recontacts CSAT 78 "
            "TICKET-C-1003 CUSTOMER-C-03 QUEUE-THREE 18 minutes 2 recontacts CSAT 74 "
            "TICKET-D-1004 CUSTOMER-D-04 QUEUE-FOUR 22 minutes 2 recontacts CSAT 72"
        )

        started = time.perf_counter()
        report = commander.run(scenario=scenario, mode="dry")
        elapsed = time.perf_counter() - started

        profile_rows = [row for row in report.enrichments if row.integration == "customer_profile"]
        self.assertEqual(len(profile_rows), 4)
        sequential = sleepy.delay_seconds * sleepy.calls
        self.assertLess(elapsed, sequential * 0.9)

    def test_runtime_script_executes_in_dry_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "examples" / "contact_center_autopilot_runtime.py"
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
