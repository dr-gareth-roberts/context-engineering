from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from .runtime_base import (
    AuditLogger,
    BaseIntegrationCommanderMixin,
    HTTPJSONAdapterBase,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    IntegrationActionResult,
    IntegrationExecutionTask,
    NoOpAuditLogger,
    unique_preserve as _unique_preserve,
)
from .tri_provider_pipeline import TriProviderPipeline, UseCaseExecutionReport

# Backward-compatible alias.
ContractActionResult = IntegrationActionResult

_ID_SUFFIX_RE = r"(?:[-_][A-Za-z0-9]+|[0-9]{2,}[A-Za-z0-9]*)(?:[-_][A-Za-z0-9]+)*"
_CONTRACT_RE = re.compile(
    rf"\b(?:CONTRACT|AGR|AGREEMENT|MSA|SOW){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_CLAUSE_RE = re.compile(
    rf"\b(?:CLAUSE|SEC|SECTION|TERM|ARTICLE){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_COUNTERPARTY_RE = re.compile(
    rf"\b(?:VENDOR|PARTY|CP|SUPPLIER){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_TERM_MONTHS_RE = re.compile(r"\b(\d{1,4})\s*months?\b", re.IGNORECASE)
_TERM_YEARS_RE = re.compile(r"\b(\d{1,3})\s*years?\b", re.IGNORECASE)
_CAP_MULTIPLIER_RE = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*x\b", re.IGNORECASE)

_RISK_HINT_KEYWORDS = (
    "unlimited liability",
    "broad data use rights",
    "indemnity",
    "ip ownership",
    "audit rights",
    "termination for convenience",
    "exclusivity",
    "auto-renewal",
    "most favored nation",
)
_RISK_HINT_RE = re.compile(
    "|".join(re.escape(keyword) for keyword in _RISK_HINT_KEYWORDS), re.IGNORECASE
)
_UNLIMITED_RE = re.compile(
    r"(?:unlimited liability|uncapped liability|no liability cap|without liability cap)",
    re.IGNORECASE,
)
_STRATEGIC_RE = re.compile(
    r"(?:strategic vendor|sole source|single supplier|critical vendor|mission[- ]critical vendor)",
    re.IGNORECASE,
)


def _normalize(value: str) -> str:
    return value.strip().replace("_", "-").upper()


class ClauseRiskAdapter(Protocol):
    def lookup_clause(self, clause_id: str) -> dict[str, Any]: ...


class NegotiationPrecedentAdapter(Protocol):
    def lookup_clause(self, clause_id: str) -> dict[str, Any]: ...


class ContractActionAdapter(Protocol):
    def open_legal_review(self, contract_id: str, *, reason: str) -> dict[str, Any]: ...

    def propose_redline(
        self, clause_id: str, *, fallback_text: str, reason: str
    ) -> dict[str, Any]: ...

    def escalate_exec_approval(self, contract_id: str, *, reason: str) -> dict[str, Any]: ...

    def request_counterparty_revision(self, clause_id: str, *, reason: str) -> dict[str, Any]: ...


class NoOpClauseRiskAdapter:
    def lookup_clause(self, clause_id: str) -> dict[str, Any]:
        return {
            "clause_id": clause_id,
            "clause_severity": 0.35,
            "counterparty_resistance": 0.40,
            "enforceability_risk": 0.30,
            "source": "noop",
        }


class NoOpNegotiationPrecedentAdapter:
    def lookup_clause(self, clause_id: str) -> dict[str, Any]:
        return {
            "clause_id": clause_id,
            "precedent_acceptance_rate": 0.62,
            "fallback_cap_multiplier": 1.0,
            "fallback_text": "Limit liability to 1x fees and narrow data use rights to service delivery purposes.",
            "source": "noop",
        }


class NoOpContractActionAdapter:
    def open_legal_review(self, contract_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "contract_id": contract_id,
            "action": "open_legal_review",
            "reason": reason,
            "status": "noop",
        }

    def propose_redline(self, clause_id: str, *, fallback_text: str, reason: str) -> dict[str, Any]:
        return {
            "clause_id": clause_id,
            "action": "propose_redline",
            "fallback_text": fallback_text,
            "reason": reason,
            "status": "noop",
        }

    def escalate_exec_approval(self, contract_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "contract_id": contract_id,
            "action": "escalate_exec_approval",
            "reason": reason,
            "status": "noop",
        }

    def request_counterparty_revision(self, clause_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "clause_id": clause_id,
            "action": "request_counterparty_revision",
            "reason": reason,
            "status": "noop",
        }


@dataclass(slots=True)
class InMemoryClauseRiskAdapter:
    clauses: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_clause(self, clause_id: str) -> dict[str, Any]:
        clause = _normalize(clause_id)
        payload = self.clauses.get(clause, {})
        severity = float(payload.get("clause_severity", 0.36))
        resistance = float(payload.get("counterparty_resistance", 0.42))
        enforceability = float(payload.get("enforceability_risk", 0.31))
        return {
            "clause_id": clause,
            "clause_severity": max(0.0, min(1.0, severity)),
            "counterparty_resistance": max(0.0, min(1.0, resistance)),
            "enforceability_risk": max(0.0, min(1.0, enforceability)),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryNegotiationPrecedentAdapter:
    clauses: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_clause(self, clause_id: str) -> dict[str, Any]:
        clause = _normalize(clause_id)
        payload = self.clauses.get(clause, {})
        acceptance = float(payload.get("precedent_acceptance_rate", 0.60))
        cap_multiplier = float(payload.get("fallback_cap_multiplier", 1.0))
        fallback_text = str(
            payload.get(
                "fallback_text",
                "Limit liability to 1x fees and restrict data use to contracted services.",
            )
        )
        return {
            "clause_id": clause,
            "precedent_acceptance_rate": max(0.0, min(1.0, acceptance)),
            "fallback_cap_multiplier": max(0.1, cap_multiplier),
            "fallback_text": fallback_text,
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryContractActionAdapter:
    legal_reviews: set[str] = field(default_factory=set)
    redlines: set[str] = field(default_factory=set)
    exec_escalations: set[str] = field(default_factory=set)
    revision_requests: set[str] = field(default_factory=set)

    def open_legal_review(self, contract_id: str, *, reason: str) -> dict[str, Any]:
        contract = _normalize(contract_id)
        self.legal_reviews.add(contract)
        return {
            "contract_id": contract,
            "action": "open_legal_review",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def propose_redline(self, clause_id: str, *, fallback_text: str, reason: str) -> dict[str, Any]:
        clause = _normalize(clause_id)
        self.redlines.add(clause)
        return {
            "clause_id": clause,
            "action": "propose_redline",
            "fallback_text": fallback_text,
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def escalate_exec_approval(self, contract_id: str, *, reason: str) -> dict[str, Any]:
        contract = _normalize(contract_id)
        self.exec_escalations.add(contract)
        return {
            "contract_id": contract,
            "action": "escalate_exec_approval",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def request_counterparty_revision(self, clause_id: str, *, reason: str) -> dict[str, Any]:
        clause = _normalize(clause_id)
        self.revision_requests.add(clause)
        return {
            "clause_id": clause,
            "action": "request_counterparty_revision",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }


_HTTPJSONAdapterBase = HTTPJSONAdapterBase


@dataclass(slots=True)
class HTTPClauseRiskAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/contract/clause_risk"

    def lookup_clause(self, clause_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"clause_id": clause_id})


@dataclass(slots=True)
class HTTPNegotiationPrecedentAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/contract/precedent"

    def lookup_clause(self, clause_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"clause_id": clause_id})


@dataclass(slots=True)
class HTTPContractActionAdapter(HTTPJSONAdapterBase):
    legal_review_path: str = "/contract/open_legal_review"
    redline_path: str = "/contract/propose_redline"
    exec_escalation_path: str = "/contract/escalate_exec_approval"
    revision_request_path: str = "/contract/request_counterparty_revision"

    def open_legal_review(self, contract_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.legal_review_path,
            {"contract_id": contract_id, "reason": reason},
        )

    def propose_redline(self, clause_id: str, *, fallback_text: str, reason: str) -> dict[str, Any]:
        return self._post(
            self.redline_path,
            {"clause_id": clause_id, "fallback_text": fallback_text, "reason": reason},
        )

    def escalate_exec_approval(self, contract_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.exec_escalation_path,
            {"contract_id": contract_id, "reason": reason},
        )

    def request_counterparty_revision(self, clause_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.revision_request_path,
            {"clause_id": clause_id, "reason": reason},
        )


def build_clause_risk_adapter_from_env() -> ClauseRiskAdapter:
    base = os.getenv("CONTRACT_RISK_BASE_URL")
    token = os.getenv("CONTRACT_RISK_API_KEY")
    if base and token:
        path = os.getenv("CONTRACT_RISK_LOOKUP_PATH", "/contract/clause_risk")
        return HTTPClauseRiskAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpClauseRiskAdapter()


def build_negotiation_precedent_adapter_from_env() -> NegotiationPrecedentAdapter:
    base = os.getenv("CONTRACT_PRECEDENT_BASE_URL")
    token = os.getenv("CONTRACT_PRECEDENT_API_KEY")
    if base and token:
        path = os.getenv("CONTRACT_PRECEDENT_LOOKUP_PATH", "/contract/precedent")
        return HTTPNegotiationPrecedentAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpNegotiationPrecedentAdapter()


def build_contract_action_adapter_from_env() -> ContractActionAdapter:
    base = os.getenv("CONTRACT_ACTION_BASE_URL")
    token = os.getenv("CONTRACT_ACTION_API_KEY")
    if base and token:
        return HTTPContractActionAdapter(
            base_url=base,
            api_key=token,
            legal_review_path=os.getenv(
                "CONTRACT_ACTION_LEGAL_REVIEW_PATH",
                "/contract/open_legal_review",
            ),
            redline_path=os.getenv(
                "CONTRACT_ACTION_REDLINE_PATH",
                "/contract/propose_redline",
            ),
            exec_escalation_path=os.getenv(
                "CONTRACT_ACTION_EXEC_ESCALATION_PATH",
                "/contract/escalate_exec_approval",
            ),
            revision_request_path=os.getenv(
                "CONTRACT_ACTION_REVISION_REQUEST_PATH",
                "/contract/request_counterparty_revision",
            ),
        )
    return NoOpContractActionAdapter()


ContractRoute = Literal[
    "hardline_redline_and_exec_escalation",
    "legal_review_and_counterproposal",
    "standard_counterproposal",
    "monitor",
]


@dataclass(slots=True, frozen=True)
class ContractSignal:
    contract_id: str
    clause_id: str
    counterparty_id: str
    risk_hint: str | None
    observed_term_months: int | None
    observed_liability_cap_multiplier: float | None
    unlimited_liability_indicator: bool
    strategic_counterparty_indicator: bool


@dataclass(slots=True, frozen=True)
class ContractDecision:
    contract_id: str
    clause_id: str
    counterparty_id: str
    route: ContractRoute
    priority: str
    confidence: float
    risk_score: float
    clause_severity: float
    counterparty_resistance: float
    enforceability_risk: float
    precedent_acceptance_rate: float
    fallback_cap_multiplier: float
    term_months: int
    recommended_fallback_text: str
    rationale: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ContractExecutionPolicy:
    execute_actions_in_dry_run: bool = False
    max_parallel_tasks: int = 6
    max_contracts_to_process: int = 20
    hardline_risk_threshold: float = 0.82
    legal_review_risk_threshold: float = 0.58
    standard_counterproposal_risk_threshold: float = 0.36
    long_term_months_threshold: int = 36
    high_cap_multiplier_threshold: float = 2.5
    allow_auto_legal_review: bool = True
    allow_auto_redline: bool = True
    allow_auto_exec_escalation: bool = True
    allow_auto_revision_request: bool = True

    def __post_init__(self) -> None:
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be >= 1")
        if self.max_contracts_to_process < 1:
            raise ValueError("max_contracts_to_process must be >= 1")
        if self.long_term_months_threshold < 1:
            raise ValueError("long_term_months_threshold must be >= 1")
        if self.high_cap_multiplier_threshold <= 0:
            raise ValueError("high_cap_multiplier_threshold must be > 0")
        for name, value in (
            ("hardline_risk_threshold", self.hardline_risk_threshold),
            ("legal_review_risk_threshold", self.legal_review_risk_threshold),
            (
                "standard_counterproposal_risk_threshold",
                self.standard_counterproposal_risk_threshold,
            ),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(slots=True, frozen=True)
class ContractExecutionStats:
    contracts_total: int
    enrichment_total: int
    enrichment_success: int
    actions_total: int
    actions_success: int
    actions_skipped: int
    actions_failed: int
    hardline_count: int
    legal_review_count: int
    counterproposal_count: int
    monitor_count: int


@dataclass(slots=True, frozen=True)
class ContractExecutionReport:
    batch_id: str
    pipeline_report: UseCaseExecutionReport
    mode: str
    started_at: datetime
    completed_at: datetime
    signals: tuple[ContractSignal, ...]
    enrichments: tuple[ContractActionResult, ...]
    decisions: tuple[ContractDecision, ...]
    actions: tuple[ContractActionResult, ...]
    stats: ContractExecutionStats
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


_ExecutionTask = IntegrationExecutionTask


@dataclass(slots=True)
class ContractNegotiationCommander(BaseIntegrationCommanderMixin):
    pipeline: TriProviderPipeline
    clause_risk_adapter: ClauseRiskAdapter
    precedent_adapter: NegotiationPrecedentAdapter
    action_adapter: ContractActionAdapter
    execution_policy: ContractExecutionPolicy = field(default_factory=ContractExecutionPolicy)
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
    ) -> ContractExecutionReport:
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
            max_signals=self.execution_policy.max_contracts_to_process,
        )

        enrichments = self._run_enrichment(signals)
        decisions = self._build_decisions(signals, enrichments)

        execute_actions = True
        if mode == "dry" and not self.execution_policy.execute_actions_in_dry_run:
            execute_actions = False
            warnings.append("Contract negotiation actions skipped in dry mode by execution policy.")

        actions = self._run_actions(
            batch_id=batch_id,
            decisions=decisions,
            execute_actions=execute_actions,
        )

        for row in (*enrichments, *actions):
            if not row.success:
                errors.append(
                    f"{row.integration}.{row.operation} failed for {row.target}: {row.error}"
                )
            self._log_integration_audit_event(batch_id=batch_id, mode=mode, row=row)

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
        return ContractExecutionReport(
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
    def extract_signals(text: str, *, max_signals: int = 20) -> list[ContractSignal]:
        contract_matches = list(_CONTRACT_RE.finditer(text))
        clauses = [_normalize(m.group(0)) for m in _CLAUSE_RE.finditer(text)]
        counterparties = [_normalize(m.group(0)) for m in _COUNTERPARTY_RE.finditer(text)]
        term_month_values = [int(m.group(1)) for m in _TERM_MONTHS_RE.finditer(text)]
        term_month_values.extend(int(m.group(1)) * 12 for m in _TERM_YEARS_RE.finditer(text))
        cap_values = [float(m.group(1)) for m in _CAP_MULTIPLIER_RE.finditer(text)]
        risk_hints = [m.group(0).lower() for m in _RISK_HINT_RE.finditer(text)]
        has_unlimited = bool(_UNLIMITED_RE.search(text))
        has_strategic = bool(_STRATEGIC_RE.search(text))

        def _pick(values: list[str], index: int, default: str) -> str:
            if not values:
                return default
            if index < len(values):
                return values[index]
            return values[-1]

        def _pick_int(values: list[int], index: int) -> int | None:
            if not values:
                return None
            if index < len(values):
                return values[index]
            return values[-1]

        def _pick_float(values: list[float], index: int) -> float | None:
            if not values:
                return None
            if index < len(values):
                return values[index]
            return values[-1]

        if not contract_matches:
            contract_id = f"CONTRACT-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:8].upper()}"
            return [
                ContractSignal(
                    contract_id=contract_id,
                    clause_id=_pick(clauses, 0, "CLAUSE-AUTO-01"),
                    counterparty_id=_pick(counterparties, 0, "VENDOR-AUTO-01"),
                    risk_hint=_pick(risk_hints, 0, "") or None,
                    observed_term_months=_pick_int(term_month_values, 0),
                    observed_liability_cap_multiplier=_pick_float(cap_values, 0),
                    unlimited_liability_indicator=has_unlimited,
                    strategic_counterparty_indicator=has_strategic,
                )
            ]

        rows: list[ContractSignal] = []
        seen_contracts: set[str] = set()
        for idx, match in enumerate(contract_matches):
            if len(rows) >= max_signals:
                break

            contract_id = _normalize(match.group(0))
            key = contract_id.lower()
            if key in seen_contracts:
                continue
            seen_contracts.add(key)

            segment_index = len(rows)
            start = match.start()
            end = (
                contract_matches[idx + 1].start() if idx + 1 < len(contract_matches) else len(text)
            )
            segment = text[start:end]

            clause_match = _CLAUSE_RE.search(segment)
            counterparty_match = _COUNTERPARTY_RE.search(segment)
            term_month_match = _TERM_MONTHS_RE.search(segment)
            term_year_match = _TERM_YEARS_RE.search(segment)
            cap_match = _CAP_MULTIPLIER_RE.search(segment)
            risk_hint_match = _RISK_HINT_RE.search(segment)
            unlimited_match = _UNLIMITED_RE.search(segment)
            strategic_match = _STRATEGIC_RE.search(segment)

            observed_term_months: int | None = None
            if term_month_match:
                observed_term_months = int(term_month_match.group(1))
            elif term_year_match:
                observed_term_months = int(term_year_match.group(1)) * 12
            else:
                observed_term_months = _pick_int(term_month_values, segment_index)

            rows.append(
                ContractSignal(
                    contract_id=contract_id,
                    clause_id=_normalize(clause_match.group(0))
                    if clause_match
                    else _pick(clauses, segment_index, "CLAUSE-AUTO-01"),
                    counterparty_id=_normalize(counterparty_match.group(0))
                    if counterparty_match
                    else _pick(counterparties, segment_index, "VENDOR-AUTO-01"),
                    risk_hint=risk_hint_match.group(0).lower()
                    if risk_hint_match
                    else (_pick(risk_hints, segment_index, "") or None),
                    observed_term_months=observed_term_months,
                    observed_liability_cap_multiplier=float(cap_match.group(1))
                    if cap_match
                    else _pick_float(cap_values, segment_index),
                    unlimited_liability_indicator=bool(unlimited_match) or has_unlimited,
                    strategic_counterparty_indicator=bool(strategic_match) or has_strategic,
                )
            )

        return rows

    @staticmethod
    def _build_batch_id(scenario: str, started_at: datetime) -> str:
        digest = hashlib.sha256(
            f"{started_at.isoformat()}::{scenario}".encode("utf-8")
        ).hexdigest()[:16]
        return f"contract-{started_at.strftime('%Y%m%d%H%M%S')}-{digest}"

    def _run_enrichment(self, signals: list[ContractSignal]) -> list[ContractActionResult]:
        tasks: list[_ExecutionTask] = []

        clause_ids = _unique_preserve([signal.clause_id for signal in signals])
        for clause_id in clause_ids:
            tasks.append(
                _ExecutionTask(
                    integration="clause_risk",
                    operation="lookup_clause",
                    target=clause_id,
                    request_payload={"clause_id": clause_id},
                    idempotency_key=None,
                    call=lambda clause_id=clause_id: self.clause_risk_adapter.lookup_clause(
                        clause_id
                    ),
                )
            )
            tasks.append(
                _ExecutionTask(
                    integration="precedent",
                    operation="lookup_clause",
                    target=clause_id,
                    request_payload={"clause_id": clause_id},
                    idempotency_key=None,
                    call=lambda clause_id=clause_id: self.precedent_adapter.lookup_clause(
                        clause_id
                    ),
                )
            )
        return self._execute_integration_tasks(tasks)

    def _build_decisions(
        self,
        signals: list[ContractSignal],
        enrichments: list[ContractActionResult],
    ) -> list[ContractDecision]:
        clause_risk_data: dict[str, dict[str, Any]] = {}
        precedent_data: dict[str, dict[str, Any]] = {}

        for row in enrichments:
            if not row.success or row.status != "executed":
                continue
            if row.integration == "clause_risk":
                clause_risk_data[row.target] = row.response or {}
            elif row.integration == "precedent":
                precedent_data[row.target] = row.response or {}

        decisions: list[ContractDecision] = []
        for signal in signals:
            clause_risk = clause_risk_data.get(signal.clause_id, {})
            precedent = precedent_data.get(signal.clause_id, {})

            clause_severity = self._as_float(
                clause_risk,
                keys=("clause_severity", "severity", "risk_score"),
                default=0.36,
            )
            counterparty_resistance = self._as_float(
                clause_risk,
                keys=("counterparty_resistance", "resistance"),
                default=0.40,
            )
            enforceability_risk = self._as_float(
                clause_risk,
                keys=("enforceability_risk", "enforcement_risk"),
                default=0.32,
            )
            precedent_acceptance_rate = self._as_float(
                precedent,
                keys=("precedent_acceptance_rate", "acceptance_rate"),
                default=0.60,
            )
            fallback_cap_multiplier = self._as_float(
                precedent,
                keys=("fallback_cap_multiplier", "cap_multiplier"),
                default=float(signal.observed_liability_cap_multiplier or 1.0),
                cap_1=False,
            )
            if fallback_cap_multiplier <= 0:
                fallback_cap_multiplier = 1.0

            term_months = signal.observed_term_months or 24
            cap_multiplier = signal.observed_liability_cap_multiplier or fallback_cap_multiplier
            cap_risk = (
                1.0 if signal.unlimited_liability_indicator else min(1.0, cap_multiplier / 4.0)
            )
            term_risk = min(1.0, term_months / 60.0)
            hint_risk = 0.0
            if signal.risk_hint in {"unlimited liability", "broad data use rights", "indemnity"}:
                hint_risk = 0.08

            risk_score = min(
                1.0,
                clause_severity * 0.30
                + counterparty_resistance * 0.15
                + enforceability_risk * 0.14
                + (1.0 - precedent_acceptance_rate) * 0.10
                + cap_risk * 0.11
                + term_risk * 0.08
                + hint_risk
                + (0.10 if signal.unlimited_liability_indicator else 0.0)
                + (0.08 if signal.strategic_counterparty_indicator else 0.0),
            )

            route: ContractRoute = "monitor"
            rationale: list[str] = []
            if (
                risk_score >= self.execution_policy.hardline_risk_threshold
                or signal.unlimited_liability_indicator
                or (
                    cap_multiplier >= self.execution_policy.high_cap_multiplier_threshold
                    and clause_severity >= 0.70
                )
            ):
                route = "hardline_redline_and_exec_escalation"
                rationale.append("Risk profile requires hardline redline and executive escalation.")
            elif risk_score >= self.execution_policy.legal_review_risk_threshold:
                route = "legal_review_and_counterproposal"
                rationale.append(
                    "Elevated legal/commercial risk requires legal review and counterproposal."
                )
            elif risk_score >= self.execution_policy.standard_counterproposal_risk_threshold:
                route = "standard_counterproposal"
                rationale.append("Moderate risk supports standard counterproposal strategy.")
            else:
                rationale.append("Current contract risk supports monitoring and selective edits.")

            if not clause_risk:
                rationale.append("Clause-risk enrichment missing; confidence reduced.")
            if not precedent:
                rationale.append("Precedent enrichment missing; confidence reduced.")

            recommended_fallback_text = str(
                precedent.get(
                    "fallback_text",
                    "Limit liability to 1x fees and restrict data rights to service delivery and support.",
                )
            )

            priority = self._priority_for(route)
            confidence = self._confidence_for(
                route=route,
                clause_risk_enriched=bool(clause_risk),
                precedent_enriched=bool(precedent),
            )

            decisions.append(
                ContractDecision(
                    contract_id=signal.contract_id,
                    clause_id=signal.clause_id,
                    counterparty_id=signal.counterparty_id,
                    route=route,
                    priority=priority,
                    confidence=confidence,
                    risk_score=risk_score,
                    clause_severity=clause_severity,
                    counterparty_resistance=counterparty_resistance,
                    enforceability_risk=enforceability_risk,
                    precedent_acceptance_rate=precedent_acceptance_rate,
                    fallback_cap_multiplier=fallback_cap_multiplier,
                    term_months=max(0, term_months),
                    recommended_fallback_text=recommended_fallback_text,
                    rationale=tuple(rationale),
                )
            )

        decisions.sort(
            key=lambda row: (
                row.route
                in {"hardline_redline_and_exec_escalation", "legal_review_and_counterproposal"},
                row.priority == "urgent",
                row.risk_score,
            ),
            reverse=True,
        )
        return decisions

    def _run_actions(
        self,
        *,
        batch_id: str,
        decisions: list[ContractDecision],
        execute_actions: bool,
    ) -> list[ContractActionResult]:
        tasks: list[_ExecutionTask] = []
        skipped: list[ContractActionResult] = []

        for row in decisions:
            reason = "; ".join(row.rationale)
            if not execute_actions:
                skipped.append(
                    ContractActionResult(
                        integration="contract_actions",
                        operation=row.route,
                        target=row.contract_id,
                        success=True,
                        latency_ms=0,
                        request={"contract_id": row.contract_id, "route": row.route},
                        status="skipped",
                        attempts=0,
                        notes=("action execution disabled by runtime policy",),
                    )
                )
                continue

            if row.route == "monitor":
                skipped.append(
                    ContractActionResult(
                        integration="contract_actions",
                        operation="monitor",
                        target=row.contract_id,
                        success=True,
                        latency_ms=0,
                        request={"contract_id": row.contract_id, "route": "monitor"},
                        status="skipped",
                        attempts=0,
                        notes=("monitor route requires no external action call",),
                    )
                )
                continue

            if row.route == "hardline_redline_and_exec_escalation":
                if self.execution_policy.allow_auto_legal_review:
                    legal_key = f"{batch_id}:legal:{row.contract_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="contract_actions",
                            operation="open_legal_review",
                            target=row.contract_id,
                            request_payload={"contract_id": row.contract_id, "reason": reason},
                            idempotency_key=legal_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.open_legal_review(
                                    row.contract_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ContractActionResult(
                            integration="contract_actions",
                            operation="open_legal_review",
                            target=row.contract_id,
                            success=True,
                            latency_ms=0,
                            request={"contract_id": row.contract_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto legal review disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_redline:
                    redline_key = f"{batch_id}:redline:{row.clause_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="contract_actions",
                            operation="propose_redline",
                            target=row.clause_id,
                            request_payload={
                                "clause_id": row.clause_id,
                                "fallback_text": row.recommended_fallback_text,
                                "reason": reason,
                            },
                            idempotency_key=redline_key,
                            call=lambda row=row, reason=reason: self.action_adapter.propose_redline(
                                row.clause_id,
                                fallback_text=row.recommended_fallback_text,
                                reason=reason,
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ContractActionResult(
                            integration="contract_actions",
                            operation="propose_redline",
                            target=row.clause_id,
                            success=True,
                            latency_ms=0,
                            request={"clause_id": row.clause_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto redline proposal disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_exec_escalation:
                    exec_key = f"{batch_id}:exec:{row.contract_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="contract_actions",
                            operation="escalate_exec_approval",
                            target=row.contract_id,
                            request_payload={"contract_id": row.contract_id, "reason": reason},
                            idempotency_key=exec_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.escalate_exec_approval(
                                    row.contract_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ContractActionResult(
                            integration="contract_actions",
                            operation="escalate_exec_approval",
                            target=row.contract_id,
                            success=True,
                            latency_ms=0,
                            request={"contract_id": row.contract_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto executive escalation disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_revision_request:
                    revision_key = f"{batch_id}:revision:{row.clause_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="contract_actions",
                            operation="request_counterparty_revision",
                            target=row.clause_id,
                            request_payload={"clause_id": row.clause_id, "reason": reason},
                            idempotency_key=revision_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.request_counterparty_revision(
                                    row.clause_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ContractActionResult(
                            integration="contract_actions",
                            operation="request_counterparty_revision",
                            target=row.clause_id,
                            success=True,
                            latency_ms=0,
                            request={"clause_id": row.clause_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto revision request disabled by policy",),
                        )
                    )
                continue

            if row.route == "legal_review_and_counterproposal":
                if self.execution_policy.allow_auto_legal_review:
                    legal_key = f"{batch_id}:legal:{row.contract_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="contract_actions",
                            operation="open_legal_review",
                            target=row.contract_id,
                            request_payload={"contract_id": row.contract_id, "reason": reason},
                            idempotency_key=legal_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.open_legal_review(
                                    row.contract_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ContractActionResult(
                            integration="contract_actions",
                            operation="open_legal_review",
                            target=row.contract_id,
                            success=True,
                            latency_ms=0,
                            request={"contract_id": row.contract_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto legal review disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_redline:
                    redline_key = f"{batch_id}:redline:{row.clause_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="contract_actions",
                            operation="propose_redline",
                            target=row.clause_id,
                            request_payload={
                                "clause_id": row.clause_id,
                                "fallback_text": row.recommended_fallback_text,
                                "reason": reason,
                            },
                            idempotency_key=redline_key,
                            call=lambda row=row, reason=reason: self.action_adapter.propose_redline(
                                row.clause_id,
                                fallback_text=row.recommended_fallback_text,
                                reason=reason,
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ContractActionResult(
                            integration="contract_actions",
                            operation="propose_redline",
                            target=row.clause_id,
                            success=True,
                            latency_ms=0,
                            request={"clause_id": row.clause_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto redline proposal disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_revision_request:
                    revision_key = f"{batch_id}:revision:{row.clause_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="contract_actions",
                            operation="request_counterparty_revision",
                            target=row.clause_id,
                            request_payload={"clause_id": row.clause_id, "reason": reason},
                            idempotency_key=revision_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.request_counterparty_revision(
                                    row.clause_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ContractActionResult(
                            integration="contract_actions",
                            operation="request_counterparty_revision",
                            target=row.clause_id,
                            success=True,
                            latency_ms=0,
                            request={"clause_id": row.clause_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto revision request disabled by policy",),
                        )
                    )
                continue

            if row.route == "standard_counterproposal":
                if self.execution_policy.allow_auto_redline:
                    redline_key = f"{batch_id}:redline:{row.clause_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="contract_actions",
                            operation="propose_redline",
                            target=row.clause_id,
                            request_payload={
                                "clause_id": row.clause_id,
                                "fallback_text": row.recommended_fallback_text,
                                "reason": reason,
                            },
                            idempotency_key=redline_key,
                            call=lambda row=row, reason=reason: self.action_adapter.propose_redline(
                                row.clause_id,
                                fallback_text=row.recommended_fallback_text,
                                reason=reason,
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ContractActionResult(
                            integration="contract_actions",
                            operation="propose_redline",
                            target=row.clause_id,
                            success=True,
                            latency_ms=0,
                            request={"clause_id": row.clause_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto redline proposal disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_revision_request:
                    revision_key = f"{batch_id}:revision:{row.clause_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="contract_actions",
                            operation="request_counterparty_revision",
                            target=row.clause_id,
                            request_payload={"clause_id": row.clause_id, "reason": reason},
                            idempotency_key=revision_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.request_counterparty_revision(
                                    row.clause_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ContractActionResult(
                            integration="contract_actions",
                            operation="request_counterparty_revision",
                            target=row.clause_id,
                            success=True,
                            latency_ms=0,
                            request={"clause_id": row.clause_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto revision request disabled by policy",),
                        )
                    )
                continue

        executed = self._execute_integration_tasks(tasks)
        return [*skipped, *executed]

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
    def _priority_for(route: ContractRoute) -> str:
        if route == "hardline_redline_and_exec_escalation":
            return "urgent"
        if route == "legal_review_and_counterproposal":
            return "high"
        if route == "standard_counterproposal":
            return "normal"
        return "low"

    @staticmethod
    def _confidence_for(
        *,
        route: ContractRoute,
        clause_risk_enriched: bool,
        precedent_enriched: bool,
    ) -> float:
        base = {
            "hardline_redline_and_exec_escalation": 0.90,
            "legal_review_and_counterproposal": 0.84,
            "standard_counterproposal": 0.76,
            "monitor": 0.68,
        }[route]
        if not clause_risk_enriched:
            base -= 0.15
        if not precedent_enriched:
            base -= 0.15
        return round(min(0.99, max(0.05, base)), 3)

    @staticmethod
    def _build_stats(
        *,
        signals: list[ContractSignal],
        enrichments: list[ContractActionResult],
        decisions: list[ContractDecision],
        actions: list[ContractActionResult],
    ) -> ContractExecutionStats:
        route_counts: dict[ContractRoute, int] = defaultdict(int)
        for row in decisions:
            route_counts[row.route] += 1

        actions_success = sum(1 for row in actions if row.success and row.status == "executed")
        actions_skipped = sum(1 for row in actions if row.status == "skipped")
        actions_failed = sum(1 for row in actions if not row.success)

        return ContractExecutionStats(
            contracts_total=len(signals),
            enrichment_total=len(enrichments),
            enrichment_success=sum(1 for row in enrichments if row.success),
            actions_total=len(actions),
            actions_success=actions_success,
            actions_skipped=actions_skipped,
            actions_failed=actions_failed,
            hardline_count=route_counts["hardline_redline_and_exec_escalation"],
            legal_review_count=route_counts["legal_review_and_counterproposal"],
            counterproposal_count=route_counts["standard_counterproposal"],
            monitor_count=route_counts["monitor"],
        )

    @staticmethod
    def _recommendations(
        *,
        pipeline_report: UseCaseExecutionReport,
        stats: ContractExecutionStats,
        decisions: list[ContractDecision],
        errors: list[str],
    ) -> list[str]:
        recs: list[str] = [
            (
                "Decision mix: "
                f"hardline={stats.hardline_count}, "
                f"legal_review={stats.legal_review_count}, "
                f"counterproposal={stats.counterproposal_count}, monitor={stats.monitor_count}."
            ),
            (
                f"Enrichment success {stats.enrichment_success}/{stats.enrichment_total}; "
                f"actions success={stats.actions_success}, skipped={stats.actions_skipped}, failed={stats.actions_failed}."
            ),
            "For hardline cases, lock redline fallback positions and exec escalation criteria before counterparty calls.",
            "For legal-review cases, align legal/commercial tradeoffs and maintain concession guardrails.",
            "For standard-counterproposal cases, track counterparty response latency and fallback usage.",
        ]

        if pipeline_report.ranked_actions:
            recs.append(f"Primary tri-provider action: {pipeline_report.ranked_actions[0].action}")

        if errors:
            recs.append(
                "At least one integration failed; escalate impacted clauses to manual legal review."
            )

        top = decisions[:3]
        if top:
            recs.append(
                "Top contracts: "
                + ", ".join(
                    f"{row.contract_id}:{row.route}:{row.risk_score:.2f}:{row.clause_id}"
                    for row in top
                )
                + "."
            )

        return recs
