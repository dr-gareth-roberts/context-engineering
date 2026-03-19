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
EOCActionResult = IntegrationActionResult

_INCIDENT_RE = re.compile(
    r"\b(?:EOC|INC|EVENT|HAZ)(?:[-_][A-Za-z0-9]{2,}|[0-9]{2,}[A-Za-z0-9]*)\b",
    re.IGNORECASE,
)
_ZONE_RE = re.compile(
    r"\b(?:ZONE|SECTOR|DISTRICT)(?:[-_][A-Za-z0-9]{2,}|[0-9]{2,}[A-Za-z0-9]*)\b",
    re.IGNORECASE,
)
_UNIT_RE = re.compile(
    r"\b(?:UNIT|TEAM|CREW)(?:[-_][A-Za-z0-9]{2,}|[0-9]{2,}[A-Za-z0-9]*)\b",
    re.IGNORECASE,
)
_PEOPLE_RE = re.compile(
    r"\b(\d{1,8})\s*(?:people|residents|evacuees|households)\b",
    re.IGNORECASE,
)
_ETA_MINUTES_RE = re.compile(r"\b(\d{1,4})\s*(?:min|mins|minutes?)\b", re.IGNORECASE)
_ETA_HOURS_RE = re.compile(r"\b(\d{1,3})\s*(?:h|hr|hrs|hours?)\b", re.IGNORECASE)

_HAZARD_KEYWORDS = (
    "wildfire",
    "flood",
    "flash flood",
    "hurricane",
    "tornado",
    "earthquake",
    "toxic plume",
    "chemical leak",
    "landslide",
)
_VULNERABLE_KEYWORDS = (
    "hospital",
    "nursing home",
    "elderly",
    "school",
    "dialysis",
    "prison",
    "shelter",
    "water treatment",
)
_HAZARD_RE = re.compile("|".join(re.escape(keyword) for keyword in _HAZARD_KEYWORDS), re.IGNORECASE)
_VULNERABLE_RE = re.compile(
    "|".join(re.escape(keyword) for keyword in _VULNERABLE_KEYWORDS),
    re.IGNORECASE,
)
_EVAC_ORDER_RE = re.compile(
    r"(?:mandatory evacuation|evacuation order|immediate evacuation)",
    re.IGNORECASE,
)


def _normalize(value: str) -> str:
    return value.strip().replace("_", "-").upper()


class HazardIntelAdapter(Protocol):
    def lookup_zone(self, zone_id: str) -> dict[str, Any]: ...


class LogisticsCapacityAdapter(Protocol):
    def lookup_zone(self, zone_id: str) -> dict[str, Any]: ...


class EOCActionAdapter(Protocol):
    def activate_evacuation(self, zone_id: str, *, reason: str) -> dict[str, Any]: ...

    def open_shelter(self, zone_id: str, *, reason: str) -> dict[str, Any]: ...

    def preposition_resources(
        self,
        resource_unit_id: str,
        *,
        zone_id: str,
        reason: str,
    ) -> dict[str, Any]: ...

    def issue_public_alert(self, incident_id: str, *, reason: str) -> dict[str, Any]: ...


class NoOpHazardIntelAdapter:
    def lookup_zone(self, zone_id: str) -> dict[str, Any]:
        return {
            "zone_id": zone_id,
            "hazard_severity": 0.32,
            "spread_velocity": 0.30,
            "weather_volatility": 0.25,
            "time_to_impact_minutes": 180,
            "source": "noop",
        }


class NoOpLogisticsCapacityAdapter:
    def lookup_zone(self, zone_id: str) -> dict[str, Any]:
        return {
            "zone_id": zone_id,
            "population_exposed": 45000,
            "vulnerable_sites_count": 1,
            "shelter_capacity_pct": 0.72,
            "route_access_score": 0.70,
            "source": "noop",
        }


class NoOpEOCActionAdapter:
    def activate_evacuation(self, zone_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "zone_id": zone_id,
            "action": "activate_evacuation",
            "reason": reason,
            "status": "noop",
        }

    def open_shelter(self, zone_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "zone_id": zone_id,
            "action": "open_shelter",
            "reason": reason,
            "status": "noop",
        }

    def preposition_resources(
        self,
        resource_unit_id: str,
        *,
        zone_id: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "resource_unit_id": resource_unit_id,
            "zone_id": zone_id,
            "action": "preposition_resources",
            "reason": reason,
            "status": "noop",
        }

    def issue_public_alert(self, incident_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "incident_id": incident_id,
            "action": "issue_public_alert",
            "reason": reason,
            "status": "noop",
        }


@dataclass(slots=True)
class InMemoryHazardIntelAdapter:
    zones: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_zone(self, zone_id: str) -> dict[str, Any]:
        zone = _normalize(zone_id)
        payload = self.zones.get(zone, {})
        severity = float(payload.get("hazard_severity", 0.34))
        spread = float(payload.get("spread_velocity", 0.30))
        weather = float(payload.get("weather_volatility", 0.25))
        impact_minutes = int(payload.get("time_to_impact_minutes", 180))
        return {
            "zone_id": zone,
            "hazard_severity": max(0.0, min(1.0, severity)),
            "spread_velocity": max(0.0, min(1.0, spread)),
            "weather_volatility": max(0.0, min(1.0, weather)),
            "time_to_impact_minutes": max(0, impact_minutes),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryLogisticsCapacityAdapter:
    zones: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_zone(self, zone_id: str) -> dict[str, Any]:
        zone = _normalize(zone_id)
        payload = self.zones.get(zone, {})
        population = int(payload.get("population_exposed", 35000))
        vulnerable_sites = int(payload.get("vulnerable_sites_count", 1))
        shelter_capacity = float(payload.get("shelter_capacity_pct", 0.75))
        route_access = float(payload.get("route_access_score", 0.72))
        return {
            "zone_id": zone,
            "population_exposed": max(0, population),
            "vulnerable_sites_count": max(0, vulnerable_sites),
            "shelter_capacity_pct": max(0.0, min(1.0, shelter_capacity)),
            "route_access_score": max(0.0, min(1.0, route_access)),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryEOCActionAdapter:
    evacuation_zones: set[str] = field(default_factory=set)
    opened_shelter_zones: set[str] = field(default_factory=set)
    prepositioned_units: dict[str, str] = field(default_factory=dict)
    alerted_incidents: set[str] = field(default_factory=set)

    def activate_evacuation(self, zone_id: str, *, reason: str) -> dict[str, Any]:
        zone = _normalize(zone_id)
        self.evacuation_zones.add(zone)
        return {
            "zone_id": zone,
            "action": "activate_evacuation",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def open_shelter(self, zone_id: str, *, reason: str) -> dict[str, Any]:
        zone = _normalize(zone_id)
        self.opened_shelter_zones.add(zone)
        return {
            "zone_id": zone,
            "action": "open_shelter",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def preposition_resources(
        self,
        resource_unit_id: str,
        *,
        zone_id: str,
        reason: str,
    ) -> dict[str, Any]:
        unit = _normalize(resource_unit_id)
        zone = _normalize(zone_id)
        self.prepositioned_units[unit] = zone
        return {
            "resource_unit_id": unit,
            "zone_id": zone,
            "action": "preposition_resources",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def issue_public_alert(self, incident_id: str, *, reason: str) -> dict[str, Any]:
        incident = _normalize(incident_id)
        self.alerted_incidents.add(incident)
        return {
            "incident_id": incident,
            "action": "issue_public_alert",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }


_HTTPJSONAdapterBase = HTTPJSONAdapterBase


@dataclass(slots=True)
class HTTPHazardIntelAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/eoc/hazard_intel"

    def lookup_zone(self, zone_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"zone_id": zone_id})


@dataclass(slots=True)
class HTTPLogisticsCapacityAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/eoc/logistics_capacity"

    def lookup_zone(self, zone_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"zone_id": zone_id})


@dataclass(slots=True)
class HTTPEOCActionAdapter(HTTPJSONAdapterBase):
    evacuation_path: str = "/eoc/activate_evacuation"
    shelter_path: str = "/eoc/open_shelter"
    preposition_path: str = "/eoc/preposition_resources"
    alert_path: str = "/eoc/public_alert"

    def activate_evacuation(self, zone_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.evacuation_path,
            {"zone_id": zone_id, "reason": reason},
        )

    def open_shelter(self, zone_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.shelter_path,
            {"zone_id": zone_id, "reason": reason},
        )

    def preposition_resources(
        self,
        resource_unit_id: str,
        *,
        zone_id: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._post(
            self.preposition_path,
            {
                "resource_unit_id": resource_unit_id,
                "zone_id": zone_id,
                "reason": reason,
            },
        )

    def issue_public_alert(self, incident_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.alert_path,
            {"incident_id": incident_id, "reason": reason},
        )


def build_hazard_intel_adapter_from_env() -> HazardIntelAdapter:
    base = os.getenv("EOC_HAZARD_BASE_URL")
    token = os.getenv("EOC_HAZARD_API_KEY")
    if base and token:
        path = os.getenv("EOC_HAZARD_LOOKUP_PATH", "/eoc/hazard_intel")
        return HTTPHazardIntelAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpHazardIntelAdapter()


def build_logistics_capacity_adapter_from_env() -> LogisticsCapacityAdapter:
    base = os.getenv("EOC_LOGISTICS_BASE_URL")
    token = os.getenv("EOC_LOGISTICS_API_KEY")
    if base and token:
        path = os.getenv("EOC_LOGISTICS_LOOKUP_PATH", "/eoc/logistics_capacity")
        return HTTPLogisticsCapacityAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpLogisticsCapacityAdapter()


def build_eoc_action_adapter_from_env() -> EOCActionAdapter:
    base = os.getenv("EOC_ACTION_BASE_URL")
    token = os.getenv("EOC_ACTION_API_KEY")
    if base and token:
        return HTTPEOCActionAdapter(
            base_url=base,
            api_key=token,
            evacuation_path=os.getenv("EOC_ACTION_EVAC_PATH", "/eoc/activate_evacuation"),
            shelter_path=os.getenv("EOC_ACTION_SHELTER_PATH", "/eoc/open_shelter"),
            preposition_path=os.getenv("EOC_ACTION_PREPOSITION_PATH", "/eoc/preposition_resources"),
            alert_path=os.getenv("EOC_ACTION_ALERT_PATH", "/eoc/public_alert"),
        )
    return NoOpEOCActionAdapter()


EOCRoute = Literal[
    "full_evacuation_activation",
    "staged_evacuation_and_shelter",
    "targeted_alert_and_preposition",
    "monitor",
]


@dataclass(slots=True, frozen=True)
class EOCSignal:
    incident_id: str
    zone_id: str
    resource_unit_id: str
    hazard_hint: str | None
    observed_population_exposed: int | None
    observed_time_to_impact_minutes: int | None
    vulnerable_population_hint: str | None
    mandatory_evacuation_hint: bool


@dataclass(slots=True, frozen=True)
class EOCDecision:
    incident_id: str
    zone_id: str
    resource_unit_id: str
    route: EOCRoute
    priority: str
    confidence: float
    risk_score: float
    hazard_severity: float
    spread_velocity: float
    weather_volatility: float
    population_exposed: int
    vulnerable_sites_count: int
    shelter_capacity_pct: float
    route_access_score: float
    time_to_impact_minutes: int
    rationale: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class EOCExecutionPolicy:
    execute_actions_in_dry_run: bool = False
    max_parallel_tasks: int = 6
    max_incidents_to_process: int = 20
    full_evacuation_risk_threshold: float = 0.82
    staged_evacuation_risk_threshold: float = 0.62
    targeted_alert_risk_threshold: float = 0.40
    preposition_hazard_threshold: float = 0.48
    major_population_threshold: int = 150_000
    low_route_access_threshold: float = 0.35
    low_shelter_capacity_threshold: float = 0.50
    allow_auto_evacuation: bool = True
    allow_auto_shelter_open: bool = True
    allow_auto_preposition: bool = True
    allow_auto_public_alert: bool = True

    def __post_init__(self) -> None:
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be >= 1")
        if self.max_incidents_to_process < 1:
            raise ValueError("max_incidents_to_process must be >= 1")
        if self.major_population_threshold < 1:
            raise ValueError("major_population_threshold must be >= 1")
        for name, value in (
            ("full_evacuation_risk_threshold", self.full_evacuation_risk_threshold),
            ("staged_evacuation_risk_threshold", self.staged_evacuation_risk_threshold),
            ("targeted_alert_risk_threshold", self.targeted_alert_risk_threshold),
            ("preposition_hazard_threshold", self.preposition_hazard_threshold),
            ("low_route_access_threshold", self.low_route_access_threshold),
            ("low_shelter_capacity_threshold", self.low_shelter_capacity_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(slots=True, frozen=True)
class EOCExecutionStats:
    incidents_total: int
    enrichment_total: int
    enrichment_success: int
    actions_total: int
    actions_success: int
    actions_skipped: int
    actions_failed: int
    full_evacuation_count: int
    staged_evacuation_count: int
    targeted_alert_count: int
    monitor_count: int


@dataclass(slots=True, frozen=True)
class EOCExecutionReport:
    batch_id: str
    pipeline_report: UseCaseExecutionReport
    mode: str
    started_at: datetime
    completed_at: datetime
    signals: tuple[EOCSignal, ...]
    enrichments: tuple[EOCActionResult, ...]
    decisions: tuple[EOCDecision, ...]
    actions: tuple[EOCActionResult, ...]
    stats: EOCExecutionStats
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
class EmergencyOperationsCommander(BaseIntegrationCommanderMixin):
    pipeline: TriProviderPipeline
    hazard_adapter: HazardIntelAdapter
    logistics_adapter: LogisticsCapacityAdapter
    action_adapter: EOCActionAdapter
    execution_policy: EOCExecutionPolicy = field(default_factory=EOCExecutionPolicy)
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
    ) -> EOCExecutionReport:
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
            warnings.append("EOC actions skipped in dry mode by execution policy.")

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
        return EOCExecutionReport(
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
    def extract_signals(text: str, *, max_signals: int = 20) -> list[EOCSignal]:
        incident_matches = list(_INCIDENT_RE.finditer(text))
        zones = [_normalize(m.group(0)) for m in _ZONE_RE.finditer(text)]
        units = [_normalize(m.group(0)) for m in _UNIT_RE.finditer(text)]
        populations = [int(m.group(1)) for m in _PEOPLE_RE.finditer(text)]

        etas_minutes: list[int] = []
        etas_minutes.extend(int(m.group(1)) for m in _ETA_MINUTES_RE.finditer(text))
        etas_minutes.extend(int(m.group(1)) * 60 for m in _ETA_HOURS_RE.finditer(text))

        hazards = [m.group(0).lower() for m in _HAZARD_RE.finditer(text)]
        vulnerable_hits = [m.group(0).lower() for m in _VULNERABLE_RE.finditer(text)]
        has_global_evac_order = bool(_EVAC_ORDER_RE.search(text))

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
            incident_id = f"EOC-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:8].upper()}"
            return [
                EOCSignal(
                    incident_id=incident_id,
                    zone_id=_pick(zones, 0, "ZONE-AUTO-01"),
                    resource_unit_id=_pick(units, 0, "UNIT-AUTO-01"),
                    hazard_hint=_pick(hazards, 0, "") or None,
                    observed_population_exposed=_pick_int(populations, 0),
                    observed_time_to_impact_minutes=_pick_int(etas_minutes, 0),
                    vulnerable_population_hint=_pick(vulnerable_hits, 0, "") or None,
                    mandatory_evacuation_hint=has_global_evac_order,
                )
            ]

        rows: list[EOCSignal] = []
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

            zone_match = _ZONE_RE.search(segment)
            unit_match = _UNIT_RE.search(segment)
            people_match = _PEOPLE_RE.search(segment)
            eta_minutes_match = _ETA_MINUTES_RE.search(segment)
            eta_hours_match = _ETA_HOURS_RE.search(segment)
            hazard_match = _HAZARD_RE.search(segment)
            vulnerable_match = _VULNERABLE_RE.search(segment)
            evac_order_match = _EVAC_ORDER_RE.search(segment)

            eta_minutes: int | None
            if eta_minutes_match:
                eta_minutes = int(eta_minutes_match.group(1))
            elif eta_hours_match:
                eta_minutes = int(eta_hours_match.group(1)) * 60
            else:
                eta_minutes = _pick_int(etas_minutes, segment_index)

            rows.append(
                EOCSignal(
                    incident_id=incident_id,
                    zone_id=_normalize(zone_match.group(0))
                    if zone_match
                    else _pick(zones, segment_index, "ZONE-AUTO-01"),
                    resource_unit_id=_normalize(unit_match.group(0))
                    if unit_match
                    else _pick(units, segment_index, "UNIT-AUTO-01"),
                    hazard_hint=hazard_match.group(0).lower()
                    if hazard_match
                    else (_pick(hazards, segment_index, "") or None),
                    observed_population_exposed=int(people_match.group(1))
                    if people_match
                    else _pick_int(populations, segment_index),
                    observed_time_to_impact_minutes=eta_minutes,
                    vulnerable_population_hint=vulnerable_match.group(0).lower()
                    if vulnerable_match
                    else (_pick(vulnerable_hits, segment_index, "") or None),
                    mandatory_evacuation_hint=bool(evac_order_match) or has_global_evac_order,
                )
            )

        return rows

    @staticmethod
    def _build_batch_id(scenario: str, started_at: datetime) -> str:
        digest = hashlib.sha256(
            f"{started_at.isoformat()}::{scenario}".encode("utf-8")
        ).hexdigest()[:16]
        return f"eoc-{started_at.strftime('%Y%m%d%H%M%S')}-{digest}"

    def _run_enrichment(self, signals: list[EOCSignal]) -> list[EOCActionResult]:
        tasks: list[_ExecutionTask] = []

        zone_ids = _unique_preserve([signal.zone_id for signal in signals])
        for zone_id in zone_ids:
            tasks.append(
                _ExecutionTask(
                    integration="hazard_intel",
                    operation="lookup_zone",
                    target=zone_id,
                    request_payload={"zone_id": zone_id},
                    idempotency_key=None,
                    call=lambda zone_id=zone_id: self.hazard_adapter.lookup_zone(zone_id),
                )
            )
            tasks.append(
                _ExecutionTask(
                    integration="logistics_capacity",
                    operation="lookup_zone",
                    target=zone_id,
                    request_payload={"zone_id": zone_id},
                    idempotency_key=None,
                    call=lambda zone_id=zone_id: self.logistics_adapter.lookup_zone(zone_id),
                )
            )

        return self._execute_integration_tasks(tasks)

    def _build_decisions(
        self,
        signals: list[EOCSignal],
        enrichments: list[EOCActionResult],
    ) -> list[EOCDecision]:
        hazard_data: dict[str, dict[str, Any]] = {}
        logistics_data: dict[str, dict[str, Any]] = {}

        for row in enrichments:
            if not row.success or row.status != "executed":
                continue
            if row.integration == "hazard_intel":
                hazard_data[row.target] = row.response or {}
            elif row.integration == "logistics_capacity":
                logistics_data[row.target] = row.response or {}

        decisions: list[EOCDecision] = []
        for signal in signals:
            hazard = hazard_data.get(signal.zone_id, {})
            logistics = logistics_data.get(signal.zone_id, {})

            hazard_severity = self._as_float(
                hazard,
                keys=("hazard_severity", "threat_index", "severity"),
                default=0.30,
            )
            spread_velocity = self._as_float(
                hazard,
                keys=("spread_velocity", "spread_rate", "propagation"),
                default=0.30,
            )
            weather_volatility = self._as_float(
                hazard,
                keys=("weather_volatility", "weather_risk"),
                default=0.25,
            )
            time_to_impact_minutes = int(
                self._as_float(
                    hazard,
                    keys=("time_to_impact_minutes", "eta_minutes", "impact_eta"),
                    default=float(signal.observed_time_to_impact_minutes or 180),
                    cap_1=False,
                )
            )

            logistics_population = int(
                self._as_float(
                    logistics,
                    keys=("population_exposed",),
                    default=0.0,
                    cap_1=False,
                )
            )
            population_exposed = max(signal.observed_population_exposed or 0, logistics_population)

            vulnerable_sites = int(
                self._as_float(
                    logistics,
                    keys=("vulnerable_sites_count", "critical_sites_count"),
                    default=0.0,
                    cap_1=False,
                )
            )
            if signal.vulnerable_population_hint and vulnerable_sites <= 0:
                vulnerable_sites = 1

            shelter_capacity = self._as_float(
                logistics,
                keys=("shelter_capacity_pct", "shelter_capacity"),
                default=0.72,
            )
            route_access = self._as_float(
                logistics,
                keys=("route_access_score", "road_access_score", "access_score"),
                default=0.70,
            )

            time_pressure = 1.0 - min(1.0, max(0, time_to_impact_minutes) / 240.0)

            risk_score = min(
                1.0,
                hazard_severity * 0.30
                + spread_velocity * 0.16
                + weather_volatility * 0.06
                + (1.0 - route_access) * 0.12
                + (1.0 - shelter_capacity) * 0.12
                + min(1.0, population_exposed / 600_000.0) * 0.10
                + min(1.0, vulnerable_sites / 8.0) * 0.08
                + time_pressure * 0.08
                + (0.08 if signal.mandatory_evacuation_hint else 0.0),
            )

            route: EOCRoute = "monitor"
            rationale: list[str] = []

            if risk_score >= self.execution_policy.full_evacuation_risk_threshold or (
                signal.mandatory_evacuation_hint
                and (
                    hazard_severity >= 0.55
                    or vulnerable_sites >= 2
                    or population_exposed >= self.execution_policy.major_population_threshold
                )
            ):
                route = "full_evacuation_activation"
                rationale.append(
                    "Severe life-safety risk supports immediate full evacuation activation."
                )
            elif risk_score >= self.execution_policy.staged_evacuation_risk_threshold or (
                population_exposed >= self.execution_policy.major_population_threshold
                and (
                    shelter_capacity <= self.execution_policy.low_shelter_capacity_threshold
                    or route_access <= self.execution_policy.low_route_access_threshold
                )
            ):
                route = "staged_evacuation_and_shelter"
                rationale.append(
                    "Elevated risk and logistics constraints require staged evacuation and shelters."
                )
            elif (
                risk_score >= self.execution_policy.targeted_alert_risk_threshold
                or hazard_severity >= self.execution_policy.preposition_hazard_threshold
            ):
                route = "targeted_alert_and_preposition"
                rationale.append(
                    "Moderate risk requires targeted public alerting and resource prepositioning."
                )
            else:
                rationale.append(
                    "Current conditions support active monitoring and readiness posture."
                )

            if not hazard:
                rationale.append("Hazard intelligence enrichment missing; confidence reduced.")
            if not logistics:
                rationale.append("Logistics capacity enrichment missing; confidence reduced.")

            priority = self._priority_for(route)
            confidence = self._confidence_for(
                route=route,
                hazard_enriched=bool(hazard),
                logistics_enriched=bool(logistics),
            )

            decisions.append(
                EOCDecision(
                    incident_id=signal.incident_id,
                    zone_id=signal.zone_id,
                    resource_unit_id=signal.resource_unit_id,
                    route=route,
                    priority=priority,
                    confidence=confidence,
                    risk_score=risk_score,
                    hazard_severity=hazard_severity,
                    spread_velocity=spread_velocity,
                    weather_volatility=weather_volatility,
                    population_exposed=population_exposed,
                    vulnerable_sites_count=vulnerable_sites,
                    shelter_capacity_pct=shelter_capacity,
                    route_access_score=route_access,
                    time_to_impact_minutes=max(0, time_to_impact_minutes),
                    rationale=tuple(rationale),
                )
            )

        decisions.sort(
            key=lambda row: (
                row.route in {"full_evacuation_activation", "staged_evacuation_and_shelter"},
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
        decisions: list[EOCDecision],
        execute_actions: bool,
    ) -> list[EOCActionResult]:
        tasks: list[_ExecutionTask] = []
        skipped: list[EOCActionResult] = []

        for row in decisions:
            reason = "; ".join(row.rationale)
            if not execute_actions:
                skipped.append(
                    EOCActionResult(
                        integration="eoc_actions",
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
                    EOCActionResult(
                        integration="eoc_actions",
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

            if row.route in {"full_evacuation_activation", "staged_evacuation_and_shelter"}:
                if self.execution_policy.allow_auto_shelter_open:
                    shelter_key = f"{batch_id}:shelter:{row.zone_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="eoc_actions",
                            operation="open_shelter",
                            target=row.zone_id,
                            request_payload={"zone_id": row.zone_id, "reason": reason},
                            idempotency_key=shelter_key,
                            call=lambda row=row, reason=reason: self.action_adapter.open_shelter(
                                row.zone_id,
                                reason=reason,
                            ),
                        )
                    )
                else:
                    skipped.append(
                        EOCActionResult(
                            integration="eoc_actions",
                            operation="open_shelter",
                            target=row.zone_id,
                            success=True,
                            latency_ms=0,
                            request={"zone_id": row.zone_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto shelter activation disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_preposition:
                    preposition_key = f"{batch_id}:preposition:{row.resource_unit_id}:{row.zone_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="eoc_actions",
                            operation="preposition_resources",
                            target=row.resource_unit_id,
                            request_payload={
                                "resource_unit_id": row.resource_unit_id,
                                "zone_id": row.zone_id,
                                "reason": reason,
                            },
                            idempotency_key=preposition_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.preposition_resources(
                                    row.resource_unit_id,
                                    zone_id=row.zone_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        EOCActionResult(
                            integration="eoc_actions",
                            operation="preposition_resources",
                            target=row.resource_unit_id,
                            success=True,
                            latency_ms=0,
                            request={
                                "resource_unit_id": row.resource_unit_id,
                                "zone_id": row.zone_id,
                            },
                            status="skipped",
                            attempts=0,
                            notes=("auto prepositioning disabled by policy",),
                        )
                    )

                if row.route == "full_evacuation_activation":
                    if self.execution_policy.allow_auto_evacuation:
                        evac_key = f"{batch_id}:evacuation:{row.zone_id}"
                        tasks.append(
                            _ExecutionTask(
                                integration="eoc_actions",
                                operation="activate_evacuation",
                                target=row.zone_id,
                                request_payload={"zone_id": row.zone_id, "reason": reason},
                                idempotency_key=evac_key,
                                call=lambda row=row, reason=reason: (
                                    self.action_adapter.activate_evacuation(
                                        row.zone_id,
                                        reason=reason,
                                    )
                                ),
                            )
                        )
                    else:
                        skipped.append(
                            EOCActionResult(
                                integration="eoc_actions",
                                operation="activate_evacuation",
                                target=row.zone_id,
                                success=True,
                                latency_ms=0,
                                request={"zone_id": row.zone_id},
                                status="skipped",
                                attempts=0,
                                notes=("auto evacuation activation disabled by policy",),
                            )
                        )

                if self.execution_policy.allow_auto_public_alert:
                    alert_key = f"{batch_id}:alert:{row.incident_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="eoc_actions",
                            operation="issue_public_alert",
                            target=row.incident_id,
                            request_payload={"incident_id": row.incident_id, "reason": reason},
                            idempotency_key=alert_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.issue_public_alert(
                                    row.incident_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        EOCActionResult(
                            integration="eoc_actions",
                            operation="issue_public_alert",
                            target=row.incident_id,
                            success=True,
                            latency_ms=0,
                            request={"incident_id": row.incident_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto public alerting disabled by policy",),
                        )
                    )
                continue

            if row.route == "targeted_alert_and_preposition":
                if self.execution_policy.allow_auto_preposition:
                    preposition_key = f"{batch_id}:preposition:{row.resource_unit_id}:{row.zone_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="eoc_actions",
                            operation="preposition_resources",
                            target=row.resource_unit_id,
                            request_payload={
                                "resource_unit_id": row.resource_unit_id,
                                "zone_id": row.zone_id,
                                "reason": reason,
                            },
                            idempotency_key=preposition_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.preposition_resources(
                                    row.resource_unit_id,
                                    zone_id=row.zone_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        EOCActionResult(
                            integration="eoc_actions",
                            operation="preposition_resources",
                            target=row.resource_unit_id,
                            success=True,
                            latency_ms=0,
                            request={
                                "resource_unit_id": row.resource_unit_id,
                                "zone_id": row.zone_id,
                            },
                            status="skipped",
                            attempts=0,
                            notes=("auto prepositioning disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_public_alert:
                    alert_key = f"{batch_id}:alert:{row.incident_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="eoc_actions",
                            operation="issue_public_alert",
                            target=row.incident_id,
                            request_payload={"incident_id": row.incident_id, "reason": reason},
                            idempotency_key=alert_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.issue_public_alert(
                                    row.incident_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        EOCActionResult(
                            integration="eoc_actions",
                            operation="issue_public_alert",
                            target=row.incident_id,
                            success=True,
                            latency_ms=0,
                            request={"incident_id": row.incident_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto public alerting disabled by policy",),
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
    def _priority_for(route: EOCRoute) -> str:
        if route == "full_evacuation_activation":
            return "urgent"
        if route == "staged_evacuation_and_shelter":
            return "high"
        if route == "targeted_alert_and_preposition":
            return "normal"
        return "low"

    @staticmethod
    def _confidence_for(
        *,
        route: EOCRoute,
        hazard_enriched: bool,
        logistics_enriched: bool,
    ) -> float:
        base = {
            "full_evacuation_activation": 0.9,
            "staged_evacuation_and_shelter": 0.84,
            "targeted_alert_and_preposition": 0.78,
            "monitor": 0.68,
        }[route]
        if not hazard_enriched:
            base -= 0.15
        if not logistics_enriched:
            base -= 0.15
        return round(min(0.99, max(0.05, base)), 3)

    @staticmethod
    def _build_stats(
        *,
        signals: list[EOCSignal],
        enrichments: list[EOCActionResult],
        decisions: list[EOCDecision],
        actions: list[EOCActionResult],
    ) -> EOCExecutionStats:
        route_counts: dict[EOCRoute, int] = defaultdict(int)
        for row in decisions:
            route_counts[row.route] += 1

        actions_success = sum(1 for row in actions if row.success and row.status == "executed")
        actions_skipped = sum(1 for row in actions if row.status == "skipped")
        actions_failed = sum(1 for row in actions if not row.success)

        return EOCExecutionStats(
            incidents_total=len(signals),
            enrichment_total=len(enrichments),
            enrichment_success=sum(1 for row in enrichments if row.success),
            actions_total=len(actions),
            actions_success=actions_success,
            actions_skipped=actions_skipped,
            actions_failed=actions_failed,
            full_evacuation_count=route_counts["full_evacuation_activation"],
            staged_evacuation_count=route_counts["staged_evacuation_and_shelter"],
            targeted_alert_count=route_counts["targeted_alert_and_preposition"],
            monitor_count=route_counts["monitor"],
        )

    @staticmethod
    def _recommendations(
        *,
        pipeline_report: UseCaseExecutionReport,
        stats: EOCExecutionStats,
        decisions: list[EOCDecision],
        errors: list[str],
    ) -> list[str]:
        recs: list[str] = [
            (
                "Decision mix: "
                f"full_evacuation={stats.full_evacuation_count}, "
                f"staged_evacuation={stats.staged_evacuation_count}, "
                f"targeted_alert={stats.targeted_alert_count}, "
                f"monitor={stats.monitor_count}."
            ),
            (
                f"Enrichment success {stats.enrichment_success}/{stats.enrichment_total}; "
                f"actions success={stats.actions_success}, skipped={stats.actions_skipped}, failed={stats.actions_failed}."
            ),
            "For full-evacuation cases, confirm transportation corridors and special-needs extraction coverage.",
            "For staged-evacuation cases, sequence neighborhood waves by vulnerability and route congestion.",
            "For targeted-alert cases, preposition field units near likely escalation boundaries.",
        ]

        if pipeline_report.ranked_actions:
            recs.append(f"Primary tri-provider action: {pipeline_report.ranked_actions[0].action}")

        if errors:
            recs.append(
                "At least one integration failed; escalate to human incident command for manual coordination."
            )

        top = decisions[:3]
        if top:
            recs.append(
                "Top incidents: "
                + ", ".join(
                    f"{row.incident_id}:{row.route}:{row.risk_score:.2f}:{row.population_exposed}"
                    for row in top
                )
                + "."
            )

        return recs
