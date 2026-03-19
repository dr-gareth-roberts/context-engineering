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
GridActionResult = IntegrationActionResult

_INCIDENT_RE = re.compile(
    r"\b(?:OUT|OUTAGE|INC|EVENT)(?:[-_][A-Za-z0-9]{2,}|[0-9]{2,}[A-Za-z0-9]*)\b",
    re.IGNORECASE,
)
_SUBSTATION_RE = re.compile(
    r"\b(?:SUB|SUBSTATION)(?:[-_][A-Za-z0-9]{2,}|[0-9]{2,}[A-Za-z0-9]*)\b",
    re.IGNORECASE,
)
_FEEDER_RE = re.compile(
    r"\b(?:FEEDER|FDR|LINE)(?:[-_][A-Za-z0-9]{2,}|[0-9]{2,}[A-Za-z0-9]*)\b",
    re.IGNORECASE,
)
_CUSTOMERS_RE = re.compile(r"\b(\d{1,8})\s*(?:customers?|accounts?)\b", re.IGNORECASE)
_ETA_MINUTES_RE = re.compile(r"\b(\d{1,4})\s*(?:min|mins|minutes?)\b", re.IGNORECASE)
_ETA_HOURS_RE = re.compile(r"\b(\d{1,3})\s*(?:h|hr|hrs|hours?)\b", re.IGNORECASE)

_CRITICAL_KEYWORDS = (
    "hospital",
    "water treatment",
    "dialysis",
    "ems",
    "911",
    "fire station",
    "airport",
    "nursing home",
)
_CRITICAL_RE = re.compile(
    "|".join(re.escape(keyword) for keyword in _CRITICAL_KEYWORDS), re.IGNORECASE
)
_CASCADE_RE = re.compile(r"\bcascad(?:e|ing)\b", re.IGNORECASE)


def _normalize(value: str) -> str:
    return value.strip().replace("_", "-").upper()


class GridTelemetryAdapter(Protocol):
    def lookup_substation(self, substation_id: str) -> dict[str, Any]: ...


class CriticalLoadAdapter(Protocol):
    def lookup_feeder(self, feeder_id: str) -> dict[str, Any]: ...


class GridActionAdapter(Protocol):
    def dispatch_repair_crew(self, substation_id: str, *, reason: str) -> dict[str, Any]: ...

    def prioritize_feeder(self, feeder_id: str, *, reason: str) -> dict[str, Any]: ...

    def initiate_controlled_load_shed(self, feeder_id: str, *, reason: str) -> dict[str, Any]: ...

    def notify_emergency_ops(self, incident_id: str, *, reason: str) -> dict[str, Any]: ...


class NoOpGridTelemetryAdapter:
    def lookup_substation(self, substation_id: str) -> dict[str, Any]:
        return {
            "substation_id": substation_id,
            "instability_score": 0.28,
            "restoration_eta_minutes": 95,
            "customers_affected": 42000,
            "source": "noop",
        }


class NoOpCriticalLoadAdapter:
    def lookup_feeder(self, feeder_id: str) -> dict[str, Any]:
        return {
            "feeder_id": feeder_id,
            "critical_sites_count": 1,
            "hospitals_impacted": 0,
            "life_safety_load_mw": 8.0,
            "source": "noop",
        }


class NoOpGridActionAdapter:
    def dispatch_repair_crew(self, substation_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "substation_id": substation_id,
            "action": "dispatch_repair_crew",
            "reason": reason,
            "status": "noop",
        }

    def prioritize_feeder(self, feeder_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "feeder_id": feeder_id,
            "action": "prioritize_feeder",
            "reason": reason,
            "status": "noop",
        }

    def initiate_controlled_load_shed(self, feeder_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "feeder_id": feeder_id,
            "action": "initiate_controlled_load_shed",
            "reason": reason,
            "status": "noop",
        }

    def notify_emergency_ops(self, incident_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "incident_id": incident_id,
            "action": "notify_emergency_ops",
            "reason": reason,
            "status": "noop",
        }


@dataclass(slots=True)
class InMemoryGridTelemetryAdapter:
    substations: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_substation(self, substation_id: str) -> dict[str, Any]:
        substation = _normalize(substation_id)
        payload = self.substations.get(substation, {})
        instability = float(payload.get("instability_score", 0.3))
        eta_minutes = int(payload.get("restoration_eta_minutes", 90))
        customers = int(payload.get("customers_affected", 30000))
        return {
            "substation_id": substation,
            "instability_score": max(0.0, min(1.0, instability)),
            "restoration_eta_minutes": max(0, eta_minutes),
            "customers_affected": max(0, customers),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryCriticalLoadAdapter:
    feeders: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_feeder(self, feeder_id: str) -> dict[str, Any]:
        feeder = _normalize(feeder_id)
        payload = self.feeders.get(feeder, {})
        critical_sites = int(payload.get("critical_sites_count", 1))
        hospitals = int(payload.get("hospitals_impacted", 0))
        load_mw = float(payload.get("life_safety_load_mw", 10.0))
        return {
            "feeder_id": feeder,
            "critical_sites_count": max(0, critical_sites),
            "hospitals_impacted": max(0, hospitals),
            "life_safety_load_mw": max(0.0, load_mw),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryGridActionAdapter:
    dispatched_substations: set[str] = field(default_factory=set)
    prioritized_feeders: set[str] = field(default_factory=set)
    load_shed_feeders: set[str] = field(default_factory=set)
    notified_incidents: set[str] = field(default_factory=set)

    def dispatch_repair_crew(self, substation_id: str, *, reason: str) -> dict[str, Any]:
        substation = _normalize(substation_id)
        self.dispatched_substations.add(substation)
        return {
            "substation_id": substation,
            "action": "dispatch_repair_crew",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def prioritize_feeder(self, feeder_id: str, *, reason: str) -> dict[str, Any]:
        feeder = _normalize(feeder_id)
        self.prioritized_feeders.add(feeder)
        return {
            "feeder_id": feeder,
            "action": "prioritize_feeder",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def initiate_controlled_load_shed(self, feeder_id: str, *, reason: str) -> dict[str, Any]:
        feeder = _normalize(feeder_id)
        self.load_shed_feeders.add(feeder)
        return {
            "feeder_id": feeder,
            "action": "initiate_controlled_load_shed",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def notify_emergency_ops(self, incident_id: str, *, reason: str) -> dict[str, Any]:
        incident = _normalize(incident_id)
        self.notified_incidents.add(incident)
        return {
            "incident_id": incident,
            "action": "notify_emergency_ops",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }


_HTTPJSONAdapterBase = HTTPJSONAdapterBase


@dataclass(slots=True)
class HTTPGridTelemetryAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/grid/telemetry"

    def lookup_substation(self, substation_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"substation_id": substation_id})


@dataclass(slots=True)
class HTTPCriticalLoadAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/grid/critical_load"

    def lookup_feeder(self, feeder_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"feeder_id": feeder_id})


@dataclass(slots=True)
class HTTPGridActionAdapter(HTTPJSONAdapterBase):
    dispatch_path: str = "/grid/dispatch"
    prioritize_path: str = "/grid/prioritize_feeder"
    load_shed_path: str = "/grid/controlled_load_shed"
    notify_path: str = "/grid/notify_eoc"

    def dispatch_repair_crew(self, substation_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.dispatch_path,
            {"substation_id": substation_id, "reason": reason},
        )

    def prioritize_feeder(self, feeder_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.prioritize_path,
            {"feeder_id": feeder_id, "reason": reason},
        )

    def initiate_controlled_load_shed(self, feeder_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.load_shed_path,
            {"feeder_id": feeder_id, "reason": reason},
        )

    def notify_emergency_ops(self, incident_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.notify_path,
            {"incident_id": incident_id, "reason": reason},
        )


def build_grid_telemetry_adapter_from_env() -> GridTelemetryAdapter:
    base = os.getenv("GRID_TELEMETRY_BASE_URL")
    token = os.getenv("GRID_TELEMETRY_API_KEY")
    if base and token:
        path = os.getenv("GRID_TELEMETRY_LOOKUP_PATH", "/grid/telemetry")
        return HTTPGridTelemetryAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpGridTelemetryAdapter()


def build_critical_load_adapter_from_env() -> CriticalLoadAdapter:
    base = os.getenv("GRID_CRITICAL_BASE_URL")
    token = os.getenv("GRID_CRITICAL_API_KEY")
    if base and token:
        path = os.getenv("GRID_CRITICAL_LOOKUP_PATH", "/grid/critical_load")
        return HTTPCriticalLoadAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpCriticalLoadAdapter()


def build_grid_action_adapter_from_env() -> GridActionAdapter:
    base = os.getenv("GRID_ACTION_BASE_URL")
    token = os.getenv("GRID_ACTION_API_KEY")
    if base and token:
        return HTTPGridActionAdapter(
            base_url=base,
            api_key=token,
            dispatch_path=os.getenv("GRID_ACTION_DISPATCH_PATH", "/grid/dispatch"),
            prioritize_path=os.getenv("GRID_ACTION_PRIORITIZE_PATH", "/grid/prioritize_feeder"),
            load_shed_path=os.getenv("GRID_ACTION_LOAD_SHED_PATH", "/grid/controlled_load_shed"),
            notify_path=os.getenv("GRID_ACTION_NOTIFY_PATH", "/grid/notify_eoc"),
        )
    return NoOpGridActionAdapter()


GridRoute = Literal[
    "blackstart_escalation", "priority_restoration", "controlled_load_shed", "monitor"
]


@dataclass(slots=True, frozen=True)
class GridSignal:
    incident_id: str
    substation_id: str
    feeder_id: str
    observed_customers_affected: int | None
    observed_restoration_eta_minutes: int | None
    critical_facility_hint: str | None
    cascading_indicator: bool


@dataclass(slots=True, frozen=True)
class GridDecision:
    incident_id: str
    substation_id: str
    feeder_id: str
    route: GridRoute
    priority: str
    confidence: float
    risk_score: float
    instability_score: float
    life_safety_load_mw: float
    customers_affected: int
    restoration_eta_minutes: int
    hospitals_impacted: int
    critical_sites_count: int
    rationale: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class GridExecutionPolicy:
    execute_actions_in_dry_run: bool = False
    max_parallel_tasks: int = 6
    max_incidents_to_process: int = 20
    blackstart_instability_threshold: float = 0.90
    emergency_risk_threshold: float = 0.82
    priority_restore_risk_threshold: float = 0.58
    controlled_shed_instability_threshold: float = 0.66
    major_outage_customers_threshold: int = 250_000
    critical_load_mw_threshold: float = 45.0
    allow_auto_dispatch: bool = True
    allow_auto_feeder_priority: bool = True
    allow_auto_load_shed: bool = True
    allow_auto_notify_eoc: bool = True

    def __post_init__(self) -> None:
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be >= 1")
        if self.max_incidents_to_process < 1:
            raise ValueError("max_incidents_to_process must be >= 1")
        if self.major_outage_customers_threshold < 1:
            raise ValueError("major_outage_customers_threshold must be >= 1")
        if self.critical_load_mw_threshold < 0:
            raise ValueError("critical_load_mw_threshold must be >= 0")
        for name, value in (
            ("blackstart_instability_threshold", self.blackstart_instability_threshold),
            ("emergency_risk_threshold", self.emergency_risk_threshold),
            ("priority_restore_risk_threshold", self.priority_restore_risk_threshold),
            ("controlled_shed_instability_threshold", self.controlled_shed_instability_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(slots=True, frozen=True)
class GridExecutionStats:
    incidents_total: int
    enrichment_total: int
    enrichment_success: int
    actions_total: int
    actions_success: int
    actions_skipped: int
    actions_failed: int
    blackstart_count: int
    priority_restore_count: int
    controlled_shed_count: int
    monitor_count: int


@dataclass(slots=True, frozen=True)
class GridExecutionReport:
    batch_id: str
    pipeline_report: UseCaseExecutionReport
    mode: str
    started_at: datetime
    completed_at: datetime
    signals: tuple[GridSignal, ...]
    enrichments: tuple[GridActionResult, ...]
    decisions: tuple[GridDecision, ...]
    actions: tuple[GridActionResult, ...]
    stats: GridExecutionStats
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
class GridOutageCommander(BaseIntegrationCommanderMixin):
    pipeline: TriProviderPipeline
    telemetry_adapter: GridTelemetryAdapter
    critical_load_adapter: CriticalLoadAdapter
    action_adapter: GridActionAdapter
    execution_policy: GridExecutionPolicy = field(default_factory=GridExecutionPolicy)
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
    ) -> GridExecutionReport:
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
            max_signals=self.execution_policy.max_incidents_to_process,
        )

        enrichments = self._run_enrichment(signals)
        decisions = self._build_decisions(signals, enrichments)

        execute_actions = True
        if mode == "dry" and not self.execution_policy.execute_actions_in_dry_run:
            execute_actions = False
            warnings.append("Grid operations actions skipped in dry mode by execution policy.")

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
        return GridExecutionReport(
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
    def extract_signals(text: str, *, max_signals: int = 20) -> list[GridSignal]:
        incident_matches = list(_INCIDENT_RE.finditer(text))
        substations = [_normalize(m.group(0)) for m in _SUBSTATION_RE.finditer(text)]
        feeders = [_normalize(m.group(0)) for m in _FEEDER_RE.finditer(text)]
        global_customer_counts = [int(m.group(1)) for m in _CUSTOMERS_RE.finditer(text)]

        global_eta_minutes: list[int] = []
        global_eta_minutes.extend(int(m.group(1)) for m in _ETA_MINUTES_RE.finditer(text))
        global_eta_minutes.extend(int(m.group(1)) * 60 for m in _ETA_HOURS_RE.finditer(text))

        critical_hits = [m.group(0).lower() for m in _CRITICAL_RE.finditer(text)]
        has_global_cascade = bool(_CASCADE_RE.search(text))

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

        if not incident_matches:
            incident_id = f"OUT-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:8].upper()}"
            return [
                GridSignal(
                    incident_id=incident_id,
                    substation_id=_pick(substations, 0, "SUB-AUTO-01"),
                    feeder_id=_pick(feeders, 0, "FEEDER-AUTO-01"),
                    observed_customers_affected=_pick_int(global_customer_counts, 0),
                    observed_restoration_eta_minutes=_pick_int(global_eta_minutes, 0),
                    critical_facility_hint=_pick(critical_hits, 0, "") or None,
                    cascading_indicator=has_global_cascade,
                )
            ]

        rows: list[GridSignal] = []
        seen_incidents: set[str] = set()
        for idx, match in enumerate(incident_matches):
            if len(rows) >= max_signals:
                break

            incident_id = _normalize(match.group(0))
            incident_key = incident_id.lower()
            if incident_key in seen_incidents:
                continue
            seen_incidents.add(incident_key)

            segment_index = len(rows)
            start = match.start()
            end = (
                incident_matches[idx + 1].start() if idx + 1 < len(incident_matches) else len(text)
            )
            segment = text[start:end]

            substation_match = _SUBSTATION_RE.search(segment)
            feeder_match = _FEEDER_RE.search(segment)
            customer_match = _CUSTOMERS_RE.search(segment)
            eta_match_minutes = _ETA_MINUTES_RE.search(segment)
            eta_match_hours = _ETA_HOURS_RE.search(segment)
            critical_match = _CRITICAL_RE.search(segment)

            observed_eta: int | None = None
            if eta_match_minutes:
                observed_eta = int(eta_match_minutes.group(1))
            elif eta_match_hours:
                observed_eta = int(eta_match_hours.group(1)) * 60
            else:
                observed_eta = _pick_int(global_eta_minutes, segment_index)

            rows.append(
                GridSignal(
                    incident_id=incident_id,
                    substation_id=_normalize(substation_match.group(0))
                    if substation_match
                    else _pick(substations, segment_index, "SUB-AUTO-01"),
                    feeder_id=_normalize(feeder_match.group(0))
                    if feeder_match
                    else _pick(feeders, segment_index, "FEEDER-AUTO-01"),
                    observed_customers_affected=int(customer_match.group(1))
                    if customer_match
                    else _pick_int(global_customer_counts, segment_index),
                    observed_restoration_eta_minutes=observed_eta,
                    critical_facility_hint=critical_match.group(0).lower()
                    if critical_match
                    else (_pick(critical_hits, segment_index, "") or None),
                    cascading_indicator=bool(_CASCADE_RE.search(segment)) or has_global_cascade,
                )
            )

        return rows

    @staticmethod
    def _build_batch_id(scenario: str, started_at: datetime) -> str:
        digest = hashlib.sha256(
            f"{started_at.isoformat()}::{scenario}".encode("utf-8")
        ).hexdigest()[:16]
        return f"grid-{started_at.strftime('%Y%m%d%H%M%S')}-{digest}"

    def _run_enrichment(self, signals: list[GridSignal]) -> list[GridActionResult]:
        tasks: list[_ExecutionTask] = []

        substation_ids = _unique_preserve([signal.substation_id for signal in signals])
        for substation_id in substation_ids:
            tasks.append(
                _ExecutionTask(
                    integration="telemetry",
                    operation="lookup_substation",
                    target=substation_id,
                    request_payload={"substation_id": substation_id},
                    idempotency_key=None,
                    call=lambda substation_id=substation_id: (
                        self.telemetry_adapter.lookup_substation(substation_id)
                    ),
                )
            )

        feeder_ids = _unique_preserve([signal.feeder_id for signal in signals])
        for feeder_id in feeder_ids:
            tasks.append(
                _ExecutionTask(
                    integration="critical_load",
                    operation="lookup_feeder",
                    target=feeder_id,
                    request_payload={"feeder_id": feeder_id},
                    idempotency_key=None,
                    call=lambda feeder_id=feeder_id: self.critical_load_adapter.lookup_feeder(
                        feeder_id
                    ),
                )
            )

        return self._execute_integration_tasks(tasks)

    def _build_decisions(
        self,
        signals: list[GridSignal],
        enrichments: list[GridActionResult],
    ) -> list[GridDecision]:
        telemetry_data: dict[str, dict[str, Any]] = {}
        critical_data: dict[str, dict[str, Any]] = {}

        for row in enrichments:
            if not row.success or row.status != "executed":
                continue
            if row.integration == "telemetry":
                telemetry_data[row.target] = row.response or {}
            elif row.integration == "critical_load":
                critical_data[row.target] = row.response or {}

        decisions: list[GridDecision] = []
        for signal in signals:
            telemetry = telemetry_data.get(signal.substation_id, {})
            critical = critical_data.get(signal.feeder_id, {})

            instability = self._as_float(
                telemetry,
                keys=("instability_score", "stability_risk", "cascade_risk"),
                default=0.25,
            )
            eta_minutes = int(
                self._as_float(
                    telemetry,
                    keys=("restoration_eta_minutes", "eta_minutes", "eta"),
                    default=float(signal.observed_restoration_eta_minutes or 90),
                    cap_1=False,
                )
            )
            telemetry_customers = int(
                self._as_float(
                    telemetry,
                    keys=("customers_affected",),
                    default=0.0,
                    cap_1=False,
                )
            )
            customers_affected = max(signal.observed_customers_affected or 0, telemetry_customers)

            critical_sites = int(
                self._as_float(
                    critical,
                    keys=("critical_sites_count", "sites_count", "priority_sites"),
                    default=0.0,
                    cap_1=False,
                )
            )
            hospitals_impacted = int(
                self._as_float(
                    critical,
                    keys=("hospitals_impacted", "hospital_count"),
                    default=1.0 if signal.critical_facility_hint == "hospital" else 0.0,
                    cap_1=False,
                )
            )
            life_safety_load = self._as_float(
                critical,
                keys=("life_safety_load_mw", "critical_load_mw", "priority_load_mw"),
                default=0.0,
                cap_1=False,
            )
            if signal.critical_facility_hint and critical_sites <= 0:
                critical_sites = 1

            risk_score = min(
                1.0,
                instability * 0.42
                + min(1.0, customers_affected / 1_500_000.0) * 0.24
                + min(1.0, life_safety_load / 120.0) * 0.18
                + min(1.0, eta_minutes / 240.0) * 0.12
                + (0.08 if hospitals_impacted > 0 else 0.0)
                + (0.06 if signal.cascading_indicator else 0.0)
                + (0.04 if critical_sites >= 3 else 0.0),
            )

            route: GridRoute = "monitor"
            rationale: list[str] = []
            if (
                instability >= self.execution_policy.blackstart_instability_threshold
                or risk_score >= self.execution_policy.emergency_risk_threshold
            ):
                route = "blackstart_escalation"
                rationale.append(
                    "Instability/emergency risk threshold crossed; activate blackstart escalation."
                )
            elif instability >= self.execution_policy.controlled_shed_instability_threshold and (
                customers_affected >= self.execution_policy.major_outage_customers_threshold
                or eta_minutes >= 180
                or signal.cascading_indicator
            ):
                route = "controlled_load_shed"
                rationale.append(
                    "Grid instability indicates controlled load-shed to contain outage spread."
                )
            elif risk_score >= self.execution_policy.priority_restore_risk_threshold or (
                customers_affected >= self.execution_policy.major_outage_customers_threshold
                and (
                    life_safety_load >= self.execution_policy.critical_load_mw_threshold
                    or hospitals_impacted > 0
                    or critical_sites >= 2
                )
            ):
                route = "priority_restoration"
                rationale.append(
                    "High impact to critical services/customers; prioritize restoration sequence."
                )
            else:
                rationale.append(
                    "Current signal supports monitoring and staged restoration readiness."
                )

            if not telemetry:
                rationale.append("Telemetry enrichment missing; confidence reduced.")
            if not critical:
                rationale.append("Critical-load enrichment missing; confidence reduced.")

            priority = self._priority_for(route)
            confidence = self._confidence_for(
                route=route,
                telemetry_enriched=bool(telemetry),
                critical_enriched=bool(critical),
            )

            decisions.append(
                GridDecision(
                    incident_id=signal.incident_id,
                    substation_id=signal.substation_id,
                    feeder_id=signal.feeder_id,
                    route=route,
                    priority=priority,
                    confidence=confidence,
                    risk_score=risk_score,
                    instability_score=instability,
                    life_safety_load_mw=life_safety_load,
                    customers_affected=customers_affected,
                    restoration_eta_minutes=max(0, eta_minutes),
                    hospitals_impacted=max(0, hospitals_impacted),
                    critical_sites_count=max(0, critical_sites),
                    rationale=tuple(rationale),
                )
            )

        decisions.sort(
            key=lambda row: (
                row.route
                in {"blackstart_escalation", "controlled_load_shed", "priority_restoration"},
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
        decisions: list[GridDecision],
        execute_actions: bool,
    ) -> list[GridActionResult]:
        tasks: list[_ExecutionTask] = []
        skipped: list[GridActionResult] = []

        for row in decisions:
            reason = "; ".join(row.rationale)
            if not execute_actions:
                skipped.append(
                    GridActionResult(
                        integration="grid_actions",
                        operation=row.route,
                        target=row.incident_id,
                        success=True,
                        latency_ms=0,
                        request={"incident_id": row.incident_id, "route": row.route},
                        status="skipped",
                        attempts=0,
                        notes=("action execution disabled by runtime policy",),
                    )
                )
                continue

            if row.route == "monitor":
                skipped.append(
                    GridActionResult(
                        integration="grid_actions",
                        operation="monitor",
                        target=row.incident_id,
                        success=True,
                        latency_ms=0,
                        request={"incident_id": row.incident_id, "route": "monitor"},
                        status="skipped",
                        attempts=0,
                        notes=("monitor route requires no external action call",),
                    )
                )
                continue

            if row.route in {"blackstart_escalation", "priority_restoration"}:
                if self.execution_policy.allow_auto_dispatch:
                    dispatch_key = f"{batch_id}:dispatch:{row.substation_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="grid_actions",
                            operation="dispatch_repair_crew",
                            target=row.substation_id,
                            request_payload={"substation_id": row.substation_id, "reason": reason},
                            idempotency_key=dispatch_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.dispatch_repair_crew(
                                    row.substation_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        GridActionResult(
                            integration="grid_actions",
                            operation="dispatch_repair_crew",
                            target=row.substation_id,
                            success=True,
                            latency_ms=0,
                            request={"substation_id": row.substation_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto crew dispatch disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_feeder_priority:
                    prioritize_key = f"{batch_id}:prioritize:{row.feeder_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="grid_actions",
                            operation="prioritize_feeder",
                            target=row.feeder_id,
                            request_payload={"feeder_id": row.feeder_id, "reason": reason},
                            idempotency_key=prioritize_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.prioritize_feeder(
                                    row.feeder_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        GridActionResult(
                            integration="grid_actions",
                            operation="prioritize_feeder",
                            target=row.feeder_id,
                            success=True,
                            latency_ms=0,
                            request={"feeder_id": row.feeder_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto feeder prioritization disabled by policy",),
                        )
                    )

                if row.route == "blackstart_escalation":
                    if self.execution_policy.allow_auto_notify_eoc:
                        notify_key = f"{batch_id}:notify:{row.incident_id}"
                        tasks.append(
                            _ExecutionTask(
                                integration="grid_actions",
                                operation="notify_emergency_ops",
                                target=row.incident_id,
                                request_payload={"incident_id": row.incident_id, "reason": reason},
                                idempotency_key=notify_key,
                                call=lambda row=row, reason=reason: (
                                    self.action_adapter.notify_emergency_ops(
                                        row.incident_id,
                                        reason=reason,
                                    )
                                ),
                            )
                        )
                    else:
                        skipped.append(
                            GridActionResult(
                                integration="grid_actions",
                                operation="notify_emergency_ops",
                                target=row.incident_id,
                                success=True,
                                latency_ms=0,
                                request={"incident_id": row.incident_id},
                                status="skipped",
                                attempts=0,
                                notes=("auto emergency-ops notification disabled by policy",),
                            )
                        )
                continue

            if row.route == "controlled_load_shed":
                if self.execution_policy.allow_auto_load_shed:
                    shed_key = f"{batch_id}:shed:{row.feeder_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="grid_actions",
                            operation="initiate_controlled_load_shed",
                            target=row.feeder_id,
                            request_payload={"feeder_id": row.feeder_id, "reason": reason},
                            idempotency_key=shed_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.initiate_controlled_load_shed(
                                    row.feeder_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        GridActionResult(
                            integration="grid_actions",
                            operation="initiate_controlled_load_shed",
                            target=row.feeder_id,
                            success=True,
                            latency_ms=0,
                            request={"feeder_id": row.feeder_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto controlled load-shed disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_notify_eoc:
                    notify_key = f"{batch_id}:notify:{row.incident_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="grid_actions",
                            operation="notify_emergency_ops",
                            target=row.incident_id,
                            request_payload={"incident_id": row.incident_id, "reason": reason},
                            idempotency_key=notify_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.notify_emergency_ops(
                                    row.incident_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        GridActionResult(
                            integration="grid_actions",
                            operation="notify_emergency_ops",
                            target=row.incident_id,
                            success=True,
                            latency_ms=0,
                            request={"incident_id": row.incident_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto emergency-ops notification disabled by policy",),
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
    def _priority_for(route: GridRoute) -> str:
        if route == "blackstart_escalation":
            return "urgent"
        if route in {"priority_restoration", "controlled_load_shed"}:
            return "high"
        return "low"

    @staticmethod
    def _confidence_for(
        *,
        route: GridRoute,
        telemetry_enriched: bool,
        critical_enriched: bool,
    ) -> float:
        base = {
            "blackstart_escalation": 0.9,
            "priority_restoration": 0.82,
            "controlled_load_shed": 0.84,
            "monitor": 0.68,
        }[route]
        if not telemetry_enriched:
            base -= 0.15
        if not critical_enriched:
            base -= 0.15
        return round(min(0.99, max(0.05, base)), 3)

    @staticmethod
    def _build_stats(
        *,
        signals: list[GridSignal],
        enrichments: list[GridActionResult],
        decisions: list[GridDecision],
        actions: list[GridActionResult],
    ) -> GridExecutionStats:
        route_counts: dict[GridRoute, int] = defaultdict(int)
        for row in decisions:
            route_counts[row.route] += 1

        actions_success = sum(1 for row in actions if row.success and row.status == "executed")
        actions_skipped = sum(1 for row in actions if row.status == "skipped")
        actions_failed = sum(1 for row in actions if not row.success)

        return GridExecutionStats(
            incidents_total=len(signals),
            enrichment_total=len(enrichments),
            enrichment_success=sum(1 for row in enrichments if row.success),
            actions_total=len(actions),
            actions_success=actions_success,
            actions_skipped=actions_skipped,
            actions_failed=actions_failed,
            blackstart_count=route_counts["blackstart_escalation"],
            priority_restore_count=route_counts["priority_restoration"],
            controlled_shed_count=route_counts["controlled_load_shed"],
            monitor_count=route_counts["monitor"],
        )

    @staticmethod
    def _recommendations(
        *,
        pipeline_report: UseCaseExecutionReport,
        stats: GridExecutionStats,
        decisions: list[GridDecision],
        errors: list[str],
    ) -> list[str]:
        recs: list[str] = [
            (
                "Decision mix: "
                f"blackstart={stats.blackstart_count}, "
                f"priority_restoration={stats.priority_restore_count}, "
                f"controlled_load_shed={stats.controlled_shed_count}, "
                f"monitor={stats.monitor_count}."
            ),
            (
                f"Enrichment success {stats.enrichment_success}/{stats.enrichment_total}; "
                f"actions success={stats.actions_success}, skipped={stats.actions_skipped}, failed={stats.actions_failed}."
            ),
            "For blackstart cases, validate generation capacity and restoration switching sequence before energization.",
            "For priority restoration cases, sequence feeders by critical load and telecom/water dependencies.",
            "For controlled load-shed cases, keep emergency services and life-safety circuits protected.",
        ]

        if pipeline_report.ranked_actions:
            recs.append(f"Primary tri-provider action: {pipeline_report.ranked_actions[0].action}")

        if errors:
            recs.append(
                "At least one integration failed; route affected incidents to manual incident command review."
            )

        top = decisions[:3]
        if top:
            recs.append(
                "Top incidents: "
                + ", ".join(
                    f"{row.incident_id}:{row.route}:{row.risk_score:.2f}:{row.customers_affected}"
                    for row in top
                )
                + "."
            )

        return recs
