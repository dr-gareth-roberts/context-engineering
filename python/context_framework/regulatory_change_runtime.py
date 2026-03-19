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
RegulatoryActionResult = IntegrationActionResult

_ID_SUFFIX_RE = r"(?:[-_][A-Za-z0-9]+|[0-9]{2,}[A-Za-z0-9]*)(?:[-_][A-Za-z0-9]+)*"
_REQUIREMENT_RE = re.compile(
    rf"\b(?:REG|RULE|LAW|ACT|REQ){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_DOMAIN_RE = re.compile(
    rf"\b(?:DOMAIN|CONTROL|POLICY|AREA){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_OWNER_RE = re.compile(
    rf"\b(?:TEAM|OWNER|SQUAD){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_DEADLINE_DAYS_RE = re.compile(r"\b(\d{1,4})\s*days?\b", re.IGNORECASE)
_OBLIGATION_COUNT_RE = re.compile(
    r"\b(\d{1,3})\s*(?:obligations?|requirements?|controls?)\b",
    re.IGNORECASE,
)

_OBLIGATION_KEYWORDS = (
    "model inventory",
    "risk tier",
    "attestation",
    "audit",
    "incident reporting",
    "data retention",
    "human oversight",
    "monitoring",
    "transparency",
)
_OBLIGATION_RE = re.compile(
    "|".join(re.escape(keyword) for keyword in _OBLIGATION_KEYWORDS), re.IGNORECASE
)
_ENFORCEMENT_RE = re.compile(
    r"(?:mandatory|required|must comply|enforcement|fine|penalty|non-compliance)",
    re.IGNORECASE,
)


def _normalize(value: str) -> str:
    return value.strip().replace("_", "-").upper()


class RegulationIntelAdapter(Protocol):
    def lookup_requirement(self, requirement_id: str) -> dict[str, Any]: ...


class ControlCoverageAdapter(Protocol):
    def lookup_domain(self, domain_id: str) -> dict[str, Any]: ...


class ComplianceActionAdapter(Protocol):
    def open_remediation_program(self, requirement_id: str, *, reason: str) -> dict[str, Any]: ...

    def create_control_gap_tasks(self, domain_id: str, *, reason: str) -> dict[str, Any]: ...

    def publish_policy_update(self, domain_id: str, *, reason: str) -> dict[str, Any]: ...

    def schedule_attestation(self, requirement_id: str, *, reason: str) -> dict[str, Any]: ...

    def assign_training(self, owner_id: str, *, reason: str) -> dict[str, Any]: ...


class NoOpRegulationIntelAdapter:
    def lookup_requirement(self, requirement_id: str) -> dict[str, Any]:
        return {
            "requirement_id": requirement_id,
            "obligation_severity": 0.35,
            "deadline_days": 140,
            "penalty_risk": 0.30,
            "obligations_count": 5,
            "source": "noop",
        }


class NoOpControlCoverageAdapter:
    def lookup_domain(self, domain_id: str) -> dict[str, Any]:
        return {
            "domain_id": domain_id,
            "coverage_pct": 0.72,
            "open_findings": 2,
            "evidence_freshness_days": 35,
            "source": "noop",
        }


class NoOpComplianceActionAdapter:
    def open_remediation_program(self, requirement_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "requirement_id": requirement_id,
            "action": "open_remediation_program",
            "reason": reason,
            "status": "noop",
        }

    def create_control_gap_tasks(self, domain_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "domain_id": domain_id,
            "action": "create_control_gap_tasks",
            "reason": reason,
            "status": "noop",
        }

    def publish_policy_update(self, domain_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "domain_id": domain_id,
            "action": "publish_policy_update",
            "reason": reason,
            "status": "noop",
        }

    def schedule_attestation(self, requirement_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "requirement_id": requirement_id,
            "action": "schedule_attestation",
            "reason": reason,
            "status": "noop",
        }

    def assign_training(self, owner_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "owner_id": owner_id,
            "action": "assign_training",
            "reason": reason,
            "status": "noop",
        }


@dataclass(slots=True)
class InMemoryRegulationIntelAdapter:
    requirements: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_requirement(self, requirement_id: str) -> dict[str, Any]:
        requirement = _normalize(requirement_id)
        payload = self.requirements.get(requirement, {})
        severity = float(payload.get("obligation_severity", 0.38))
        deadline_days = int(payload.get("deadline_days", 150))
        penalty_risk = float(payload.get("penalty_risk", 0.32))
        obligations_count = int(payload.get("obligations_count", 5))
        return {
            "requirement_id": requirement,
            "obligation_severity": max(0.0, min(1.0, severity)),
            "deadline_days": max(0, deadline_days),
            "penalty_risk": max(0.0, min(1.0, penalty_risk)),
            "obligations_count": max(0, obligations_count),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryControlCoverageAdapter:
    domains: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_domain(self, domain_id: str) -> dict[str, Any]:
        domain = _normalize(domain_id)
        payload = self.domains.get(domain, {})
        coverage = float(payload.get("coverage_pct", 0.70))
        open_findings = int(payload.get("open_findings", 2))
        freshness = int(payload.get("evidence_freshness_days", 30))
        return {
            "domain_id": domain,
            "coverage_pct": max(0.0, min(1.0, coverage)),
            "open_findings": max(0, open_findings),
            "evidence_freshness_days": max(0, freshness),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryComplianceActionAdapter:
    remediation_programs: set[str] = field(default_factory=set)
    control_gap_domains: set[str] = field(default_factory=set)
    policy_updates: set[str] = field(default_factory=set)
    attestations: set[str] = field(default_factory=set)
    training_assignments: set[str] = field(default_factory=set)

    def open_remediation_program(self, requirement_id: str, *, reason: str) -> dict[str, Any]:
        requirement = _normalize(requirement_id)
        self.remediation_programs.add(requirement)
        return {
            "requirement_id": requirement,
            "action": "open_remediation_program",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def create_control_gap_tasks(self, domain_id: str, *, reason: str) -> dict[str, Any]:
        domain = _normalize(domain_id)
        self.control_gap_domains.add(domain)
        return {
            "domain_id": domain,
            "action": "create_control_gap_tasks",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def publish_policy_update(self, domain_id: str, *, reason: str) -> dict[str, Any]:
        domain = _normalize(domain_id)
        self.policy_updates.add(domain)
        return {
            "domain_id": domain,
            "action": "publish_policy_update",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def schedule_attestation(self, requirement_id: str, *, reason: str) -> dict[str, Any]:
        requirement = _normalize(requirement_id)
        self.attestations.add(requirement)
        return {
            "requirement_id": requirement,
            "action": "schedule_attestation",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def assign_training(self, owner_id: str, *, reason: str) -> dict[str, Any]:
        owner = _normalize(owner_id)
        self.training_assignments.add(owner)
        return {
            "owner_id": owner,
            "action": "assign_training",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }


_HTTPJSONAdapterBase = HTTPJSONAdapterBase


@dataclass(slots=True)
class HTTPRegulationIntelAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/reg/intel"

    def lookup_requirement(self, requirement_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"requirement_id": requirement_id})


@dataclass(slots=True)
class HTTPControlCoverageAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/reg/coverage"

    def lookup_domain(self, domain_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"domain_id": domain_id})


@dataclass(slots=True)
class HTTPComplianceActionAdapter(HTTPJSONAdapterBase):
    remediation_path: str = "/reg/open_remediation_program"
    control_gap_path: str = "/reg/create_control_gap_tasks"
    policy_update_path: str = "/reg/publish_policy_update"
    attestation_path: str = "/reg/schedule_attestation"
    training_path: str = "/reg/assign_training"

    def open_remediation_program(self, requirement_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.remediation_path,
            {"requirement_id": requirement_id, "reason": reason},
        )

    def create_control_gap_tasks(self, domain_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.control_gap_path,
            {"domain_id": domain_id, "reason": reason},
        )

    def publish_policy_update(self, domain_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.policy_update_path,
            {"domain_id": domain_id, "reason": reason},
        )

    def schedule_attestation(self, requirement_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.attestation_path,
            {"requirement_id": requirement_id, "reason": reason},
        )

    def assign_training(self, owner_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.training_path,
            {"owner_id": owner_id, "reason": reason},
        )


def build_regulation_intel_adapter_from_env() -> RegulationIntelAdapter:
    base = os.getenv("REG_CHANGE_INTEL_BASE_URL")
    token = os.getenv("REG_CHANGE_INTEL_API_KEY")
    if base and token:
        path = os.getenv("REG_CHANGE_INTEL_LOOKUP_PATH", "/reg/intel")
        return HTTPRegulationIntelAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpRegulationIntelAdapter()


def build_control_coverage_adapter_from_env() -> ControlCoverageAdapter:
    base = os.getenv("REG_CHANGE_COVERAGE_BASE_URL")
    token = os.getenv("REG_CHANGE_COVERAGE_API_KEY")
    if base and token:
        path = os.getenv("REG_CHANGE_COVERAGE_LOOKUP_PATH", "/reg/coverage")
        return HTTPControlCoverageAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpControlCoverageAdapter()


def build_compliance_action_adapter_from_env() -> ComplianceActionAdapter:
    base = os.getenv("REG_CHANGE_ACTION_BASE_URL")
    token = os.getenv("REG_CHANGE_ACTION_API_KEY")
    if base and token:
        return HTTPComplianceActionAdapter(
            base_url=base,
            api_key=token,
            remediation_path=os.getenv(
                "REG_CHANGE_ACTION_REMEDIATION_PATH",
                "/reg/open_remediation_program",
            ),
            control_gap_path=os.getenv(
                "REG_CHANGE_ACTION_CONTROL_GAP_PATH",
                "/reg/create_control_gap_tasks",
            ),
            policy_update_path=os.getenv(
                "REG_CHANGE_ACTION_POLICY_UPDATE_PATH",
                "/reg/publish_policy_update",
            ),
            attestation_path=os.getenv(
                "REG_CHANGE_ACTION_ATTESTATION_PATH",
                "/reg/schedule_attestation",
            ),
            training_path=os.getenv(
                "REG_CHANGE_ACTION_TRAINING_PATH",
                "/reg/assign_training",
            ),
        )
    return NoOpComplianceActionAdapter()


RegulatoryRoute = Literal[
    "immediate_remediation_program",
    "accelerated_control_gap_closure",
    "policy_update_and_training",
    "monitor",
]


@dataclass(slots=True, frozen=True)
class RegulatorySignal:
    requirement_id: str
    domain_id: str
    owner_id: str
    obligation_hint: str | None
    observed_deadline_days: int | None
    observed_obligation_count: int | None
    enforcement_indicator: bool


@dataclass(slots=True, frozen=True)
class RegulatoryDecision:
    requirement_id: str
    domain_id: str
    owner_id: str
    route: RegulatoryRoute
    priority: str
    confidence: float
    risk_score: float
    obligation_severity: float
    deadline_days: int
    penalty_risk: float
    obligations_count: int
    coverage_pct: float
    open_findings: int
    evidence_freshness_days: int
    rationale: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class RegulatoryExecutionPolicy:
    execute_actions_in_dry_run: bool = False
    max_parallel_tasks: int = 6
    max_requirements_to_process: int = 20
    immediate_remediation_risk_threshold: float = 0.82
    accelerated_gap_closure_risk_threshold: float = 0.60
    policy_update_risk_threshold: float = 0.38
    urgent_deadline_days_threshold: int = 45
    stale_evidence_days_threshold: int = 90
    allow_auto_remediation_program: bool = True
    allow_auto_control_gap_tasks: bool = True
    allow_auto_policy_update: bool = True
    allow_auto_attestation: bool = True
    allow_auto_training_assignment: bool = True

    def __post_init__(self) -> None:
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be >= 1")
        if self.max_requirements_to_process < 1:
            raise ValueError("max_requirements_to_process must be >= 1")
        if self.urgent_deadline_days_threshold < 1:
            raise ValueError("urgent_deadline_days_threshold must be >= 1")
        if self.stale_evidence_days_threshold < 1:
            raise ValueError("stale_evidence_days_threshold must be >= 1")
        for name, value in (
            ("immediate_remediation_risk_threshold", self.immediate_remediation_risk_threshold),
            (
                "accelerated_gap_closure_risk_threshold",
                self.accelerated_gap_closure_risk_threshold,
            ),
            ("policy_update_risk_threshold", self.policy_update_risk_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(slots=True, frozen=True)
class RegulatoryExecutionStats:
    requirements_total: int
    enrichment_total: int
    enrichment_success: int
    actions_total: int
    actions_success: int
    actions_skipped: int
    actions_failed: int
    immediate_remediation_count: int
    accelerated_gap_closure_count: int
    policy_update_count: int
    monitor_count: int


@dataclass(slots=True, frozen=True)
class RegulatoryExecutionReport:
    batch_id: str
    pipeline_report: UseCaseExecutionReport
    mode: str
    started_at: datetime
    completed_at: datetime
    signals: tuple[RegulatorySignal, ...]
    enrichments: tuple[RegulatoryActionResult, ...]
    decisions: tuple[RegulatoryDecision, ...]
    actions: tuple[RegulatoryActionResult, ...]
    stats: RegulatoryExecutionStats
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
class RegulatoryChangeCommander(BaseIntegrationCommanderMixin):
    pipeline: TriProviderPipeline
    regulation_intel_adapter: RegulationIntelAdapter
    control_coverage_adapter: ControlCoverageAdapter
    compliance_action_adapter: ComplianceActionAdapter
    execution_policy: RegulatoryExecutionPolicy = field(default_factory=RegulatoryExecutionPolicy)
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
    ) -> RegulatoryExecutionReport:
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
            max_signals=self.execution_policy.max_requirements_to_process,
        )

        enrichments = self._run_enrichment(signals)
        decisions = self._build_decisions(signals, enrichments)

        execute_actions = True
        if mode == "dry" and not self.execution_policy.execute_actions_in_dry_run:
            execute_actions = False
            warnings.append("Compliance actions skipped in dry mode by execution policy.")

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
        return RegulatoryExecutionReport(
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
    def extract_signals(text: str, *, max_signals: int = 20) -> list[RegulatorySignal]:
        requirement_matches = list(_REQUIREMENT_RE.finditer(text))
        domains = [_normalize(m.group(0)) for m in _DOMAIN_RE.finditer(text)]
        owners = [_normalize(m.group(0)) for m in _OWNER_RE.finditer(text)]
        deadlines = [int(m.group(1)) for m in _DEADLINE_DAYS_RE.finditer(text)]
        obligation_counts = [int(m.group(1)) for m in _OBLIGATION_COUNT_RE.finditer(text)]
        obligation_hints = [m.group(0).lower() for m in _OBLIGATION_RE.finditer(text)]
        has_enforcement = bool(_ENFORCEMENT_RE.search(text))

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

        if not requirement_matches:
            return [
                RegulatorySignal(
                    requirement_id=f"REG-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:8].upper()}",
                    domain_id=_pick(domains, 0, "DOMAIN-AUTO-01"),
                    owner_id=_pick(owners, 0, "TEAM-AUTO-01"),
                    obligation_hint=_pick(obligation_hints, 0, "") or None,
                    observed_deadline_days=_pick_int(deadlines, 0),
                    observed_obligation_count=_pick_int(obligation_counts, 0),
                    enforcement_indicator=has_enforcement,
                )
            ]

        rows: list[RegulatorySignal] = []
        seen_ids: set[str] = set()
        for idx, match in enumerate(requirement_matches):
            if len(rows) >= max_signals:
                break

            requirement_id = _normalize(match.group(0))
            key = requirement_id.lower()
            if key in seen_ids:
                continue
            seen_ids.add(key)

            segment_index = len(rows)
            start = match.start()
            end = (
                requirement_matches[idx + 1].start()
                if idx + 1 < len(requirement_matches)
                else len(text)
            )
            segment = text[start:end]

            domain_match = _DOMAIN_RE.search(segment)
            owner_match = _OWNER_RE.search(segment)
            deadline_match = _DEADLINE_DAYS_RE.search(segment)
            obligation_count_match = _OBLIGATION_COUNT_RE.search(segment)
            obligation_hint_match = _OBLIGATION_RE.search(segment)
            enforcement_match = _ENFORCEMENT_RE.search(segment)

            rows.append(
                RegulatorySignal(
                    requirement_id=requirement_id,
                    domain_id=_normalize(domain_match.group(0))
                    if domain_match
                    else _pick(domains, segment_index, "DOMAIN-AUTO-01"),
                    owner_id=_normalize(owner_match.group(0))
                    if owner_match
                    else _pick(owners, segment_index, "TEAM-AUTO-01"),
                    obligation_hint=obligation_hint_match.group(0).lower()
                    if obligation_hint_match
                    else (_pick(obligation_hints, segment_index, "") or None),
                    observed_deadline_days=int(deadline_match.group(1))
                    if deadline_match
                    else _pick_int(deadlines, segment_index),
                    observed_obligation_count=int(obligation_count_match.group(1))
                    if obligation_count_match
                    else _pick_int(obligation_counts, segment_index),
                    enforcement_indicator=bool(enforcement_match) or has_enforcement,
                )
            )

        return rows

    @staticmethod
    def _build_batch_id(scenario: str, started_at: datetime) -> str:
        digest = hashlib.sha256(
            f"{started_at.isoformat()}::{scenario}".encode("utf-8")
        ).hexdigest()[:16]
        return f"reg-{started_at.strftime('%Y%m%d%H%M%S')}-{digest}"

    def _run_enrichment(self, signals: list[RegulatorySignal]) -> list[RegulatoryActionResult]:
        tasks: list[_ExecutionTask] = []

        requirement_ids = _unique_preserve([signal.requirement_id for signal in signals])
        for requirement_id in requirement_ids:
            tasks.append(
                _ExecutionTask(
                    integration="regulation_intel",
                    operation="lookup_requirement",
                    target=requirement_id,
                    request_payload={"requirement_id": requirement_id},
                    idempotency_key=None,
                    call=lambda requirement_id=requirement_id: (
                        self.regulation_intel_adapter.lookup_requirement(requirement_id)
                    ),
                )
            )

        domain_ids = _unique_preserve([signal.domain_id for signal in signals])
        for domain_id in domain_ids:
            tasks.append(
                _ExecutionTask(
                    integration="control_coverage",
                    operation="lookup_domain",
                    target=domain_id,
                    request_payload={"domain_id": domain_id},
                    idempotency_key=None,
                    call=lambda domain_id=domain_id: self.control_coverage_adapter.lookup_domain(
                        domain_id
                    ),
                )
            )

        return self._execute_integration_tasks(tasks)

    def _build_decisions(
        self,
        signals: list[RegulatorySignal],
        enrichments: list[RegulatoryActionResult],
    ) -> list[RegulatoryDecision]:
        intel_data: dict[str, dict[str, Any]] = {}
        coverage_data: dict[str, dict[str, Any]] = {}

        for row in enrichments:
            if not row.success or row.status != "executed":
                continue
            if row.integration == "regulation_intel":
                intel_data[row.target] = row.response or {}
            elif row.integration == "control_coverage":
                coverage_data[row.target] = row.response or {}

        decisions: list[RegulatoryDecision] = []
        for signal in signals:
            intel = intel_data.get(signal.requirement_id, {})
            coverage = coverage_data.get(signal.domain_id, {})

            obligation_severity = self._as_float(
                intel,
                keys=("obligation_severity", "severity", "risk_score"),
                default=0.35,
            )
            deadline_days = int(
                self._as_float(
                    intel,
                    keys=("deadline_days", "days_to_deadline"),
                    default=float(signal.observed_deadline_days or 150),
                    cap_1=False,
                )
            )
            penalty_risk = self._as_float(
                intel,
                keys=("penalty_risk", "enforcement_risk"),
                default=0.30,
            )
            obligations_count = int(
                self._as_float(
                    intel,
                    keys=("obligations_count", "requirement_count"),
                    default=float(signal.observed_obligation_count or 4),
                    cap_1=False,
                )
            )

            coverage_pct = self._as_float(
                coverage,
                keys=("coverage_pct", "control_coverage", "coverage"),
                default=0.70,
            )
            open_findings = int(
                self._as_float(
                    coverage,
                    keys=("open_findings", "findings"),
                    default=2.0,
                    cap_1=False,
                )
            )
            evidence_freshness_days = int(
                self._as_float(
                    coverage,
                    keys=("evidence_freshness_days", "evidence_age_days"),
                    default=30.0,
                    cap_1=False,
                )
            )

            deadline_urgency = 1.0 - min(1.0, max(0, deadline_days) / 180.0)
            coverage_gap = 1.0 - coverage_pct

            risk_score = min(
                1.0,
                obligation_severity * 0.30
                + penalty_risk * 0.22
                + coverage_gap * 0.24
                + min(1.0, open_findings / 12.0) * 0.08
                + min(1.0, obligations_count / 20.0) * 0.06
                + deadline_urgency * 0.08
                + (0.08 if signal.enforcement_indicator else 0.0)
                + (
                    0.05
                    if evidence_freshness_days
                    >= self.execution_policy.stale_evidence_days_threshold
                    else 0.0
                ),
            )

            route: RegulatoryRoute = "monitor"
            rationale: list[str] = []

            if (
                risk_score >= self.execution_policy.immediate_remediation_risk_threshold
                or (
                    deadline_days <= self.execution_policy.urgent_deadline_days_threshold
                    and coverage_pct < 0.60
                )
                or (signal.enforcement_indicator and coverage_pct < 0.50)
            ):
                route = "immediate_remediation_program"
                rationale.append(
                    "High compliance risk/deadline pressure requires immediate remediation program."
                )
            elif (
                risk_score >= self.execution_policy.accelerated_gap_closure_risk_threshold
                or coverage_pct < 0.70
                or evidence_freshness_days >= self.execution_policy.stale_evidence_days_threshold
            ):
                route = "accelerated_control_gap_closure"
                rationale.append(
                    "Control coverage gaps require accelerated closure and evidence refresh."
                )
            elif risk_score >= self.execution_policy.policy_update_risk_threshold:
                route = "policy_update_and_training"
                rationale.append(
                    "Moderate compliance impact requires policy update and training rollout."
                )
            else:
                rationale.append(
                    "Current regulatory delta can be tracked through standard monitoring."
                )

            if not intel:
                rationale.append("Regulation-intel enrichment missing; confidence reduced.")
            if not coverage:
                rationale.append("Control-coverage enrichment missing; confidence reduced.")

            priority = self._priority_for(route)
            confidence = self._confidence_for(
                route=route,
                intel_enriched=bool(intel),
                coverage_enriched=bool(coverage),
            )

            decisions.append(
                RegulatoryDecision(
                    requirement_id=signal.requirement_id,
                    domain_id=signal.domain_id,
                    owner_id=signal.owner_id,
                    route=route,
                    priority=priority,
                    confidence=confidence,
                    risk_score=risk_score,
                    obligation_severity=obligation_severity,
                    deadline_days=max(0, deadline_days),
                    penalty_risk=penalty_risk,
                    obligations_count=max(0, obligations_count),
                    coverage_pct=coverage_pct,
                    open_findings=max(0, open_findings),
                    evidence_freshness_days=max(0, evidence_freshness_days),
                    rationale=tuple(rationale),
                )
            )

        decisions.sort(
            key=lambda row: (
                row.route in {"immediate_remediation_program", "accelerated_control_gap_closure"},
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
        decisions: list[RegulatoryDecision],
        execute_actions: bool,
    ) -> list[RegulatoryActionResult]:
        tasks: list[_ExecutionTask] = []
        skipped: list[RegulatoryActionResult] = []

        for row in decisions:
            reason = "; ".join(row.rationale)
            if not execute_actions:
                skipped.append(
                    RegulatoryActionResult(
                        integration="compliance_actions",
                        operation=row.route,
                        target=row.requirement_id,
                        success=True,
                        latency_ms=0,
                        request={"requirement_id": row.requirement_id, "route": row.route},
                        status="skipped",
                        attempts=0,
                        notes=("action execution disabled by runtime policy",),
                    )
                )
                continue

            if row.route == "monitor":
                skipped.append(
                    RegulatoryActionResult(
                        integration="compliance_actions",
                        operation="monitor",
                        target=row.requirement_id,
                        success=True,
                        latency_ms=0,
                        request={"requirement_id": row.requirement_id, "route": "monitor"},
                        status="skipped",
                        attempts=0,
                        notes=("monitor route requires no external action call",),
                    )
                )
                continue

            if row.route == "immediate_remediation_program":
                if self.execution_policy.allow_auto_remediation_program:
                    remediation_key = f"{batch_id}:remediation:{row.requirement_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="compliance_actions",
                            operation="open_remediation_program",
                            target=row.requirement_id,
                            request_payload={
                                "requirement_id": row.requirement_id,
                                "reason": reason,
                            },
                            idempotency_key=remediation_key,
                            call=lambda row=row, reason=reason: (
                                self.compliance_action_adapter.open_remediation_program(
                                    row.requirement_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        RegulatoryActionResult(
                            integration="compliance_actions",
                            operation="open_remediation_program",
                            target=row.requirement_id,
                            success=True,
                            latency_ms=0,
                            request={"requirement_id": row.requirement_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto remediation program disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_control_gap_tasks:
                    control_gap_key = f"{batch_id}:gap:{row.domain_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="compliance_actions",
                            operation="create_control_gap_tasks",
                            target=row.domain_id,
                            request_payload={"domain_id": row.domain_id, "reason": reason},
                            idempotency_key=control_gap_key,
                            call=lambda row=row, reason=reason: (
                                self.compliance_action_adapter.create_control_gap_tasks(
                                    row.domain_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        RegulatoryActionResult(
                            integration="compliance_actions",
                            operation="create_control_gap_tasks",
                            target=row.domain_id,
                            success=True,
                            latency_ms=0,
                            request={"domain_id": row.domain_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto control-gap tasks disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_policy_update:
                    policy_key = f"{batch_id}:policy:{row.domain_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="compliance_actions",
                            operation="publish_policy_update",
                            target=row.domain_id,
                            request_payload={"domain_id": row.domain_id, "reason": reason},
                            idempotency_key=policy_key,
                            call=lambda row=row, reason=reason: (
                                self.compliance_action_adapter.publish_policy_update(
                                    row.domain_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        RegulatoryActionResult(
                            integration="compliance_actions",
                            operation="publish_policy_update",
                            target=row.domain_id,
                            success=True,
                            latency_ms=0,
                            request={"domain_id": row.domain_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto policy update disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_attestation:
                    attestation_key = f"{batch_id}:attestation:{row.requirement_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="compliance_actions",
                            operation="schedule_attestation",
                            target=row.requirement_id,
                            request_payload={
                                "requirement_id": row.requirement_id,
                                "reason": reason,
                            },
                            idempotency_key=attestation_key,
                            call=lambda row=row, reason=reason: (
                                self.compliance_action_adapter.schedule_attestation(
                                    row.requirement_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        RegulatoryActionResult(
                            integration="compliance_actions",
                            operation="schedule_attestation",
                            target=row.requirement_id,
                            success=True,
                            latency_ms=0,
                            request={"requirement_id": row.requirement_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto attestation scheduling disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_training_assignment:
                    training_key = f"{batch_id}:training:{row.owner_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="compliance_actions",
                            operation="assign_training",
                            target=row.owner_id,
                            request_payload={"owner_id": row.owner_id, "reason": reason},
                            idempotency_key=training_key,
                            call=lambda row=row, reason=reason: (
                                self.compliance_action_adapter.assign_training(
                                    row.owner_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        RegulatoryActionResult(
                            integration="compliance_actions",
                            operation="assign_training",
                            target=row.owner_id,
                            success=True,
                            latency_ms=0,
                            request={"owner_id": row.owner_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto training assignment disabled by policy",),
                        )
                    )
                continue

            if row.route == "accelerated_control_gap_closure":
                if self.execution_policy.allow_auto_control_gap_tasks:
                    control_gap_key = f"{batch_id}:gap:{row.domain_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="compliance_actions",
                            operation="create_control_gap_tasks",
                            target=row.domain_id,
                            request_payload={"domain_id": row.domain_id, "reason": reason},
                            idempotency_key=control_gap_key,
                            call=lambda row=row, reason=reason: (
                                self.compliance_action_adapter.create_control_gap_tasks(
                                    row.domain_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        RegulatoryActionResult(
                            integration="compliance_actions",
                            operation="create_control_gap_tasks",
                            target=row.domain_id,
                            success=True,
                            latency_ms=0,
                            request={"domain_id": row.domain_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto control-gap tasks disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_policy_update:
                    policy_key = f"{batch_id}:policy:{row.domain_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="compliance_actions",
                            operation="publish_policy_update",
                            target=row.domain_id,
                            request_payload={"domain_id": row.domain_id, "reason": reason},
                            idempotency_key=policy_key,
                            call=lambda row=row, reason=reason: (
                                self.compliance_action_adapter.publish_policy_update(
                                    row.domain_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        RegulatoryActionResult(
                            integration="compliance_actions",
                            operation="publish_policy_update",
                            target=row.domain_id,
                            success=True,
                            latency_ms=0,
                            request={"domain_id": row.domain_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto policy update disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_training_assignment:
                    training_key = f"{batch_id}:training:{row.owner_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="compliance_actions",
                            operation="assign_training",
                            target=row.owner_id,
                            request_payload={"owner_id": row.owner_id, "reason": reason},
                            idempotency_key=training_key,
                            call=lambda row=row, reason=reason: (
                                self.compliance_action_adapter.assign_training(
                                    row.owner_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        RegulatoryActionResult(
                            integration="compliance_actions",
                            operation="assign_training",
                            target=row.owner_id,
                            success=True,
                            latency_ms=0,
                            request={"owner_id": row.owner_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto training assignment disabled by policy",),
                        )
                    )
                continue

            if row.route == "policy_update_and_training":
                if self.execution_policy.allow_auto_policy_update:
                    policy_key = f"{batch_id}:policy:{row.domain_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="compliance_actions",
                            operation="publish_policy_update",
                            target=row.domain_id,
                            request_payload={"domain_id": row.domain_id, "reason": reason},
                            idempotency_key=policy_key,
                            call=lambda row=row, reason=reason: (
                                self.compliance_action_adapter.publish_policy_update(
                                    row.domain_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        RegulatoryActionResult(
                            integration="compliance_actions",
                            operation="publish_policy_update",
                            target=row.domain_id,
                            success=True,
                            latency_ms=0,
                            request={"domain_id": row.domain_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto policy update disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_training_assignment:
                    training_key = f"{batch_id}:training:{row.owner_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="compliance_actions",
                            operation="assign_training",
                            target=row.owner_id,
                            request_payload={"owner_id": row.owner_id, "reason": reason},
                            idempotency_key=training_key,
                            call=lambda row=row, reason=reason: (
                                self.compliance_action_adapter.assign_training(
                                    row.owner_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        RegulatoryActionResult(
                            integration="compliance_actions",
                            operation="assign_training",
                            target=row.owner_id,
                            success=True,
                            latency_ms=0,
                            request={"owner_id": row.owner_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto training assignment disabled by policy",),
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
    def _priority_for(route: RegulatoryRoute) -> str:
        if route == "immediate_remediation_program":
            return "urgent"
        if route == "accelerated_control_gap_closure":
            return "high"
        if route == "policy_update_and_training":
            return "normal"
        return "low"

    @staticmethod
    def _confidence_for(
        *,
        route: RegulatoryRoute,
        intel_enriched: bool,
        coverage_enriched: bool,
    ) -> float:
        base = {
            "immediate_remediation_program": 0.90,
            "accelerated_control_gap_closure": 0.84,
            "policy_update_and_training": 0.76,
            "monitor": 0.68,
        }[route]
        if not intel_enriched:
            base -= 0.15
        if not coverage_enriched:
            base -= 0.15
        return round(min(0.99, max(0.05, base)), 3)

    @staticmethod
    def _build_stats(
        *,
        signals: list[RegulatorySignal],
        enrichments: list[RegulatoryActionResult],
        decisions: list[RegulatoryDecision],
        actions: list[RegulatoryActionResult],
    ) -> RegulatoryExecutionStats:
        route_counts: dict[RegulatoryRoute, int] = defaultdict(int)
        for row in decisions:
            route_counts[row.route] += 1

        actions_success = sum(1 for row in actions if row.success and row.status == "executed")
        actions_skipped = sum(1 for row in actions if row.status == "skipped")
        actions_failed = sum(1 for row in actions if not row.success)

        return RegulatoryExecutionStats(
            requirements_total=len(signals),
            enrichment_total=len(enrichments),
            enrichment_success=sum(1 for row in enrichments if row.success),
            actions_total=len(actions),
            actions_success=actions_success,
            actions_skipped=actions_skipped,
            actions_failed=actions_failed,
            immediate_remediation_count=route_counts["immediate_remediation_program"],
            accelerated_gap_closure_count=route_counts["accelerated_control_gap_closure"],
            policy_update_count=route_counts["policy_update_and_training"],
            monitor_count=route_counts["monitor"],
        )

    @staticmethod
    def _recommendations(
        *,
        pipeline_report: UseCaseExecutionReport,
        stats: RegulatoryExecutionStats,
        decisions: list[RegulatoryDecision],
        errors: list[str],
    ) -> list[str]:
        recs: list[str] = [
            (
                "Decision mix: "
                f"immediate_remediation={stats.immediate_remediation_count}, "
                f"accelerated_gap_closure={stats.accelerated_gap_closure_count}, "
                f"policy_update={stats.policy_update_count}, monitor={stats.monitor_count}."
            ),
            (
                f"Enrichment success {stats.enrichment_success}/{stats.enrichment_total}; "
                f"actions success={stats.actions_success}, skipped={stats.actions_skipped}, failed={stats.actions_failed}."
            ),
            "For immediate-remediation cases, assign accountable owners and lock milestone checkpoints.",
            "For accelerated gap-closure cases, refresh evidence sets and prioritize high-risk control domains.",
            "For policy-update cases, synchronize policy publication with training completion tracking.",
        ]

        if pipeline_report.ranked_actions:
            recs.append(f"Primary tri-provider action: {pipeline_report.ranked_actions[0].action}")

        if errors:
            recs.append(
                "At least one integration failed; escalate impacted requirements to manual compliance review."
            )

        top = decisions[:3]
        if top:
            recs.append(
                "Top requirements: "
                + ", ".join(
                    f"{row.requirement_id}:{row.route}:{row.risk_score:.2f}:{row.coverage_pct:.2f}"
                    for row in top
                )
                + "."
            )

        return recs
