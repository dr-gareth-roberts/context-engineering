from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Protocol
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from .soc_runtime import (
    AuditLogger,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    NoOpAuditLogger,
)
from .tri_provider_pipeline import TriProviderPipeline, UseCaseExecutionReport

_CASE_RE = re.compile(r"\b(?:CASE|ALERT)[-_]?[A-Za-z0-9]{3,}\b", re.IGNORECASE)
_ACCOUNT_RE = re.compile(r"\b(?:ACC|ACCT|ACCOUNT)[-_]?[A-Za-z0-9]{3,}\b", re.IGNORECASE)
_ENTITY_RE = re.compile(r"\b(?:ENT|ENTITY|CUST|CUSTOMER|USER)[-_]?[A-Za-z0-9]{2,}\b", re.IGNORECASE)
_TX_RE = re.compile(r"\b(?:TX|TRX)[-_]?[A-Za-z0-9]{4,}\b", re.IGNORECASE)
_MONEY_RE = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{2})?)")


def _unique_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(value)
    return ordered


def _normalize(value: str) -> str:
    return value.strip().replace("_", "-").upper()


class TransactionGraphAdapter(Protocol):
    def lookup_account_graph(self, account_id: str) -> dict[str, Any]:
        ...


class SanctionsScreenAdapter(Protocol):
    def screen_entity(self, entity_id: str) -> dict[str, Any]:
        ...


class CaseActionAdapter(Protocol):
    def freeze_account(self, account_id: str, *, reason: str) -> dict[str, Any]:
        ...

    def create_sar(self, case_id: str, *, priority: str, reason: str) -> dict[str, Any]:
        ...

    def queue_edd(self, case_id: str, *, reason: str) -> dict[str, Any]:
        ...


class NoOpTransactionGraphAdapter:
    def lookup_account_graph(self, account_id: str) -> dict[str, Any]:
        return {
            "account_id": account_id,
            "anomaly_score": 0.22,
            "cross_border_count": 2,
            "high_risk_jurisdictions": [],
            "source": "noop",
        }


class NoOpSanctionsScreenAdapter:
    def screen_entity(self, entity_id: str) -> dict[str, Any]:
        return {
            "entity_id": entity_id,
            "match_score": 0.04,
            "watchlist_hit": False,
            "pep_hit": False,
            "source": "noop",
        }


class NoOpCaseActionAdapter:
    def freeze_account(self, account_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "account_id": account_id,
            "action": "freeze_account",
            "reason": reason,
            "status": "noop",
        }

    def create_sar(self, case_id: str, *, priority: str, reason: str) -> dict[str, Any]:
        return {
            "case_id": case_id,
            "action": "create_sar",
            "priority": priority,
            "reason": reason,
            "status": "noop",
        }

    def queue_edd(self, case_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "case_id": case_id,
            "action": "queue_edd",
            "reason": reason,
            "status": "noop",
        }


@dataclass(slots=True)
class InMemoryTransactionGraphAdapter:
    accounts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_account_graph(self, account_id: str) -> dict[str, Any]:
        account = _normalize(account_id)
        data = self.accounts.get(account, {})
        anomaly = float(data.get("anomaly_score", 0.3))
        cross_border = int(data.get("cross_border_count", 0))
        jurisdictions = list(data.get("high_risk_jurisdictions", []))
        return {
            "account_id": account,
            "anomaly_score": max(0.0, min(1.0, anomaly)),
            "cross_border_count": max(0, cross_border),
            "high_risk_jurisdictions": jurisdictions,
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemorySanctionsScreenAdapter:
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)

    def screen_entity(self, entity_id: str) -> dict[str, Any]:
        entity = _normalize(entity_id)
        data = self.entities.get(entity, {})
        match_score = float(data.get("match_score", 0.05))
        watchlist_hit = bool(data.get("watchlist_hit", match_score >= 0.9))
        pep_hit = bool(data.get("pep_hit", False))
        return {
            "entity_id": entity,
            "match_score": max(0.0, min(1.0, match_score)),
            "watchlist_hit": watchlist_hit,
            "pep_hit": pep_hit,
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryCaseActionAdapter:
    frozen_accounts: set[str] = field(default_factory=set)
    sar_cases: dict[str, str] = field(default_factory=dict)
    edd_cases: set[str] = field(default_factory=set)

    def freeze_account(self, account_id: str, *, reason: str) -> dict[str, Any]:
        account = _normalize(account_id)
        self.frozen_accounts.add(account)
        return {
            "account_id": account,
            "action": "freeze_account",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def create_sar(self, case_id: str, *, priority: str, reason: str) -> dict[str, Any]:
        case = _normalize(case_id)
        self.sar_cases[case] = priority
        return {
            "case_id": case,
            "action": "create_sar",
            "priority": priority,
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def queue_edd(self, case_id: str, *, reason: str) -> dict[str, Any]:
        case = _normalize(case_id)
        self.edd_cases.add(case)
        return {
            "case_id": case,
            "action": "queue_edd",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }


@dataclass(slots=True)
class _HTTPJSONAdapterBase:
    base_url: str
    api_key: str
    timeout_seconds: float = 10.0

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{self.base_url.rstrip('/')}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_seconds) as response:
                data = response.read().decode("utf-8")
                if not data.strip():
                    return {}
                return json.loads(data)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Network error: {exc}") from exc


@dataclass(slots=True)
class HTTPTransactionGraphAdapter(_HTTPJSONAdapterBase):
    lookup_path: str = "/aml/transaction_graph"

    def lookup_account_graph(self, account_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"account_id": account_id})


@dataclass(slots=True)
class HTTPSanctionsScreenAdapter(_HTTPJSONAdapterBase):
    screen_path: str = "/aml/sanctions_screen"

    def screen_entity(self, entity_id: str) -> dict[str, Any]:
        return self._post(self.screen_path, {"entity_id": entity_id})


@dataclass(slots=True)
class HTTPCaseActionAdapter(_HTTPJSONAdapterBase):
    freeze_path: str = "/aml/freeze_account"
    sar_path: str = "/aml/create_sar"
    edd_path: str = "/aml/queue_edd"

    def freeze_account(self, account_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.freeze_path, {"account_id": account_id, "reason": reason})

    def create_sar(self, case_id: str, *, priority: str, reason: str) -> dict[str, Any]:
        return self._post(
            self.sar_path,
            {"case_id": case_id, "priority": priority, "reason": reason},
        )

    def queue_edd(self, case_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.edd_path, {"case_id": case_id, "reason": reason})


def build_transaction_graph_adapter_from_env() -> TransactionGraphAdapter:
    base = os.getenv("AML_GRAPH_BASE_URL")
    token = os.getenv("AML_GRAPH_API_KEY")
    if base and token:
        path = os.getenv("AML_GRAPH_LOOKUP_PATH", "/aml/transaction_graph")
        return HTTPTransactionGraphAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpTransactionGraphAdapter()


def build_sanctions_screen_adapter_from_env() -> SanctionsScreenAdapter:
    base = os.getenv("AML_SANCTIONS_BASE_URL")
    token = os.getenv("AML_SANCTIONS_API_KEY")
    if base and token:
        path = os.getenv("AML_SANCTIONS_SCREEN_PATH", "/aml/sanctions_screen")
        return HTTPSanctionsScreenAdapter(base_url=base, api_key=token, screen_path=path)
    return NoOpSanctionsScreenAdapter()


def build_case_action_adapter_from_env() -> CaseActionAdapter:
    base = os.getenv("AML_ACTIONS_BASE_URL")
    token = os.getenv("AML_ACTIONS_API_KEY")
    if base and token:
        return HTTPCaseActionAdapter(
            base_url=base,
            api_key=token,
            freeze_path=os.getenv("AML_ACTIONS_FREEZE_PATH", "/aml/freeze_account"),
            sar_path=os.getenv("AML_ACTIONS_SAR_PATH", "/aml/create_sar"),
            edd_path=os.getenv("AML_ACTIONS_EDD_PATH", "/aml/queue_edd"),
        )
    return NoOpCaseActionAdapter()


AMLRoute = Literal["freeze_and_sar", "sar_only", "enhanced_due_diligence", "monitor"]


@dataclass(slots=True, frozen=True)
class AMLSignal:
    case_id: str
    account_id: str
    entity_id: str
    transaction_id: str | None
    observed_amount: float | None


@dataclass(slots=True, frozen=True)
class AMLDecision:
    case_id: str
    account_id: str
    entity_id: str
    route: AMLRoute
    priority: str
    confidence: float
    anomaly_score: float
    sanctions_match_score: float
    watchlist_hit: bool
    rationale: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class AMLActionResult:
    integration: str
    operation: str
    target: str
    success: bool
    latency_ms: int
    request: dict[str, Any]
    response: dict[str, Any] | None = None
    error: str | None = None
    retried: int = 0
    attempts: int = 1
    status: str = "executed"
    idempotency_key: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class AMLExecutionPolicy:
    execute_actions_in_dry_run: bool = False
    max_parallel_tasks: int = 6
    max_signals_to_process: int = 20
    sanctions_match_threshold: float = 0.9
    anomaly_escalation_threshold: float = 0.75
    edd_threshold: float = 0.45
    allow_auto_freeze: bool = True
    allow_auto_sar: bool = True
    allow_auto_edd: bool = True

    def __post_init__(self) -> None:
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be >= 1")
        if self.max_signals_to_process < 1:
            raise ValueError("max_signals_to_process must be >= 1")
        for name, value in (
            ("sanctions_match_threshold", self.sanctions_match_threshold),
            ("anomaly_escalation_threshold", self.anomaly_escalation_threshold),
            ("edd_threshold", self.edd_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(slots=True, frozen=True)
class AMLExecutionStats:
    signals_total: int
    enrichment_total: int
    enrichment_success: int
    actions_total: int
    actions_success: int
    actions_skipped: int
    actions_failed: int
    freeze_sar_count: int
    sar_only_count: int
    edd_count: int
    monitor_count: int


@dataclass(slots=True, frozen=True)
class AMLExecutionReport:
    batch_id: str
    pipeline_report: UseCaseExecutionReport
    mode: str
    started_at: datetime
    completed_at: datetime
    signals: tuple[AMLSignal, ...]
    enrichments: tuple[AMLActionResult, ...]
    decisions: tuple[AMLDecision, ...]
    actions: tuple[AMLActionResult, ...]
    stats: AMLExecutionStats
    recommendations: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "pipeline_report": self.pipeline_report.to_dict(),
            "mode": self.mode,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "signals": [asdict(item) for item in self.signals],
            "enrichments": [asdict(item) for item in self.enrichments],
            "decisions": [asdict(item) for item in self.decisions],
            "actions": [asdict(item) for item in self.actions],
            "stats": asdict(self.stats),
            "recommendations": list(self.recommendations),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(slots=True, frozen=True)
class _ExecutionTask:
    integration: str
    operation: str
    target: str
    request_payload: dict[str, Any]
    idempotency_key: str | None
    call: Callable[[], dict[str, Any]]


@dataclass(slots=True)
class AMLKYCFincrimeCommander:
    pipeline: TriProviderPipeline
    transaction_graph_adapter: TransactionGraphAdapter
    sanctions_screen_adapter: SanctionsScreenAdapter
    case_action_adapter: CaseActionAdapter
    execution_policy: AMLExecutionPolicy = field(default_factory=AMLExecutionPolicy)
    idempotency_store: IdempotencyStore = field(default_factory=InMemoryIdempotencyStore)
    audit_logger: AuditLogger = field(default_factory=NoOpAuditLogger)
    retry_attempts: int = 2
    retry_backoff_seconds: float = 0.35
    idempotency_ttl_seconds: int = 4 * 60 * 60

    def run(
        self,
        *,
        scenario: str,
        evidence_documents: tuple[str, ...] = (),
        mode: str = "dry",
        metadata: dict[str, str] | None = None,
    ) -> AMLExecutionReport:
        if mode not in {"dry", "live"}:
            raise ValueError("mode must be 'dry' or 'live'")

        started_at = datetime.now(timezone.utc)
        warnings: list[str] = []
        errors: list[str] = []

        meta = dict(metadata or {})
        batch_id = meta.get("batch_id") or self._build_batch_id(scenario, started_at)
        meta["batch_id"] = batch_id

        pipeline_mode = "live" if mode == "live" else "dry"
        pipeline_report = self.pipeline.run(
            scenario=scenario,
            evidence_documents=evidence_documents,
            mode=pipeline_mode,
            metadata=meta,
        )

        source_text = " ".join((scenario, *evidence_documents))
        signals = self.extract_signals(
            source_text,
            max_signals=self.execution_policy.max_signals_to_process,
        )

        enrichments = self._run_enrichment(signals)
        decisions = self._build_decisions(signals, enrichments)

        execute_actions = True
        if mode == "dry" and not self.execution_policy.execute_actions_in_dry_run:
            execute_actions = False
            warnings.append("AML actions skipped in dry mode by execution policy.")

        actions = self._run_actions(
            batch_id=batch_id,
            decisions=decisions,
            execute_actions=execute_actions,
        )

        for row in (*enrichments, *actions):
            if not row.success:
                errors.append(f"{row.integration}.{row.operation} failed for {row.target}: {row.error}")
            self._log_audit_event(batch_id=batch_id, mode=mode, row=row)

        stats = self._build_stats(
            signals=signals,
            enrichments=enrichments,
            decisions=decisions,
            actions=actions,
        )

        recommendations = self._recommendations(
            pipeline_report=pipeline_report,
            stats=stats,
            decisions=decisions,
            errors=errors,
        )

        completed_at = datetime.now(timezone.utc)
        return AMLExecutionReport(
            batch_id=batch_id,
            pipeline_report=pipeline_report,
            mode=mode,
            started_at=started_at,
            completed_at=completed_at,
            signals=tuple(signals),
            enrichments=tuple(enrichments),
            decisions=tuple(decisions),
            actions=tuple(actions),
            stats=stats,
            recommendations=tuple(recommendations),
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    @staticmethod
    def extract_signals(text: str, *, max_signals: int = 20) -> list[AMLSignal]:
        cases = _unique_preserve([_normalize(m.group(0)) for m in _CASE_RE.finditer(text)])
        accounts = _unique_preserve([_normalize(m.group(0)) for m in _ACCOUNT_RE.finditer(text)])
        entities = _unique_preserve([_normalize(m.group(0)) for m in _ENTITY_RE.finditer(text)])
        txs = _unique_preserve([_normalize(m.group(0)) for m in _TX_RE.finditer(text)])

        amounts: list[float] = []
        for match in _MONEY_RE.finditer(text):
            try:
                amounts.append(float(match.group(1).replace(",", "")))
            except ValueError:
                continue

        if not cases:
            cases = [f"CASE-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:8].upper()}"]
        if not accounts:
            accounts = ["ACC-AUTO-01"]
        if not entities:
            entities = ["ENT-AUTO-01"]

        rows: list[AMLSignal] = []
        for idx, case_id in enumerate(cases[:max_signals]):
            rows.append(
                AMLSignal(
                    case_id=case_id,
                    account_id=accounts[idx % len(accounts)],
                    entity_id=entities[idx % len(entities)],
                    transaction_id=txs[idx % len(txs)] if txs else None,
                    observed_amount=amounts[idx % len(amounts)] if amounts else None,
                )
            )
        return rows

    @staticmethod
    def _build_batch_id(scenario: str, started_at: datetime) -> str:
        digest = hashlib.sha256(
            f"{started_at.isoformat()}::{scenario}".encode("utf-8")
        ).hexdigest()[:16]
        return f"aml-{started_at.strftime('%Y%m%d%H%M%S')}-{digest}"

    def _run_enrichment(self, signals: list[AMLSignal]) -> list[AMLActionResult]:
        tasks: list[_ExecutionTask] = []

        account_ids = _unique_preserve([signal.account_id for signal in signals])
        for account_id in account_ids:
            tasks.append(
                _ExecutionTask(
                    integration="transaction_graph",
                    operation="lookup",
                    target=account_id,
                    request_payload={"account_id": account_id},
                    idempotency_key=None,
                    call=lambda account_id=account_id: self.transaction_graph_adapter.lookup_account_graph(
                        account_id
                    ),
                )
            )

        entity_ids = _unique_preserve([signal.entity_id for signal in signals])
        for entity_id in entity_ids:
            tasks.append(
                _ExecutionTask(
                    integration="sanctions_screen",
                    operation="screen",
                    target=entity_id,
                    request_payload={"entity_id": entity_id},
                    idempotency_key=None,
                    call=lambda entity_id=entity_id: self.sanctions_screen_adapter.screen_entity(
                        entity_id
                    ),
                )
            )

        return self._execute_tasks(tasks)

    def _build_decisions(
        self,
        signals: list[AMLSignal],
        enrichments: list[AMLActionResult],
    ) -> list[AMLDecision]:
        graph_data: dict[str, dict[str, Any]] = {}
        sanctions_data: dict[str, dict[str, Any]] = {}

        for row in enrichments:
            if not row.success or row.status != "executed":
                continue
            if row.integration == "transaction_graph":
                graph_data[row.target] = row.response or {}
            elif row.integration == "sanctions_screen":
                sanctions_data[row.target] = row.response or {}

        decisions: list[AMLDecision] = []
        for signal in signals:
            graph = graph_data.get(signal.account_id, {})
            sanction = sanctions_data.get(signal.entity_id, {})

            anomaly_score = self._as_float(
                graph,
                keys=("anomaly_score", "risk_score", "score"),
                default=0.35,
            )
            sanctions_match = self._as_float(
                sanction,
                keys=("match_score", "sanctions_score", "score"),
                default=0.02,
                cap_1=True,
            )
            watchlist_hit = bool(
                sanction.get("watchlist_hit", False)
                or sanction.get("sanctions_hit", False)
            )
            high_risk_jurisdictions = list(graph.get("high_risk_jurisdictions", []) or [])

            route: AMLRoute = "monitor"
            rationale: list[str] = []

            if sanctions_match >= self.execution_policy.sanctions_match_threshold or watchlist_hit:
                route = "freeze_and_sar"
                rationale.append("Strong sanctions/watchlist signal detected.")
            elif anomaly_score >= self.execution_policy.anomaly_escalation_threshold:
                route = "sar_only"
                rationale.append("Transaction graph anomaly exceeds escalation threshold.")
            elif anomaly_score >= self.execution_policy.edd_threshold or high_risk_jurisdictions:
                route = "enhanced_due_diligence"
                rationale.append("Moderate anomaly or jurisdictional risk requires EDD.")
            else:
                rationale.append("No immediate escalation threshold hit; continue monitoring.")

            if not graph:
                rationale.append("Transaction graph enrichment missing; confidence reduced.")
            if not sanction:
                rationale.append("Sanctions enrichment missing; confidence reduced.")

            priority = self._priority_for(route=route)
            confidence = self._confidence_for(
                route=route,
                graph_enriched=bool(graph),
                sanctions_enriched=bool(sanction),
            )

            decisions.append(
                AMLDecision(
                    case_id=signal.case_id,
                    account_id=signal.account_id,
                    entity_id=signal.entity_id,
                    route=route,
                    priority=priority,
                    confidence=confidence,
                    anomaly_score=anomaly_score,
                    sanctions_match_score=sanctions_match,
                    watchlist_hit=watchlist_hit,
                    rationale=tuple(rationale),
                )
            )

        decisions.sort(
            key=lambda row: (
                row.route in {"freeze_and_sar", "sar_only", "enhanced_due_diligence"},
                row.priority == "urgent",
                row.sanctions_match_score,
                row.anomaly_score,
            ),
            reverse=True,
        )
        return decisions

    def _run_actions(
        self,
        *,
        batch_id: str,
        decisions: list[AMLDecision],
        execute_actions: bool,
    ) -> list[AMLActionResult]:
        tasks: list[_ExecutionTask] = []
        skipped: list[AMLActionResult] = []

        for row in decisions:
            reason = "; ".join(row.rationale)
            if not execute_actions:
                skipped.append(
                    AMLActionResult(
                        integration="case_actions",
                        operation=row.route,
                        target=row.case_id,
                        success=True,
                        latency_ms=0,
                        request={"case_id": row.case_id, "route": row.route},
                        status="skipped",
                        attempts=0,
                        notes=("action execution disabled by runtime policy",),
                    )
                )
                continue

            if row.route == "monitor":
                skipped.append(
                    AMLActionResult(
                        integration="case_actions",
                        operation="monitor",
                        target=row.case_id,
                        success=True,
                        latency_ms=0,
                        request={"case_id": row.case_id, "route": "monitor"},
                        status="skipped",
                        attempts=0,
                        notes=("monitor route requires no external action call",),
                    )
                )
                continue

            if row.route == "freeze_and_sar":
                if self.execution_policy.allow_auto_freeze:
                    freeze_key = f"{batch_id}:freeze:{row.account_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="case_actions",
                            operation="freeze_account",
                            target=row.account_id,
                            request_payload={"account_id": row.account_id, "reason": reason},
                            idempotency_key=freeze_key,
                            call=lambda account_id=row.account_id, reason=reason: self.case_action_adapter.freeze_account(
                                account_id,
                                reason=reason,
                            ),
                        )
                    )
                else:
                    skipped.append(
                        AMLActionResult(
                            integration="case_actions",
                            operation="freeze_account",
                            target=row.account_id,
                            success=True,
                            latency_ms=0,
                            request={"account_id": row.account_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto freeze disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_sar:
                    sar_key = f"{batch_id}:sar:{row.case_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="case_actions",
                            operation="create_sar",
                            target=row.case_id,
                            request_payload={
                                "case_id": row.case_id,
                                "priority": row.priority,
                                "reason": reason,
                            },
                            idempotency_key=sar_key,
                            call=lambda case_id=row.case_id, priority=row.priority, reason=reason: self.case_action_adapter.create_sar(
                                case_id,
                                priority=priority,
                                reason=reason,
                            ),
                        )
                    )
                else:
                    skipped.append(
                        AMLActionResult(
                            integration="case_actions",
                            operation="create_sar",
                            target=row.case_id,
                            success=True,
                            latency_ms=0,
                            request={"case_id": row.case_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto SAR disabled by policy",),
                        )
                    )
                continue

            if row.route == "sar_only":
                if not self.execution_policy.allow_auto_sar:
                    skipped.append(
                        AMLActionResult(
                            integration="case_actions",
                            operation="create_sar",
                            target=row.case_id,
                            success=True,
                            latency_ms=0,
                            request={"case_id": row.case_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto SAR disabled by policy",),
                        )
                    )
                    continue
                sar_key = f"{batch_id}:sar:{row.case_id}"
                tasks.append(
                    _ExecutionTask(
                        integration="case_actions",
                        operation="create_sar",
                        target=row.case_id,
                        request_payload={
                            "case_id": row.case_id,
                            "priority": row.priority,
                            "reason": reason,
                        },
                        idempotency_key=sar_key,
                        call=lambda case_id=row.case_id, priority=row.priority, reason=reason: self.case_action_adapter.create_sar(
                            case_id,
                            priority=priority,
                            reason=reason,
                        ),
                    )
                )
                continue

            if row.route == "enhanced_due_diligence":
                if not self.execution_policy.allow_auto_edd:
                    skipped.append(
                        AMLActionResult(
                            integration="case_actions",
                            operation="queue_edd",
                            target=row.case_id,
                            success=True,
                            latency_ms=0,
                            request={"case_id": row.case_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto EDD disabled by policy",),
                        )
                    )
                    continue
                edd_key = f"{batch_id}:edd:{row.case_id}"
                tasks.append(
                    _ExecutionTask(
                        integration="case_actions",
                        operation="queue_edd",
                        target=row.case_id,
                        request_payload={"case_id": row.case_id, "reason": reason},
                        idempotency_key=edd_key,
                        call=lambda case_id=row.case_id, reason=reason: self.case_action_adapter.queue_edd(
                            case_id,
                            reason=reason,
                        ),
                    )
                )

        executed = self._execute_tasks(tasks)
        return [*skipped, *executed]

    def _execute_tasks(self, tasks: list[_ExecutionTask]) -> list[AMLActionResult]:
        if not tasks:
            return []

        workers = min(self.execution_policy.max_parallel_tasks, len(tasks))
        if workers == 1:
            return [self._execute_task(task) for task in tasks]

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(self._execute_task, task) for task in tasks]
            return [future.result() for future in futures]

    def _execute_task(self, task: _ExecutionTask) -> AMLActionResult:
        if task.idempotency_key and self.idempotency_store.seen(task.idempotency_key):
            return AMLActionResult(
                integration=task.integration,
                operation=task.operation,
                target=task.target,
                success=True,
                latency_ms=0,
                request=task.request_payload,
                response=None,
                retried=0,
                attempts=0,
                status="skipped",
                idempotency_key=task.idempotency_key,
                notes=("duplicate action suppressed by idempotency store",),
            )

        result = self._execute_with_retry(
            integration=task.integration,
            operation=task.operation,
            target=task.target,
            request_payload=task.request_payload,
            call=task.call,
            idempotency_key=task.idempotency_key,
        )

        if result.success and result.status == "executed" and task.idempotency_key:
            self.idempotency_store.mark(task.idempotency_key, ttl_seconds=self.idempotency_ttl_seconds)
        return result

    def _execute_with_retry(
        self,
        *,
        integration: str,
        operation: str,
        target: str,
        request_payload: dict[str, Any],
        call: Callable[[], dict[str, Any]],
        idempotency_key: str | None,
    ) -> AMLActionResult:
        attempts = max(1, self.retry_attempts)
        retried = 0
        used_attempts = 0
        last_error: str | None = None
        start = time.perf_counter()

        for attempt in range(1, attempts + 1):
            used_attempts = attempt
            try:
                response = call()
                latency_ms = int((time.perf_counter() - start) * 1000)
                return AMLActionResult(
                    integration=integration,
                    operation=operation,
                    target=target,
                    success=True,
                    latency_ms=latency_ms,
                    request=request_payload,
                    response=response,
                    retried=retried,
                    attempts=used_attempts,
                    status="executed",
                    idempotency_key=idempotency_key,
                )
            except Exception as exc:  # noqa: BLE001 - runtime integration failure capture
                last_error = str(exc)
                if attempt >= attempts or not self._is_retryable_error(exc):
                    break
                retried += 1
                time.sleep(self.retry_backoff_seconds * attempt)

        latency_ms = int((time.perf_counter() - start) * 1000)
        return AMLActionResult(
            integration=integration,
            operation=operation,
            target=target,
            success=False,
            latency_ms=latency_ms,
            request=request_payload,
            error=last_error or "unknown error",
            retried=retried,
            attempts=used_attempts,
            status="executed",
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        text = str(exc).lower()
        markers = (
            "timeout",
            "tempor",
            "rate limit",
            "connection reset",
            "connection aborted",
            "unavailable",
            "502",
            "503",
            "504",
            "429",
        )
        return any(marker in text for marker in markers)

    def _log_audit_event(
        self,
        *,
        batch_id: str,
        mode: str,
        row: AMLActionResult,
    ) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "batch_id": batch_id,
            "mode": mode,
            "integration": row.integration,
            "operation": row.operation,
            "target": row.target,
            "status": row.status,
            "success": row.success,
            "latency_ms": row.latency_ms,
            "attempts": row.attempts,
            "retried": row.retried,
            "idempotency_key": row.idempotency_key,
            "request": self._safe_payload(row.request),
            "response": self._safe_payload(row.response),
            "error": row.error,
            "notes": list(row.notes),
        }
        self.audit_logger.log(event)

    @staticmethod
    def _safe_payload(payload: Any, *, max_chars: int = 900) -> Any:
        if payload is None:
            return None
        try:
            encoded = json.dumps(payload, separators=(",", ":"), default=str)
        except Exception:  # noqa: BLE001
            return str(payload)[:max_chars]
        if len(encoded) <= max_chars:
            return payload
        return {
            "truncated": True,
            "size": len(encoded),
            "preview": encoded[:max_chars],
        }

    @staticmethod
    def _as_float(
        data: dict[str, Any],
        *,
        keys: tuple[str, ...],
        default: float,
        cap_1: bool = True,
    ) -> float:
        for key in keys:
            value = data.get(key)
            if value is None:
                continue
            try:
                out = float(value)
            except Exception:  # noqa: BLE001
                continue
            if cap_1 and out > 1.0:
                out = out / 100.0
            if cap_1:
                out = max(0.0, min(1.0, out))
            return out
        return default

    @staticmethod
    def _priority_for(*, route: AMLRoute) -> str:
        if route == "freeze_and_sar":
            return "urgent"
        if route == "sar_only":
            return "high"
        if route == "enhanced_due_diligence":
            return "normal"
        return "low"

    @staticmethod
    def _confidence_for(
        *,
        route: AMLRoute,
        graph_enriched: bool,
        sanctions_enriched: bool,
    ) -> float:
        base = {
            "freeze_and_sar": 0.92,
            "sar_only": 0.86,
            "enhanced_due_diligence": 0.78,
            "monitor": 0.7,
        }[route]
        if not graph_enriched:
            base -= 0.15
        if not sanctions_enriched:
            base -= 0.15
        return round(min(0.99, max(0.05, base)), 3)

    @staticmethod
    def _build_stats(
        *,
        signals: list[AMLSignal],
        enrichments: list[AMLActionResult],
        decisions: list[AMLDecision],
        actions: list[AMLActionResult],
    ) -> AMLExecutionStats:
        route_counts: dict[AMLRoute, int] = defaultdict(int)
        for row in decisions:
            route_counts[row.route] += 1

        actions_success = sum(1 for row in actions if row.success and row.status == "executed")
        actions_skipped = sum(1 for row in actions if row.status == "skipped")
        actions_failed = sum(1 for row in actions if not row.success)

        return AMLExecutionStats(
            signals_total=len(signals),
            enrichment_total=len(enrichments),
            enrichment_success=sum(1 for row in enrichments if row.success),
            actions_total=len(actions),
            actions_success=actions_success,
            actions_skipped=actions_skipped,
            actions_failed=actions_failed,
            freeze_sar_count=route_counts["freeze_and_sar"],
            sar_only_count=route_counts["sar_only"],
            edd_count=route_counts["enhanced_due_diligence"],
            monitor_count=route_counts["monitor"],
        )

    @staticmethod
    def _recommendations(
        *,
        pipeline_report: UseCaseExecutionReport,
        stats: AMLExecutionStats,
        decisions: list[AMLDecision],
        errors: list[str],
    ) -> list[str]:
        recs: list[str] = [
            (
                f"Decision mix: freeze+SAR={stats.freeze_sar_count}, SAR-only={stats.sar_only_count}, "
                f"EDD={stats.edd_count}, monitor={stats.monitor_count}."
            ),
            (
                f"Enrichment success {stats.enrichment_success}/{stats.enrichment_total}; "
                f"actions success={stats.actions_success}, skipped={stats.actions_skipped}, failed={stats.actions_failed}."
            ),
            "For freeze+SAR cases, verify beneficial owner network and linked-account contagion.",
            "For SAR-only cases, assemble narrative with transaction typology and time-sequenced evidence.",
            "For EDD cases, request refreshed KYC documents and source-of-funds validation.",
        ]

        if pipeline_report.ranked_actions:
            recs.append(f"Primary tri-provider action: {pipeline_report.ranked_actions[0].action}")

        if errors:
            recs.append("At least one integration failed; route affected cases to manual AML escalation queue.")

        top = decisions[:3]
        if top:
            recs.append(
                "Top-priority cases: "
                + ", ".join(
                    f"{row.case_id}:{row.route}:{row.sanctions_match_score:.2f}:{row.anomaly_score:.2f}"
                    for row in top
                )
                + "."
            )

        return recs
