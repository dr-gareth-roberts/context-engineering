from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from context_framework import (
    USE_CASE_INDEX,
    ContractExecutionPolicy,
    ContractNegotiationCommander,
    InMemoryClauseRiskAdapter,
    InMemoryContractActionAdapter,
    InMemoryNegotiationPrecedentAdapter,
    TriProviderPipeline,
)


class _FlakyClauseRiskAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def lookup_clause(self, clause_id: str):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("timeout contacting clause-risk service")
        return {
            "clause_id": clause_id,
            "clause_severity": 0.90,
            "counterparty_resistance": 0.79,
            "enforceability_risk": 0.85,
        }


class _SleepyClauseRiskAdapter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def lookup_clause(self, clause_id: str):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return {
            "clause_id": clause_id,
            "clause_severity": 0.56,
            "counterparty_resistance": 0.52,
            "enforceability_risk": 0.49,
        }


class ContractNegotiationRuntimeTests(unittest.TestCase):
    def _pipeline(self) -> TriProviderPipeline:
        spec = USE_CASE_INDEX["contract_risk_negotiation"]
        return TriProviderPipeline(spec)

    def test_extract_signals(self) -> None:
        rows = ContractNegotiationCommander.extract_signals(
            "CONTRACT-ALPHA-001 CLAUSE-LIABILITY-01 VENDOR-OMEGA unlimited liability 48 months 4x strategic vendor"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].contract_id, "CONTRACT-ALPHA-001")
        self.assertEqual(rows[0].clause_id, "CLAUSE-LIABILITY-01")
        self.assertEqual(rows[0].counterparty_id, "VENDOR-OMEGA")
        self.assertEqual(rows[0].observed_term_months, 48)
        self.assertEqual(rows[0].observed_liability_cap_multiplier, 4.0)
        self.assertEqual(rows[0].risk_hint, "unlimited liability")
        self.assertTrue(rows[0].unlimited_liability_indicator)
        self.assertTrue(rows[0].strategic_counterparty_indicator)

    def test_extract_signals_preserves_event_alignment(self) -> None:
        rows = ContractNegotiationCommander.extract_signals(
            "CONTRACT-ALPHA-001 includes CLAUSE-LIABILITY-01 for VENDOR-OMEGA over 48 months with 4x cap. "
            "CONTRACT-BETA-009 includes CLAUSE-DATA-77 for VENDOR-SIGMA over 24 months with 1x cap."
        )
        by_contract = {row.contract_id: row for row in rows}
        self.assertEqual(by_contract["CONTRACT-ALPHA-001"].clause_id, "CLAUSE-LIABILITY-01")
        self.assertEqual(by_contract["CONTRACT-ALPHA-001"].counterparty_id, "VENDOR-OMEGA")
        self.assertEqual(by_contract["CONTRACT-ALPHA-001"].observed_term_months, 48)
        self.assertEqual(by_contract["CONTRACT-BETA-009"].clause_id, "CLAUSE-DATA-77")
        self.assertEqual(by_contract["CONTRACT-BETA-009"].counterparty_id, "VENDOR-SIGMA")
        self.assertEqual(by_contract["CONTRACT-BETA-009"].observed_term_months, 24)

    def test_extract_signals_avoids_generic_phrase_false_positive(self) -> None:
        rows = ContractNegotiationCommander.extract_signals(
            "Contract review update for enterprise agreement between internal teams. "
            "CONTRACT-ALPHA-001 and CONTRACT-BETA-009 are in scope."
        )
        ids = [row.contract_id for row in rows]
        self.assertEqual(ids, ["CONTRACT-ALPHA-001", "CONTRACT-BETA-009"])

    def test_dry_mode_gates_actions_by_default(self) -> None:
        commander = ContractNegotiationCommander(
            pipeline=self._pipeline(),
            clause_risk_adapter=InMemoryClauseRiskAdapter(
                clauses={
                    "CLAUSE-LIABILITY-01": {
                        "clause_severity": 0.92,
                        "counterparty_resistance": 0.85,
                        "enforceability_risk": 0.87,
                    }
                }
            ),
            precedent_adapter=InMemoryNegotiationPrecedentAdapter(
                clauses={
                    "CLAUSE-LIABILITY-01": {
                        "precedent_acceptance_rate": 0.25,
                        "fallback_cap_multiplier": 1.0,
                    }
                }
            ),
            action_adapter=InMemoryContractActionAdapter(),
            execution_policy=ContractExecutionPolicy(execute_actions_in_dry_run=False),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="CONTRACT-ALPHA-001 CLAUSE-LIABILITY-01 VENDOR-OMEGA unlimited liability 48 months 4x",
            mode="dry",
        )

        self.assertGreaterEqual(len(report.actions), 1)
        self.assertTrue(all(row.status == "skipped" for row in report.actions))
        self.assertIn("dry mode", " ".join(report.warnings).lower())

    def test_idempotency_skips_repeat_actions(self) -> None:
        action_adapter = InMemoryContractActionAdapter()
        commander = ContractNegotiationCommander(
            pipeline=self._pipeline(),
            clause_risk_adapter=InMemoryClauseRiskAdapter(
                clauses={
                    "CLAUSE-LIABILITY-01": {
                        "clause_severity": 0.94,
                        "counterparty_resistance": 0.89,
                        "enforceability_risk": 0.90,
                    }
                }
            ),
            precedent_adapter=InMemoryNegotiationPrecedentAdapter(
                clauses={
                    "CLAUSE-LIABILITY-01": {
                        "precedent_acceptance_rate": 0.20,
                        "fallback_cap_multiplier": 1.0,
                    }
                }
            ),
            action_adapter=action_adapter,
            execution_policy=ContractExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        scenario = (
            "CONTRACT-ALPHA-001 CLAUSE-LIABILITY-01 VENDOR-OMEGA unlimited liability 48 months 4x"
        )
        first = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})
        second = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})

        self.assertTrue(any(row.status == "executed" for row in first.actions))
        self.assertTrue(all(row.status == "skipped" for row in second.actions))
        self.assertEqual(len(action_adapter.legal_reviews), 1)
        self.assertEqual(len(action_adapter.redlines), 1)
        self.assertEqual(len(action_adapter.exec_escalations), 1)
        self.assertEqual(len(action_adapter.revision_requests), 1)

    def test_high_risk_routes_hardline_escalation(self) -> None:
        commander = ContractNegotiationCommander(
            pipeline=self._pipeline(),
            clause_risk_adapter=InMemoryClauseRiskAdapter(
                clauses={
                    "CLAUSE-LIABILITY-01": {
                        "clause_severity": 0.95,
                        "counterparty_resistance": 0.88,
                        "enforceability_risk": 0.91,
                    }
                }
            ),
            precedent_adapter=InMemoryNegotiationPrecedentAdapter(
                clauses={
                    "CLAUSE-LIABILITY-01": {
                        "precedent_acceptance_rate": 0.18,
                        "fallback_cap_multiplier": 1.0,
                    }
                }
            ),
            action_adapter=InMemoryContractActionAdapter(),
            execution_policy=ContractExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="CONTRACT-ALPHA-001 CLAUSE-LIABILITY-01 VENDOR-OMEGA unlimited liability 48 months 4x",
            mode="dry",
        )

        self.assertEqual(report.decisions[0].route, "hardline_redline_and_exec_escalation")
        ops = {row.operation for row in report.actions if row.status == "executed"}
        self.assertIn("open_legal_review", ops)
        self.assertIn("propose_redline", ops)
        self.assertIn("escalate_exec_approval", ops)
        self.assertIn("request_counterparty_revision", ops)

    def test_retry_recovers_from_transient_clause_risk_failure(self) -> None:
        flaky = _FlakyClauseRiskAdapter()
        commander = ContractNegotiationCommander(
            pipeline=self._pipeline(),
            clause_risk_adapter=flaky,
            precedent_adapter=InMemoryNegotiationPrecedentAdapter(),
            action_adapter=InMemoryContractActionAdapter(),
            execution_policy=ContractExecutionPolicy(execute_actions_in_dry_run=False),
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="CONTRACT-ALPHA-001 CLAUSE-LIABILITY-01 VENDOR-OMEGA 36 months 2x",
            mode="dry",
        )

        self.assertEqual(flaky.calls, 2)
        clause_row = next(row for row in report.enrichments if row.integration == "clause_risk")
        self.assertTrue(clause_row.success)
        self.assertEqual(clause_row.retried, 1)
        self.assertEqual(clause_row.attempts, 2)

    def test_parallel_clause_risk_enrichment_reduces_latency(self) -> None:
        sleepy = _SleepyClauseRiskAdapter(delay_seconds=0.08)
        commander = ContractNegotiationCommander(
            pipeline=self._pipeline(),
            clause_risk_adapter=sleepy,
            precedent_adapter=InMemoryNegotiationPrecedentAdapter(),
            action_adapter=InMemoryContractActionAdapter(),
            execution_policy=ContractExecutionPolicy(
                execute_actions_in_dry_run=False,
                max_parallel_tasks=8,
            ),
            retry_backoff_seconds=0.0,
        )

        scenario = (
            "CONTRACT-AX-1001 CLAUSE-A1 VENDOR-ONE 36 months 2x "
            "CONTRACT-BX-1002 CLAUSE-A2 VENDOR-TWO 24 months 1x "
            "CONTRACT-CX-1003 CLAUSE-A3 VENDOR-THREE 18 months 1x "
            "CONTRACT-DX-1004 CLAUSE-A4 VENDOR-FOUR 48 months 3x"
        )

        started = time.perf_counter()
        report = commander.run(scenario=scenario, mode="dry")
        elapsed = time.perf_counter() - started

        clause_rows = [row for row in report.enrichments if row.integration == "clause_risk"]
        self.assertEqual(len(clause_rows), 4)
        sequential = sleepy.delay_seconds * sleepy.calls
        self.assertLess(elapsed, sequential * 0.9)

    def test_runtime_script_executes_in_dry_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "examples" / "contract_risk_negotiation_runtime.py"
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
