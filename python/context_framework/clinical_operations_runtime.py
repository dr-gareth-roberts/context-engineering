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
)
from .runtime_base import (
    unique_preserve as _unique_preserve,
)
from .tri_provider_pipeline import TriProviderPipeline, UseCaseExecutionReport

# Backward-compatible alias.
ClinicalActionResult = IntegrationActionResult

_ID_SUFFIX_RE = r"(?:[-_][A-Za-z0-9]+|[0-9]{2,}[A-Za-z0-9]*)(?:[-_][A-Za-z0-9]+)*"
_UNIT_RE = re.compile(
    rf"\b(?:UNIT|WARD|ICU|ED|FLOOR){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_TEAM_RE = re.compile(
    rf"\b(?:TEAM|SERVICE|SQUAD){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_SERVICE_LINE_RE = re.compile(
    rf"\b(?:LINE|SPECIALTY|SERVICE-LINE){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_OCCUPANCY_RE = re.compile(r"\b(\d{1,3})\s*%\s*occupancy\b", re.IGNORECASE)
_BOARDING_HOURS_RE = re.compile(r"\b(\d{1,3})\s*hours?\b", re.IGNORECASE)
_WAITING_PATIENTS_RE = re.compile(
    r"\b(\d{1,4})\s*(?:patients?|admissions?)\b",
    re.IGNORECASE,
)

_ACUITY_HINT_KEYWORDS = (
    "sepsis",
    "stroke",
    "trauma surge",
    "respiratory failure",
    "icu overflow",
    "diversion",
)
_ACUITY_HINT_RE = re.compile(
    "|".join(re.escape(keyword) for keyword in _ACUITY_HINT_KEYWORDS), re.IGNORECASE
)
_HIGH_ACUITY_RE = re.compile(
    r"(?:high acuity|critical patients|code blue|rapid response)",
    re.IGNORECASE,
)
_DIVERSION_RE = re.compile(
    r"(?:diversion|boarding crisis|capacity crisis)",
    re.IGNORECASE,
)


def _normalize(value: str) -> str:
    return value.strip().replace("_", "-").upper()


class BedCapacityAdapter(Protocol):
    def lookup_unit(self, unit_id: str) -> dict[str, Any]: ...


class AcuityIntelAdapter(Protocol):
    def lookup_unit(self, unit_id: str) -> dict[str, Any]: ...


class ClinicalActionAdapter(Protocol):
    def activate_surge_staffing(self, unit_id: str, *, reason: str) -> dict[str, Any]: ...

    def prioritize_discharge_huddle(self, unit_id: str, *, reason: str) -> dict[str, Any]: ...

    def open_transfer_coordination(self, unit_id: str, *, reason: str) -> dict[str, Any]: ...

    def escalate_hospital_command(self, unit_id: str, *, reason: str) -> dict[str, Any]: ...

    def rebalance_clinician_coverage(self, team_id: str, *, reason: str) -> dict[str, Any]: ...


class NoOpBedCapacityAdapter:
    def lookup_unit(self, unit_id: str) -> dict[str, Any]:
        return {
            "unit_id": unit_id,
            "occupancy_pct": 82,
            "staffed_bed_ratio": 0.78,
            "discharge_backlog": 24,
            "diversion_risk": 0.42,
            "source": "noop",
        }


class NoOpAcuityIntelAdapter:
    def lookup_unit(self, unit_id: str) -> dict[str, Any]:
        return {
            "unit_id": unit_id,
            "high_acuity_ratio": 0.40,
            "deteriorating_patients": 6,
            "transfer_blockers": 0.44,
            "surge_probability": 0.46,
            "source": "noop",
        }


class NoOpClinicalActionAdapter:
    def activate_surge_staffing(self, unit_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "unit_id": unit_id,
            "action": "activate_surge_staffing",
            "reason": reason,
            "status": "noop",
        }

    def prioritize_discharge_huddle(self, unit_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "unit_id": unit_id,
            "action": "prioritize_discharge_huddle",
            "reason": reason,
            "status": "noop",
        }

    def open_transfer_coordination(self, unit_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "unit_id": unit_id,
            "action": "open_transfer_coordination",
            "reason": reason,
            "status": "noop",
        }

    def escalate_hospital_command(self, unit_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "unit_id": unit_id,
            "action": "escalate_hospital_command",
            "reason": reason,
            "status": "noop",
        }

    def rebalance_clinician_coverage(self, team_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "team_id": team_id,
            "action": "rebalance_clinician_coverage",
            "reason": reason,
            "status": "noop",
        }


@dataclass(slots=True)
class InMemoryBedCapacityAdapter:
    units: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_unit(self, unit_id: str) -> dict[str, Any]:
        unit = _normalize(unit_id)
        payload = self.units.get(unit, {})
        occupancy_pct = int(payload.get("occupancy_pct", 84))
        staffed_ratio = float(payload.get("staffed_bed_ratio", 0.76))
        discharge_backlog = int(payload.get("discharge_backlog", 26))
        diversion_risk = float(payload.get("diversion_risk", 0.44))
        return {
            "unit_id": unit,
            "occupancy_pct": max(0, min(100, occupancy_pct)),
            "staffed_bed_ratio": max(0.0, min(1.0, staffed_ratio)),
            "discharge_backlog": max(0, discharge_backlog),
            "diversion_risk": max(0.0, min(1.0, diversion_risk)),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryAcuityIntelAdapter:
    units: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_unit(self, unit_id: str) -> dict[str, Any]:
        unit = _normalize(unit_id)
        payload = self.units.get(unit, {})
        high_acuity_ratio = float(payload.get("high_acuity_ratio", 0.42))
        deteriorating = int(payload.get("deteriorating_patients", 7))
        transfer_blockers = float(payload.get("transfer_blockers", 0.46))
        surge_probability = float(payload.get("surge_probability", 0.48))
        return {
            "unit_id": unit,
            "high_acuity_ratio": max(0.0, min(1.0, high_acuity_ratio)),
            "deteriorating_patients": max(0, deteriorating),
            "transfer_blockers": max(0.0, min(1.0, transfer_blockers)),
            "surge_probability": max(0.0, min(1.0, surge_probability)),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryClinicalActionAdapter:
    surge_staffing_units: set[str] = field(default_factory=set)
    discharge_huddle_units: set[str] = field(default_factory=set)
    transfer_coordination_units: set[str] = field(default_factory=set)
    hospital_command_units: set[str] = field(default_factory=set)
    coverage_rebalance_teams: set[str] = field(default_factory=set)

    def activate_surge_staffing(self, unit_id: str, *, reason: str) -> dict[str, Any]:
        unit = _normalize(unit_id)
        self.surge_staffing_units.add(unit)
        return {
            "unit_id": unit,
            "action": "activate_surge_staffing",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def prioritize_discharge_huddle(self, unit_id: str, *, reason: str) -> dict[str, Any]:
        unit = _normalize(unit_id)
        self.discharge_huddle_units.add(unit)
        return {
            "unit_id": unit,
            "action": "prioritize_discharge_huddle",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def open_transfer_coordination(self, unit_id: str, *, reason: str) -> dict[str, Any]:
        unit = _normalize(unit_id)
        self.transfer_coordination_units.add(unit)
        return {
            "unit_id": unit,
            "action": "open_transfer_coordination",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def escalate_hospital_command(self, unit_id: str, *, reason: str) -> dict[str, Any]:
        unit = _normalize(unit_id)
        self.hospital_command_units.add(unit)
        return {
            "unit_id": unit,
            "action": "escalate_hospital_command",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def rebalance_clinician_coverage(self, team_id: str, *, reason: str) -> dict[str, Any]:
        team = _normalize(team_id)
        self.coverage_rebalance_teams.add(team)
        return {
            "team_id": team,
            "action": "rebalance_clinician_coverage",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }


_HTTPJSONAdapterBase = HTTPJSONAdapterBase


@dataclass(slots=True)
class HTTPBedCapacityAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/clinical/bed_capacity"

    def lookup_unit(self, unit_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"unit_id": unit_id})


@dataclass(slots=True)
class HTTPAcuityIntelAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/clinical/acuity_intel"

    def lookup_unit(self, unit_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"unit_id": unit_id})


@dataclass(slots=True)
class HTTPClinicalActionAdapter(HTTPJSONAdapterBase):
    surge_staffing_path: str = "/clinical/activate_surge_staffing"
    discharge_huddle_path: str = "/clinical/prioritize_discharge_huddle"
    transfer_coordination_path: str = "/clinical/open_transfer_coordination"
    hospital_command_path: str = "/clinical/escalate_hospital_command"
    coverage_rebalance_path: str = "/clinical/rebalance_clinician_coverage"

    def activate_surge_staffing(self, unit_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.surge_staffing_path, {"unit_id": unit_id, "reason": reason})

    def prioritize_discharge_huddle(self, unit_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.discharge_huddle_path, {"unit_id": unit_id, "reason": reason})

    def open_transfer_coordination(self, unit_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.transfer_coordination_path, {"unit_id": unit_id, "reason": reason})

    def escalate_hospital_command(self, unit_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.hospital_command_path, {"unit_id": unit_id, "reason": reason})

    def rebalance_clinician_coverage(self, team_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.coverage_rebalance_path, {"team_id": team_id, "reason": reason})


def build_bed_capacity_adapter_from_env() -> BedCapacityAdapter:
    base = os.getenv("CLINICAL_BED_BASE_URL")
    token = os.getenv("CLINICAL_BED_API_KEY")
    if base and token:
        path = os.getenv("CLINICAL_BED_LOOKUP_PATH", "/clinical/bed_capacity")
        return HTTPBedCapacityAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpBedCapacityAdapter()


def build_acuity_intel_adapter_from_env() -> AcuityIntelAdapter:
    base = os.getenv("CLINICAL_ACUITY_BASE_URL")
    token = os.getenv("CLINICAL_ACUITY_API_KEY")
    if base and token:
        path = os.getenv("CLINICAL_ACUITY_LOOKUP_PATH", "/clinical/acuity_intel")
        return HTTPAcuityIntelAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpAcuityIntelAdapter()


def build_clinical_action_adapter_from_env() -> ClinicalActionAdapter:
    base = os.getenv("CLINICAL_ACTION_BASE_URL")
    token = os.getenv("CLINICAL_ACTION_API_KEY")
    if base and token:
        return HTTPClinicalActionAdapter(
            base_url=base,
            api_key=token,
            surge_staffing_path=os.getenv(
                "CLINICAL_ACTION_SURGE_STAFFING_PATH",
                "/clinical/activate_surge_staffing",
            ),
            discharge_huddle_path=os.getenv(
                "CLINICAL_ACTION_DISCHARGE_HUDDLE_PATH",
                "/clinical/prioritize_discharge_huddle",
            ),
            transfer_coordination_path=os.getenv(
                "CLINICAL_ACTION_TRANSFER_COORDINATION_PATH",
                "/clinical/open_transfer_coordination",
            ),
            hospital_command_path=os.getenv(
                "CLINICAL_ACTION_HOSPITAL_COMMAND_PATH",
                "/clinical/escalate_hospital_command",
            ),
            coverage_rebalance_path=os.getenv(
                "CLINICAL_ACTION_COVERAGE_REBALANCE_PATH",
                "/clinical/rebalance_clinician_coverage",
            ),
        )
    return NoOpClinicalActionAdapter()


ClinicalRoute = Literal[
    "critical_capacity_command",
    "surge_flow_stabilization",
    "flow_optimization",
    "monitor",
]


@dataclass(slots=True, frozen=True)
class ClinicalSignal:
    unit_id: str
    team_id: str
    service_line_id: str
    acuity_hint: str | None
    observed_occupancy_pct: int | None
    observed_boarding_hours: int | None
    observed_waiting_patients: int | None
    high_acuity_indicator: bool
    diversion_risk_indicator: bool


@dataclass(slots=True, frozen=True)
class ClinicalDecision:
    unit_id: str
    team_id: str
    service_line_id: str
    route: ClinicalRoute
    priority: str
    confidence: float
    risk_score: float
    occupancy_pct: int
    staffed_bed_ratio: float
    discharge_backlog: int
    diversion_risk: float
    high_acuity_ratio: float
    deteriorating_patients: int
    transfer_blockers: float
    surge_probability: float
    boarding_hours: int
    waiting_patients: int
    rationale: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ClinicalExecutionPolicy:
    execute_actions_in_dry_run: bool = False
    max_parallel_tasks: int = 6
    max_units_to_process: int = 20
    critical_risk_threshold: float = 0.84
    surge_risk_threshold: float = 0.60
    flow_risk_threshold: float = 0.36
    high_occupancy_threshold: int = 92
    high_boarding_hours_threshold: int = 8
    allow_auto_surge_staffing: bool = True
    allow_auto_discharge_huddle: bool = True
    allow_auto_transfer_coordination: bool = True
    allow_auto_hospital_command: bool = True
    allow_auto_coverage_rebalance: bool = True

    def __post_init__(self) -> None:
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be >= 1")
        if self.max_units_to_process < 1:
            raise ValueError("max_units_to_process must be >= 1")
        if self.high_occupancy_threshold < 1:
            raise ValueError("high_occupancy_threshold must be >= 1")
        if self.high_boarding_hours_threshold < 1:
            raise ValueError("high_boarding_hours_threshold must be >= 1")
        for name, value in (
            ("critical_risk_threshold", self.critical_risk_threshold),
            ("surge_risk_threshold", self.surge_risk_threshold),
            ("flow_risk_threshold", self.flow_risk_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(slots=True, frozen=True)
class ClinicalExecutionStats:
    units_total: int
    enrichment_total: int
    enrichment_success: int
    actions_total: int
    actions_success: int
    actions_skipped: int
    actions_failed: int
    critical_count: int
    surge_count: int
    flow_count: int
    monitor_count: int


@dataclass(slots=True, frozen=True)
class ClinicalExecutionReport:
    batch_id: str
    pipeline_report: UseCaseExecutionReport
    mode: str
    started_at: datetime
    completed_at: datetime
    signals: tuple[ClinicalSignal, ...]
    enrichments: tuple[ClinicalActionResult, ...]
    decisions: tuple[ClinicalDecision, ...]
    actions: tuple[ClinicalActionResult, ...]
    stats: ClinicalExecutionStats
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
class ClinicalOperationsCommander(BaseIntegrationCommanderMixin):
    pipeline: TriProviderPipeline
    bed_capacity_adapter: BedCapacityAdapter
    acuity_intel_adapter: AcuityIntelAdapter
    action_adapter: ClinicalActionAdapter
    execution_policy: ClinicalExecutionPolicy = field(default_factory=ClinicalExecutionPolicy)
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
    ) -> ClinicalExecutionReport:
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
            max_signals=self.execution_policy.max_units_to_process,
        )

        enrichments = self._run_enrichment(signals)
        decisions = self._build_decisions(signals, enrichments)

        execute_actions = True
        if mode == "dry" and not self.execution_policy.execute_actions_in_dry_run:
            execute_actions = False
            warnings.append("Clinical actions skipped in dry mode by execution policy.")

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
        return ClinicalExecutionReport(
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
    def extract_signals(text: str, *, max_signals: int = 20) -> list[ClinicalSignal]:
        unit_matches = list(_UNIT_RE.finditer(text))
        teams = [_normalize(m.group(0)) for m in _TEAM_RE.finditer(text)]
        service_lines = [_normalize(m.group(0)) for m in _SERVICE_LINE_RE.finditer(text)]
        occupancy_values = [int(m.group(1)) for m in _OCCUPANCY_RE.finditer(text)]
        boarding_values = [int(m.group(1)) for m in _BOARDING_HOURS_RE.finditer(text)]
        waiting_values = [int(m.group(1)) for m in _WAITING_PATIENTS_RE.finditer(text)]
        acuity_hints = [m.group(0).lower() for m in _ACUITY_HINT_RE.finditer(text)]
        has_high_acuity = bool(_HIGH_ACUITY_RE.search(text))
        has_diversion = bool(_DIVERSION_RE.search(text))

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

        if not unit_matches:
            unit_id = f"UNIT-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:8].upper()}"
            return [
                ClinicalSignal(
                    unit_id=unit_id,
                    team_id=_pick(teams, 0, "TEAM-AUTO-01"),
                    service_line_id=_pick(service_lines, 0, "LINE-AUTO-01"),
                    acuity_hint=_pick(acuity_hints, 0, "") or None,
                    observed_occupancy_pct=_pick_int(occupancy_values, 0),
                    observed_boarding_hours=_pick_int(boarding_values, 0),
                    observed_waiting_patients=_pick_int(waiting_values, 0),
                    high_acuity_indicator=has_high_acuity,
                    diversion_risk_indicator=has_diversion,
                )
            ]

        rows: list[ClinicalSignal] = []
        seen_units: set[str] = set()
        for idx, match in enumerate(unit_matches):
            if len(rows) >= max_signals:
                break

            unit_id = _normalize(match.group(0))
            key = unit_id.lower()
            if key in seen_units:
                continue
            seen_units.add(key)

            segment_index = len(rows)
            start = match.start()
            end = unit_matches[idx + 1].start() if idx + 1 < len(unit_matches) else len(text)
            segment = text[start:end]

            team_match = _TEAM_RE.search(segment)
            service_line_match = _SERVICE_LINE_RE.search(segment)
            occupancy_match = _OCCUPANCY_RE.search(segment)
            boarding_match = _BOARDING_HOURS_RE.search(segment)
            waiting_match = _WAITING_PATIENTS_RE.search(segment)
            acuity_hint_matches = [m.group(0).lower() for m in _ACUITY_HINT_RE.finditer(segment)]
            high_acuity_match = _HIGH_ACUITY_RE.search(segment)
            diversion_match = _DIVERSION_RE.search(segment)

            rows.append(
                ClinicalSignal(
                    unit_id=unit_id,
                    team_id=_normalize(team_match.group(0))
                    if team_match
                    else _pick(teams, segment_index, "TEAM-AUTO-01"),
                    service_line_id=_normalize(service_line_match.group(0))
                    if service_line_match
                    else _pick(service_lines, segment_index, "LINE-AUTO-01"),
                    acuity_hint=acuity_hint_matches[-1]
                    if acuity_hint_matches
                    else (_pick(acuity_hints, segment_index, "") or None),
                    observed_occupancy_pct=int(occupancy_match.group(1))
                    if occupancy_match
                    else _pick_int(occupancy_values, segment_index),
                    observed_boarding_hours=int(boarding_match.group(1))
                    if boarding_match
                    else _pick_int(boarding_values, segment_index),
                    observed_waiting_patients=int(waiting_match.group(1))
                    if waiting_match
                    else _pick_int(waiting_values, segment_index),
                    high_acuity_indicator=bool(high_acuity_match) or has_high_acuity,
                    diversion_risk_indicator=bool(diversion_match) or has_diversion,
                )
            )

        return rows

    @staticmethod
    def _build_batch_id(scenario: str, started_at: datetime) -> str:
        digest = hashlib.sha256(
            f"{started_at.isoformat()}::{scenario}".encode("utf-8")
        ).hexdigest()[:16]
        return f"clinical-{started_at.strftime('%Y%m%d%H%M%S')}-{digest}"

    def _run_enrichment(self, signals: list[ClinicalSignal]) -> list[ClinicalActionResult]:
        tasks: list[_ExecutionTask] = []

        unit_ids = _unique_preserve([signal.unit_id for signal in signals])
        for unit_id in unit_ids:
            tasks.append(
                _ExecutionTask(
                    integration="bed_capacity",
                    operation="lookup_unit",
                    target=unit_id,
                    request_payload={"unit_id": unit_id},
                    idempotency_key=None,
                    call=lambda unit_id=unit_id: self.bed_capacity_adapter.lookup_unit(unit_id),
                )
            )
            tasks.append(
                _ExecutionTask(
                    integration="acuity_intel",
                    operation="lookup_unit",
                    target=unit_id,
                    request_payload={"unit_id": unit_id},
                    idempotency_key=None,
                    call=lambda unit_id=unit_id: self.acuity_intel_adapter.lookup_unit(unit_id),
                )
            )
        return self._execute_integration_tasks(tasks)

    def _build_decisions(
        self,
        signals: list[ClinicalSignal],
        enrichments: list[ClinicalActionResult],
    ) -> list[ClinicalDecision]:
        capacity_data: dict[str, dict[str, Any]] = {}
        acuity_data: dict[str, dict[str, Any]] = {}

        for row in enrichments:
            if not row.success or row.status != "executed":
                continue
            if row.integration == "bed_capacity":
                capacity_data[row.target] = row.response or {}
            elif row.integration == "acuity_intel":
                acuity_data[row.target] = row.response or {}

        decisions: list[ClinicalDecision] = []
        for signal in signals:
            capacity = capacity_data.get(signal.unit_id, {})
            acuity = acuity_data.get(signal.unit_id, {})

            occupancy_pct = self._as_int(capacity, keys=("occupancy_pct",), default=84)
            staffed_bed_ratio = self._as_float(capacity, keys=("staffed_bed_ratio",), default=0.76)
            discharge_backlog = self._as_int(capacity, keys=("discharge_backlog",), default=26)
            diversion_risk = self._as_float(capacity, keys=("diversion_risk",), default=0.44)

            high_acuity_ratio = self._as_float(acuity, keys=("high_acuity_ratio",), default=0.42)
            deteriorating_patients = self._as_int(
                acuity, keys=("deteriorating_patients",), default=7
            )
            transfer_blockers = self._as_float(acuity, keys=("transfer_blockers",), default=0.46)
            surge_probability = self._as_float(acuity, keys=("surge_probability",), default=0.48)

            occupancy_pct = max(occupancy_pct, signal.observed_occupancy_pct or 0)
            boarding_hours = signal.observed_boarding_hours or 3
            waiting_patients = signal.observed_waiting_patients or 20

            occupancy_risk = min(1.0, occupancy_pct / 100.0)
            staffing_risk = 1.0 - staffed_bed_ratio
            backlog_risk = min(1.0, discharge_backlog / 80.0)
            boarding_risk = min(1.0, boarding_hours / 24.0)
            waiting_risk = min(1.0, waiting_patients / 120.0)
            deterioration_risk = min(1.0, deteriorating_patients / 30.0)
            hint_risk = 0.0
            if signal.acuity_hint in {
                "sepsis",
                "stroke",
                "trauma surge",
                "respiratory failure",
                "diversion",
            }:
                hint_risk = 0.05

            risk_score = min(
                1.0,
                occupancy_risk * 0.20
                + diversion_risk * 0.14
                + high_acuity_ratio * 0.18
                + staffing_risk * 0.08
                + backlog_risk * 0.08
                + transfer_blockers * 0.10
                + surge_probability * 0.07
                + boarding_risk * 0.07
                + waiting_risk * 0.05
                + deterioration_risk * 0.03
                + hint_risk
                + (0.08 if signal.high_acuity_indicator else 0.0)
                + (0.08 if signal.diversion_risk_indicator else 0.0),
            )

            route: ClinicalRoute = "monitor"
            rationale: list[str] = []
            if risk_score >= self.execution_policy.critical_risk_threshold or (
                occupancy_pct >= self.execution_policy.high_occupancy_threshold
                and (signal.high_acuity_indicator or signal.diversion_risk_indicator)
            ):
                route = "critical_capacity_command"
                rationale.append(
                    "Capacity and acuity profile requires hospital-level command activation."
                )
            elif (
                risk_score >= self.execution_policy.surge_risk_threshold
                or boarding_hours >= self.execution_policy.high_boarding_hours_threshold
            ):
                route = "surge_flow_stabilization"
                rationale.append("Unit risk requires surge staffing and active flow stabilization.")
            elif risk_score >= self.execution_policy.flow_risk_threshold:
                route = "flow_optimization"
                rationale.append("Unit risk supports focused throughput and coverage optimization.")
            else:
                rationale.append(
                    "Current unit risk supports monitoring with incremental improvements."
                )

            if not capacity:
                rationale.append("Bed-capacity enrichment missing; confidence reduced.")
            if not acuity:
                rationale.append("Acuity-intel enrichment missing; confidence reduced.")

            priority = self._priority_for(route)
            confidence = self._confidence_for(
                route=route,
                capacity_enriched=bool(capacity),
                acuity_enriched=bool(acuity),
            )

            decisions.append(
                ClinicalDecision(
                    unit_id=signal.unit_id,
                    team_id=signal.team_id,
                    service_line_id=signal.service_line_id,
                    route=route,
                    priority=priority,
                    confidence=confidence,
                    risk_score=risk_score,
                    occupancy_pct=max(0, min(100, occupancy_pct)),
                    staffed_bed_ratio=staffed_bed_ratio,
                    discharge_backlog=max(0, discharge_backlog),
                    diversion_risk=diversion_risk,
                    high_acuity_ratio=high_acuity_ratio,
                    deteriorating_patients=max(0, deteriorating_patients),
                    transfer_blockers=transfer_blockers,
                    surge_probability=surge_probability,
                    boarding_hours=max(0, boarding_hours),
                    waiting_patients=max(0, waiting_patients),
                    rationale=tuple(rationale),
                )
            )

        decisions.sort(
            key=lambda row: (
                row.route in {"critical_capacity_command", "surge_flow_stabilization"},
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
        decisions: list[ClinicalDecision],
        execute_actions: bool,
    ) -> list[ClinicalActionResult]:
        tasks: list[_ExecutionTask] = []
        skipped: list[ClinicalActionResult] = []

        for row in decisions:
            reason = "; ".join(row.rationale)
            if not execute_actions:
                skipped.append(
                    ClinicalActionResult(
                        integration="clinical_actions",
                        operation=row.route,
                        target=row.unit_id,
                        success=True,
                        latency_ms=0,
                        request={"unit_id": row.unit_id, "route": row.route},
                        status="skipped",
                        attempts=0,
                        notes=("action execution disabled by runtime policy",),
                    )
                )
                continue

            if row.route == "monitor":
                skipped.append(
                    ClinicalActionResult(
                        integration="clinical_actions",
                        operation="monitor",
                        target=row.unit_id,
                        success=True,
                        latency_ms=0,
                        request={"unit_id": row.unit_id, "route": "monitor"},
                        status="skipped",
                        attempts=0,
                        notes=("monitor route requires no external action call",),
                    )
                )
                continue

            if row.route in {"critical_capacity_command", "surge_flow_stabilization"}:
                if self.execution_policy.allow_auto_surge_staffing:
                    key = f"{batch_id}:surge:{row.unit_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="clinical_actions",
                            operation="activate_surge_staffing",
                            target=row.unit_id,
                            request_payload={"unit_id": row.unit_id, "reason": reason},
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.activate_surge_staffing(
                                    row.unit_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ClinicalActionResult(
                            integration="clinical_actions",
                            operation="activate_surge_staffing",
                            target=row.unit_id,
                            success=True,
                            latency_ms=0,
                            request={"unit_id": row.unit_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto surge-staffing disabled by policy",),
                        )
                    )

            if row.route in {
                "critical_capacity_command",
                "surge_flow_stabilization",
                "flow_optimization",
            }:
                if self.execution_policy.allow_auto_discharge_huddle:
                    key = f"{batch_id}:discharge:{row.unit_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="clinical_actions",
                            operation="prioritize_discharge_huddle",
                            target=row.unit_id,
                            request_payload={"unit_id": row.unit_id, "reason": reason},
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.prioritize_discharge_huddle(
                                    row.unit_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ClinicalActionResult(
                            integration="clinical_actions",
                            operation="prioritize_discharge_huddle",
                            target=row.unit_id,
                            success=True,
                            latency_ms=0,
                            request={"unit_id": row.unit_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto discharge-huddle actions disabled by policy",),
                        )
                    )

            if row.route in {"critical_capacity_command", "surge_flow_stabilization"}:
                if self.execution_policy.allow_auto_transfer_coordination:
                    key = f"{batch_id}:transfer:{row.unit_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="clinical_actions",
                            operation="open_transfer_coordination",
                            target=row.unit_id,
                            request_payload={"unit_id": row.unit_id, "reason": reason},
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.open_transfer_coordination(
                                    row.unit_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ClinicalActionResult(
                            integration="clinical_actions",
                            operation="open_transfer_coordination",
                            target=row.unit_id,
                            success=True,
                            latency_ms=0,
                            request={"unit_id": row.unit_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto transfer coordination disabled by policy",),
                        )
                    )

            if row.route == "critical_capacity_command":
                if self.execution_policy.allow_auto_hospital_command:
                    key = f"{batch_id}:command:{row.unit_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="clinical_actions",
                            operation="escalate_hospital_command",
                            target=row.unit_id,
                            request_payload={"unit_id": row.unit_id, "reason": reason},
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.escalate_hospital_command(
                                    row.unit_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ClinicalActionResult(
                            integration="clinical_actions",
                            operation="escalate_hospital_command",
                            target=row.unit_id,
                            success=True,
                            latency_ms=0,
                            request={"unit_id": row.unit_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto hospital-command escalation disabled by policy",),
                        )
                    )

            if row.route in {
                "critical_capacity_command",
                "surge_flow_stabilization",
                "flow_optimization",
            }:
                if self.execution_policy.allow_auto_coverage_rebalance:
                    key = f"{batch_id}:coverage:{row.team_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="clinical_actions",
                            operation="rebalance_clinician_coverage",
                            target=row.team_id,
                            request_payload={"team_id": row.team_id, "reason": reason},
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.rebalance_clinician_coverage(
                                    row.team_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ClinicalActionResult(
                            integration="clinical_actions",
                            operation="rebalance_clinician_coverage",
                            target=row.team_id,
                            success=True,
                            latency_ms=0,
                            request={"team_id": row.team_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto coverage rebalance disabled by policy",),
                        )
                    )

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
    def _as_int(data: dict[str, Any], *, keys: tuple[str, ...], default: int) -> int:
        for key in keys:
            value = data.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except Exception:  # noqa: BLE001
                continue
        return default

    @staticmethod
    def _priority_for(route: ClinicalRoute) -> str:
        if route == "critical_capacity_command":
            return "urgent"
        if route == "surge_flow_stabilization":
            return "high"
        if route == "flow_optimization":
            return "normal"
        return "low"

    @staticmethod
    def _confidence_for(
        *,
        route: ClinicalRoute,
        capacity_enriched: bool,
        acuity_enriched: bool,
    ) -> float:
        base = {
            "critical_capacity_command": 0.90,
            "surge_flow_stabilization": 0.84,
            "flow_optimization": 0.76,
            "monitor": 0.68,
        }[route]
        if not capacity_enriched:
            base -= 0.15
        if not acuity_enriched:
            base -= 0.15
        return round(min(0.99, max(0.05, base)), 3)

    @staticmethod
    def _build_stats(
        *,
        signals: list[ClinicalSignal],
        enrichments: list[ClinicalActionResult],
        decisions: list[ClinicalDecision],
        actions: list[ClinicalActionResult],
    ) -> ClinicalExecutionStats:
        route_counts: dict[ClinicalRoute, int] = defaultdict(int)
        for row in decisions:
            route_counts[row.route] += 1

        actions_success = sum(1 for row in actions if row.success and row.status == "executed")
        actions_skipped = sum(1 for row in actions if row.status == "skipped")
        actions_failed = sum(1 for row in actions if not row.success)

        return ClinicalExecutionStats(
            units_total=len(signals),
            enrichment_total=len(enrichments),
            enrichment_success=sum(1 for row in enrichments if row.success),
            actions_total=len(actions),
            actions_success=actions_success,
            actions_skipped=actions_skipped,
            actions_failed=actions_failed,
            critical_count=route_counts["critical_capacity_command"],
            surge_count=route_counts["surge_flow_stabilization"],
            flow_count=route_counts["flow_optimization"],
            monitor_count=route_counts["monitor"],
        )

    @staticmethod
    def _recommendations(
        *,
        pipeline_report: UseCaseExecutionReport,
        stats: ClinicalExecutionStats,
        decisions: list[ClinicalDecision],
        errors: list[str],
    ) -> list[str]:
        recs: list[str] = [
            (
                "Decision mix: "
                f"critical={stats.critical_count}, "
                f"surge={stats.surge_count}, "
                f"flow={stats.flow_count}, monitor={stats.monitor_count}."
            ),
            (
                f"Enrichment success {stats.enrichment_success}/{stats.enrichment_total}; "
                f"actions success={stats.actions_success}, skipped={stats.actions_skipped}, failed={stats.actions_failed}."
            ),
            "For critical units, trigger command cadence and transfer huddles every 30 minutes.",
            "For surge units, rebalance staffing and discharge focus by service line.",
            "For flow-optimization units, monitor boarding and waiting-patient trends shift-over-shift.",
        ]

        if pipeline_report.ranked_actions:
            recs.append(f"Primary tri-provider action: {pipeline_report.ranked_actions[0].action}")

        if errors:
            recs.append(
                "At least one integration failed; escalate impacted units to manual bed management review."
            )

        top = decisions[:3]
        if top:
            recs.append(
                "Top units: "
                + ", ".join(
                    f"{row.unit_id}:{row.route}:{row.risk_score:.2f}:{row.service_line_id}"
                    for row in top
                )
                + "."
            )

        return recs
