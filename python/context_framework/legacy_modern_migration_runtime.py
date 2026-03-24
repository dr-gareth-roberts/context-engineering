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
LegacyMigrationActionResult = IntegrationActionResult

_ID_SUFFIX_RE = r"(?:[-_][A-Za-z0-9]+|[0-9]{2,}[A-Za-z0-9]*)(?:[-_][A-Za-z0-9]+)*"
_SYSTEM_RE = re.compile(
    rf"\b(?:APP|SERVICE|SYSTEM|LEGACY|WORKLOAD|PLATFORM){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_SERVICE_RE = re.compile(
    rf"\b(?:MODULE|DOMAIN|COMPONENT|API|JOB){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_OWNER_RE = re.compile(
    rf"\b(?:TEAM|OWNER|SQUAD|GROUP){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_AGE_YEARS_RE = re.compile(r"\b(\d{1,2})\s*years?\b", re.IGNORECASE)
_OUTAGE_HOURS_RE = re.compile(r"\b(\d{1,4})\s*hours?\b", re.IGNORECASE)
_DEPENDENCY_COUNT_RE = re.compile(
    r"\b(\d{1,4})\s*(?:dependencies|integrations|services|connectors?)\b",
    re.IGNORECASE,
)

_RISK_HINT_KEYWORDS = (
    "mainframe",
    "eol runtime",
    "unsupported os",
    "manual release",
    "shared database",
    "hard-coded secret",
    "single point of failure",
    "vendor lock-in",
)
_RISK_HINT_RE = re.compile(
    "|".join(re.escape(keyword) for keyword in _RISK_HINT_KEYWORDS), re.IGNORECASE
)
_UNSUPPORTED_RE = re.compile(
    r"(?:eol|end of support|unsupported|out[- ]of[- ]support)",
    re.IGNORECASE,
)
_MISSION_CRITICAL_RE = re.compile(
    r"(?:mission[- ]critical|revenue[- ]critical|customer[- ]critical|safety[- ]critical)",
    re.IGNORECASE,
)


def _normalize(value: str) -> str:
    return value.strip().replace("_", "-").upper()


class SystemInventoryAdapter(Protocol):
    def lookup_system(self, system_id: str) -> dict[str, Any]: ...


class DependencyGraphAdapter(Protocol):
    def lookup_system(self, system_id: str) -> dict[str, Any]: ...


class MigrationActionAdapter(Protocol):
    def open_modernization_program(self, system_id: str, *, reason: str) -> dict[str, Any]: ...

    def create_migration_wave(self, system_id: str, *, reason: str) -> dict[str, Any]: ...

    def schedule_parallel_run(
        self,
        system_id: str,
        *,
        target_platform: str,
        reason: str,
    ) -> dict[str, Any]: ...

    def register_rollback_plan(self, system_id: str, *, reason: str) -> dict[str, Any]: ...

    def assign_transformation_owner(self, owner_id: str, *, reason: str) -> dict[str, Any]: ...


class NoOpSystemInventoryAdapter:
    def lookup_system(self, system_id: str) -> dict[str, Any]:
        return {
            "system_id": system_id,
            "tech_debt_score": 0.36,
            "modernization_blocker_score": 0.33,
            "criticality": 0.48,
            "change_failure_rate": 0.30,
            "source": "noop",
        }


class NoOpDependencyGraphAdapter:
    def lookup_system(self, system_id: str) -> dict[str, Any]:
        return {
            "system_id": system_id,
            "dependency_count": 24,
            "coupling_score": 0.40,
            "blast_radius": 0.42,
            "target_platform": "PLATFORM-K8S-01",
            "parallel_run_readiness": 0.58,
            "source": "noop",
        }


class NoOpMigrationActionAdapter:
    def open_modernization_program(self, system_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "system_id": system_id,
            "action": "open_modernization_program",
            "reason": reason,
            "status": "noop",
        }

    def create_migration_wave(self, system_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "system_id": system_id,
            "action": "create_migration_wave",
            "reason": reason,
            "status": "noop",
        }

    def schedule_parallel_run(
        self,
        system_id: str,
        *,
        target_platform: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "system_id": system_id,
            "action": "schedule_parallel_run",
            "target_platform": target_platform,
            "reason": reason,
            "status": "noop",
        }

    def register_rollback_plan(self, system_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "system_id": system_id,
            "action": "register_rollback_plan",
            "reason": reason,
            "status": "noop",
        }

    def assign_transformation_owner(self, owner_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "owner_id": owner_id,
            "action": "assign_transformation_owner",
            "reason": reason,
            "status": "noop",
        }


@dataclass(slots=True)
class InMemorySystemInventoryAdapter:
    systems: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_system(self, system_id: str) -> dict[str, Any]:
        system = _normalize(system_id)
        payload = self.systems.get(system, {})
        tech_debt = float(payload.get("tech_debt_score", 0.38))
        blocker = float(payload.get("modernization_blocker_score", 0.35))
        criticality = float(payload.get("criticality", 0.50))
        failure_rate = float(payload.get("change_failure_rate", 0.32))
        return {
            "system_id": system,
            "tech_debt_score": max(0.0, min(1.0, tech_debt)),
            "modernization_blocker_score": max(0.0, min(1.0, blocker)),
            "criticality": max(0.0, min(1.0, criticality)),
            "change_failure_rate": max(0.0, min(1.0, failure_rate)),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryDependencyGraphAdapter:
    systems: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_system(self, system_id: str) -> dict[str, Any]:
        system = _normalize(system_id)
        payload = self.systems.get(system, {})
        dependency_count = int(payload.get("dependency_count", 28))
        coupling = float(payload.get("coupling_score", 0.42))
        blast_radius = float(payload.get("blast_radius", 0.44))
        target_platform = str(payload.get("target_platform", "PLATFORM-K8S-01"))
        parallel_readiness = float(payload.get("parallel_run_readiness", 0.60))
        return {
            "system_id": system,
            "dependency_count": max(0, dependency_count),
            "coupling_score": max(0.0, min(1.0, coupling)),
            "blast_radius": max(0.0, min(1.0, blast_radius)),
            "target_platform": target_platform,
            "parallel_run_readiness": max(0.0, min(1.0, parallel_readiness)),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryMigrationActionAdapter:
    modernization_programs: set[str] = field(default_factory=set)
    migration_waves: set[str] = field(default_factory=set)
    parallel_runs: set[str] = field(default_factory=set)
    rollback_plans: set[str] = field(default_factory=set)
    owner_assignments: set[str] = field(default_factory=set)

    def open_modernization_program(self, system_id: str, *, reason: str) -> dict[str, Any]:
        system = _normalize(system_id)
        self.modernization_programs.add(system)
        return {
            "system_id": system,
            "action": "open_modernization_program",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def create_migration_wave(self, system_id: str, *, reason: str) -> dict[str, Any]:
        system = _normalize(system_id)
        self.migration_waves.add(system)
        return {
            "system_id": system,
            "action": "create_migration_wave",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def schedule_parallel_run(
        self,
        system_id: str,
        *,
        target_platform: str,
        reason: str,
    ) -> dict[str, Any]:
        system = _normalize(system_id)
        self.parallel_runs.add(system)
        return {
            "system_id": system,
            "action": "schedule_parallel_run",
            "target_platform": target_platform,
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def register_rollback_plan(self, system_id: str, *, reason: str) -> dict[str, Any]:
        system = _normalize(system_id)
        self.rollback_plans.add(system)
        return {
            "system_id": system,
            "action": "register_rollback_plan",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def assign_transformation_owner(self, owner_id: str, *, reason: str) -> dict[str, Any]:
        owner = _normalize(owner_id)
        self.owner_assignments.add(owner)
        return {
            "owner_id": owner,
            "action": "assign_transformation_owner",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }


_HTTPJSONAdapterBase = HTTPJSONAdapterBase


@dataclass(slots=True)
class HTTPSystemInventoryAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/migration/system_inventory"

    def lookup_system(self, system_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"system_id": system_id})


@dataclass(slots=True)
class HTTPDependencyGraphAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/migration/dependency_graph"

    def lookup_system(self, system_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"system_id": system_id})


@dataclass(slots=True)
class HTTPMigrationActionAdapter(HTTPJSONAdapterBase):
    program_path: str = "/migration/open_program"
    wave_path: str = "/migration/create_wave"
    parallel_run_path: str = "/migration/schedule_parallel_run"
    rollback_path: str = "/migration/register_rollback"
    owner_assignment_path: str = "/migration/assign_owner"

    def open_modernization_program(self, system_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.program_path, {"system_id": system_id, "reason": reason})

    def create_migration_wave(self, system_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.wave_path, {"system_id": system_id, "reason": reason})

    def schedule_parallel_run(
        self,
        system_id: str,
        *,
        target_platform: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._post(
            self.parallel_run_path,
            {
                "system_id": system_id,
                "target_platform": target_platform,
                "reason": reason,
            },
        )

    def register_rollback_plan(self, system_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.rollback_path, {"system_id": system_id, "reason": reason})

    def assign_transformation_owner(self, owner_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.owner_assignment_path, {"owner_id": owner_id, "reason": reason})


def build_system_inventory_adapter_from_env() -> SystemInventoryAdapter:
    base = os.getenv("MIGRATION_SYSTEM_BASE_URL")
    token = os.getenv("MIGRATION_SYSTEM_API_KEY")
    if base and token:
        path = os.getenv("MIGRATION_SYSTEM_LOOKUP_PATH", "/migration/system_inventory")
        return HTTPSystemInventoryAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpSystemInventoryAdapter()


def build_dependency_graph_adapter_from_env() -> DependencyGraphAdapter:
    base = os.getenv("MIGRATION_DEPGRAPH_BASE_URL")
    token = os.getenv("MIGRATION_DEPGRAPH_API_KEY")
    if base and token:
        path = os.getenv("MIGRATION_DEPGRAPH_LOOKUP_PATH", "/migration/dependency_graph")
        return HTTPDependencyGraphAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpDependencyGraphAdapter()


def build_migration_action_adapter_from_env() -> MigrationActionAdapter:
    base = os.getenv("MIGRATION_ACTION_BASE_URL")
    token = os.getenv("MIGRATION_ACTION_API_KEY")
    if base and token:
        return HTTPMigrationActionAdapter(
            base_url=base,
            api_key=token,
            program_path=os.getenv("MIGRATION_ACTION_PROGRAM_PATH", "/migration/open_program"),
            wave_path=os.getenv("MIGRATION_ACTION_WAVE_PATH", "/migration/create_wave"),
            parallel_run_path=os.getenv(
                "MIGRATION_ACTION_PARALLEL_RUN_PATH",
                "/migration/schedule_parallel_run",
            ),
            rollback_path=os.getenv(
                "MIGRATION_ACTION_ROLLBACK_PATH",
                "/migration/register_rollback",
            ),
            owner_assignment_path=os.getenv(
                "MIGRATION_ACTION_OWNER_ASSIGNMENT_PATH",
                "/migration/assign_owner",
            ),
        )
    return NoOpMigrationActionAdapter()


LegacyMigrationRoute = Literal[
    "immediate_replatform_program",
    "phased_strangler_with_parallel_run",
    "targeted_refactor_wave",
    "monitor",
]


@dataclass(slots=True, frozen=True)
class LegacyMigrationSignal:
    system_id: str
    service_id: str
    owner_id: str
    risk_hint: str | None
    observed_age_years: int | None
    observed_dependency_count: int | None
    observed_recent_outage_hours: int | None
    unsupported_runtime_indicator: bool
    mission_critical_indicator: bool


@dataclass(slots=True, frozen=True)
class LegacyMigrationDecision:
    system_id: str
    service_id: str
    owner_id: str
    route: LegacyMigrationRoute
    priority: str
    confidence: float
    risk_score: float
    tech_debt_score: float
    blocker_score: float
    criticality: float
    change_failure_rate: float
    coupling_score: float
    blast_radius: float
    dependency_count: int
    age_years: int
    recent_outage_hours: int
    target_platform: str
    parallel_run_readiness: float
    rationale: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class LegacyMigrationExecutionPolicy:
    execute_actions_in_dry_run: bool = False
    max_parallel_tasks: int = 6
    max_systems_to_process: int = 20
    immediate_risk_threshold: float = 0.84
    phased_risk_threshold: float = 0.58
    targeted_risk_threshold: float = 0.36
    high_dependency_threshold: int = 60
    long_age_years_threshold: int = 8
    allow_auto_program_open: bool = True
    allow_auto_wave: bool = True
    allow_auto_parallel_run: bool = True
    allow_auto_rollback_plan: bool = True
    allow_auto_owner_assignment: bool = True

    def __post_init__(self) -> None:
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be >= 1")
        if self.max_systems_to_process < 1:
            raise ValueError("max_systems_to_process must be >= 1")
        if self.high_dependency_threshold < 1:
            raise ValueError("high_dependency_threshold must be >= 1")
        if self.long_age_years_threshold < 1:
            raise ValueError("long_age_years_threshold must be >= 1")
        for name, value in (
            ("immediate_risk_threshold", self.immediate_risk_threshold),
            ("phased_risk_threshold", self.phased_risk_threshold),
            ("targeted_risk_threshold", self.targeted_risk_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(slots=True, frozen=True)
class LegacyMigrationExecutionStats:
    systems_total: int
    enrichment_total: int
    enrichment_success: int
    actions_total: int
    actions_success: int
    actions_skipped: int
    actions_failed: int
    immediate_count: int
    phased_count: int
    targeted_count: int
    monitor_count: int


@dataclass(slots=True, frozen=True)
class LegacyMigrationExecutionReport:
    batch_id: str
    pipeline_report: UseCaseExecutionReport
    mode: str
    started_at: datetime
    completed_at: datetime
    signals: tuple[LegacyMigrationSignal, ...]
    enrichments: tuple[LegacyMigrationActionResult, ...]
    decisions: tuple[LegacyMigrationDecision, ...]
    actions: tuple[LegacyMigrationActionResult, ...]
    stats: LegacyMigrationExecutionStats
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
class LegacyModernMigrationCommander(BaseIntegrationCommanderMixin):
    pipeline: TriProviderPipeline
    system_inventory_adapter: SystemInventoryAdapter
    dependency_graph_adapter: DependencyGraphAdapter
    action_adapter: MigrationActionAdapter
    execution_policy: LegacyMigrationExecutionPolicy = field(
        default_factory=LegacyMigrationExecutionPolicy
    )
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
    ) -> LegacyMigrationExecutionReport:
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
            max_signals=self.execution_policy.max_systems_to_process,
        )

        enrichments = self._run_enrichment(signals)
        decisions = self._build_decisions(signals, enrichments)

        execute_actions = True
        if mode == "dry" and not self.execution_policy.execute_actions_in_dry_run:
            execute_actions = False
            warnings.append("Legacy migration actions skipped in dry mode by execution policy.")

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
        return LegacyMigrationExecutionReport(
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
    def extract_signals(text: str, *, max_signals: int = 20) -> list[LegacyMigrationSignal]:
        system_matches = list(_SYSTEM_RE.finditer(text))
        services = [_normalize(m.group(0)) for m in _SERVICE_RE.finditer(text)]
        owners = [_normalize(m.group(0)) for m in _OWNER_RE.finditer(text)]
        age_values = [int(m.group(1)) for m in _AGE_YEARS_RE.finditer(text)]
        outage_values = [int(m.group(1)) for m in _OUTAGE_HOURS_RE.finditer(text)]
        dependency_values = [int(m.group(1)) for m in _DEPENDENCY_COUNT_RE.finditer(text)]
        risk_hints = [m.group(0).lower() for m in _RISK_HINT_RE.finditer(text)]
        has_unsupported = bool(_UNSUPPORTED_RE.search(text))
        has_mission_critical = bool(_MISSION_CRITICAL_RE.search(text))

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

        if not system_matches:
            system_id = f"SYSTEM-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:8].upper()}"
            return [
                LegacyMigrationSignal(
                    system_id=system_id,
                    service_id=_pick(services, 0, "SERVICE-AUTO-01"),
                    owner_id=_pick(owners, 0, "TEAM-AUTO-01"),
                    risk_hint=_pick(risk_hints, 0, "") or None,
                    observed_age_years=_pick_int(age_values, 0),
                    observed_dependency_count=_pick_int(dependency_values, 0),
                    observed_recent_outage_hours=_pick_int(outage_values, 0),
                    unsupported_runtime_indicator=has_unsupported,
                    mission_critical_indicator=has_mission_critical,
                )
            ]

        rows: list[LegacyMigrationSignal] = []
        seen_systems: set[str] = set()
        for idx, match in enumerate(system_matches):
            if len(rows) >= max_signals:
                break

            system_id = _normalize(match.group(0))
            key = system_id.lower()
            if key in seen_systems:
                continue
            seen_systems.add(key)

            segment_index = len(rows)
            start = match.start()
            end = system_matches[idx + 1].start() if idx + 1 < len(system_matches) else len(text)
            segment = text[start:end]

            service_match = _SERVICE_RE.search(segment)
            owner_match = _OWNER_RE.search(segment)
            age_match = _AGE_YEARS_RE.search(segment)
            outage_match = _OUTAGE_HOURS_RE.search(segment)
            dependency_match = _DEPENDENCY_COUNT_RE.search(segment)
            risk_hint_match = _RISK_HINT_RE.search(segment)
            unsupported_match = _UNSUPPORTED_RE.search(segment)
            mission_critical_match = _MISSION_CRITICAL_RE.search(segment)

            rows.append(
                LegacyMigrationSignal(
                    system_id=system_id,
                    service_id=_normalize(service_match.group(0))
                    if service_match
                    else _pick(services, segment_index, "SERVICE-AUTO-01"),
                    owner_id=_normalize(owner_match.group(0))
                    if owner_match
                    else _pick(owners, segment_index, "TEAM-AUTO-01"),
                    risk_hint=risk_hint_match.group(0).lower()
                    if risk_hint_match
                    else (_pick(risk_hints, segment_index, "") or None),
                    observed_age_years=int(age_match.group(1))
                    if age_match
                    else _pick_int(age_values, segment_index),
                    observed_dependency_count=int(dependency_match.group(1))
                    if dependency_match
                    else _pick_int(dependency_values, segment_index),
                    observed_recent_outage_hours=int(outage_match.group(1))
                    if outage_match
                    else _pick_int(outage_values, segment_index),
                    unsupported_runtime_indicator=bool(unsupported_match) or has_unsupported,
                    mission_critical_indicator=bool(mission_critical_match) or has_mission_critical,
                )
            )

        return rows

    @staticmethod
    def _build_batch_id(scenario: str, started_at: datetime) -> str:
        digest = hashlib.sha256(
            f"{started_at.isoformat()}::{scenario}".encode("utf-8")
        ).hexdigest()[:16]
        return f"migration-{started_at.strftime('%Y%m%d%H%M%S')}-{digest}"

    def _run_enrichment(
        self, signals: list[LegacyMigrationSignal]
    ) -> list[LegacyMigrationActionResult]:
        tasks: list[_ExecutionTask] = []

        system_ids = _unique_preserve([signal.system_id for signal in signals])
        for system_id in system_ids:
            tasks.append(
                _ExecutionTask(
                    integration="system_inventory",
                    operation="lookup_system",
                    target=system_id,
                    request_payload={"system_id": system_id},
                    idempotency_key=None,
                    call=lambda system_id=system_id: self.system_inventory_adapter.lookup_system(
                        system_id
                    ),
                )
            )
            tasks.append(
                _ExecutionTask(
                    integration="dependency_graph",
                    operation="lookup_system",
                    target=system_id,
                    request_payload={"system_id": system_id},
                    idempotency_key=None,
                    call=lambda system_id=system_id: self.dependency_graph_adapter.lookup_system(
                        system_id
                    ),
                )
            )
        return self._execute_integration_tasks(tasks)

    def _build_decisions(
        self,
        signals: list[LegacyMigrationSignal],
        enrichments: list[LegacyMigrationActionResult],
    ) -> list[LegacyMigrationDecision]:
        system_data: dict[str, dict[str, Any]] = {}
        dependency_data: dict[str, dict[str, Any]] = {}

        for row in enrichments:
            if not row.success or row.status != "executed":
                continue
            if row.integration == "system_inventory":
                system_data[row.target] = row.response or {}
            elif row.integration == "dependency_graph":
                dependency_data[row.target] = row.response or {}

        decisions: list[LegacyMigrationDecision] = []
        for signal in signals:
            sys_row = system_data.get(signal.system_id, {})
            dep_row = dependency_data.get(signal.system_id, {})

            tech_debt = self._as_float(sys_row, keys=("tech_debt_score", "tech_debt"), default=0.38)
            blocker = self._as_float(
                sys_row,
                keys=("modernization_blocker_score", "blocker_score"),
                default=0.35,
            )
            criticality = self._as_float(
                sys_row, keys=("criticality", "business_criticality"), default=0.50
            )
            change_failure = self._as_float(
                sys_row,
                keys=("change_failure_rate", "deployment_failure_rate"),
                default=0.32,
            )

            dependency_count = self._as_int(
                dep_row, keys=("dependency_count", "integration_count"), default=30
            )
            coupling = self._as_float(dep_row, keys=("coupling_score", "coupling"), default=0.42)
            blast_radius = self._as_float(
                dep_row, keys=("blast_radius", "impact_radius"), default=0.44
            )
            parallel_readiness = self._as_float(
                dep_row,
                keys=("parallel_run_readiness", "parallel_readiness"),
                default=0.60,
            )
            target_platform = str(dep_row.get("target_platform", "PLATFORM-K8S-01"))

            age_years = signal.observed_age_years or 6
            outage_hours = signal.observed_recent_outage_hours or 0
            dependency_count = max(dependency_count, signal.observed_dependency_count or 0)

            dependency_risk = min(1.0, dependency_count / 120.0)
            age_risk = min(1.0, age_years / 15.0)
            outage_risk = min(1.0, outage_hours / 72.0)
            hint_risk = 0.0
            if signal.risk_hint in {
                "mainframe",
                "eol runtime",
                "shared database",
                "single point of failure",
            }:
                hint_risk = 0.06

            risk_score = min(
                1.0,
                tech_debt * 0.22
                + blocker * 0.14
                + criticality * 0.15
                + change_failure * 0.10
                + coupling * 0.12
                + blast_radius * 0.08
                + dependency_risk * 0.10
                + age_risk * 0.04
                + outage_risk * 0.03
                + (1.0 - parallel_readiness) * 0.04
                + hint_risk
                + (0.10 if signal.unsupported_runtime_indicator else 0.0)
                + (0.08 if signal.mission_critical_indicator else 0.0),
            )

            route: LegacyMigrationRoute = "monitor"
            rationale: list[str] = []
            if (
                risk_score >= self.execution_policy.immediate_risk_threshold
                or signal.unsupported_runtime_indicator
                or (criticality >= 0.85 and outage_hours >= 24)
            ):
                route = "immediate_replatform_program"
                rationale.append(
                    "Risk profile requires immediate modernization program and controlled replatforming."
                )
            elif (
                risk_score >= self.execution_policy.phased_risk_threshold
                or dependency_count >= self.execution_policy.high_dependency_threshold
                or age_years >= self.execution_policy.long_age_years_threshold
            ):
                route = "phased_strangler_with_parallel_run"
                rationale.append(
                    "Risk profile supports phased strangler migration with parallel-run safety checks."
                )
            elif risk_score >= self.execution_policy.targeted_risk_threshold:
                route = "targeted_refactor_wave"
                rationale.append(
                    "Risk profile supports targeted refactor and migration wave execution."
                )
            else:
                rationale.append(
                    "Current modernization risk supports monitoring and incremental hardening."
                )

            if not sys_row:
                rationale.append("System-inventory enrichment missing; confidence reduced.")
            if not dep_row:
                rationale.append("Dependency-graph enrichment missing; confidence reduced.")

            priority = self._priority_for(route)
            confidence = self._confidence_for(
                route=route,
                system_enriched=bool(sys_row),
                dependency_enriched=bool(dep_row),
            )

            decisions.append(
                LegacyMigrationDecision(
                    system_id=signal.system_id,
                    service_id=signal.service_id,
                    owner_id=signal.owner_id,
                    route=route,
                    priority=priority,
                    confidence=confidence,
                    risk_score=risk_score,
                    tech_debt_score=tech_debt,
                    blocker_score=blocker,
                    criticality=criticality,
                    change_failure_rate=change_failure,
                    coupling_score=coupling,
                    blast_radius=blast_radius,
                    dependency_count=max(0, dependency_count),
                    age_years=max(0, age_years),
                    recent_outage_hours=max(0, outage_hours),
                    target_platform=target_platform,
                    parallel_run_readiness=parallel_readiness,
                    rationale=tuple(rationale),
                )
            )

        decisions.sort(
            key=lambda row: (
                row.route in {"immediate_replatform_program", "phased_strangler_with_parallel_run"},
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
        decisions: list[LegacyMigrationDecision],
        execute_actions: bool,
    ) -> list[LegacyMigrationActionResult]:
        tasks: list[_ExecutionTask] = []
        skipped: list[LegacyMigrationActionResult] = []

        for row in decisions:
            reason = "; ".join(row.rationale)
            if not execute_actions:
                skipped.append(
                    LegacyMigrationActionResult(
                        integration="migration_actions",
                        operation=row.route,
                        target=row.system_id,
                        success=True,
                        latency_ms=0,
                        request={"system_id": row.system_id, "route": row.route},
                        status="skipped",
                        attempts=0,
                        notes=("action execution disabled by runtime policy",),
                    )
                )
                continue

            if row.route == "monitor":
                skipped.append(
                    LegacyMigrationActionResult(
                        integration="migration_actions",
                        operation="monitor",
                        target=row.system_id,
                        success=True,
                        latency_ms=0,
                        request={"system_id": row.system_id, "route": "monitor"},
                        status="skipped",
                        attempts=0,
                        notes=("monitor route requires no external action call",),
                    )
                )
                continue

            if row.route in {"immediate_replatform_program", "phased_strangler_with_parallel_run"}:
                if self.execution_policy.allow_auto_program_open:
                    key = f"{batch_id}:program:{row.system_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="migration_actions",
                            operation="open_modernization_program",
                            target=row.system_id,
                            request_payload={"system_id": row.system_id, "reason": reason},
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.open_modernization_program(
                                    row.system_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        LegacyMigrationActionResult(
                            integration="migration_actions",
                            operation="open_modernization_program",
                            target=row.system_id,
                            success=True,
                            latency_ms=0,
                            request={"system_id": row.system_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto program-open disabled by policy",),
                        )
                    )

            if row.route in {
                "immediate_replatform_program",
                "phased_strangler_with_parallel_run",
                "targeted_refactor_wave",
            }:
                if self.execution_policy.allow_auto_wave:
                    key = f"{batch_id}:wave:{row.system_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="migration_actions",
                            operation="create_migration_wave",
                            target=row.system_id,
                            request_payload={"system_id": row.system_id, "reason": reason},
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.create_migration_wave(
                                    row.system_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        LegacyMigrationActionResult(
                            integration="migration_actions",
                            operation="create_migration_wave",
                            target=row.system_id,
                            success=True,
                            latency_ms=0,
                            request={"system_id": row.system_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto wave creation disabled by policy",),
                        )
                    )

            if row.route in {"immediate_replatform_program", "phased_strangler_with_parallel_run"}:
                if self.execution_policy.allow_auto_parallel_run:
                    key = f"{batch_id}:parallel:{row.system_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="migration_actions",
                            operation="schedule_parallel_run",
                            target=row.system_id,
                            request_payload={
                                "system_id": row.system_id,
                                "target_platform": row.target_platform,
                                "reason": reason,
                            },
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.schedule_parallel_run(
                                    row.system_id,
                                    target_platform=row.target_platform,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        LegacyMigrationActionResult(
                            integration="migration_actions",
                            operation="schedule_parallel_run",
                            target=row.system_id,
                            success=True,
                            latency_ms=0,
                            request={
                                "system_id": row.system_id,
                                "target_platform": row.target_platform,
                            },
                            status="skipped",
                            attempts=0,
                            notes=("auto parallel-run scheduling disabled by policy",),
                        )
                    )

            if row.route in {"immediate_replatform_program", "targeted_refactor_wave"}:
                if self.execution_policy.allow_auto_rollback_plan:
                    key = f"{batch_id}:rollback:{row.system_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="migration_actions",
                            operation="register_rollback_plan",
                            target=row.system_id,
                            request_payload={"system_id": row.system_id, "reason": reason},
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.register_rollback_plan(
                                    row.system_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        LegacyMigrationActionResult(
                            integration="migration_actions",
                            operation="register_rollback_plan",
                            target=row.system_id,
                            success=True,
                            latency_ms=0,
                            request={"system_id": row.system_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto rollback-plan registration disabled by policy",),
                        )
                    )

            if row.route in {
                "immediate_replatform_program",
                "phased_strangler_with_parallel_run",
                "targeted_refactor_wave",
            }:
                if self.execution_policy.allow_auto_owner_assignment:
                    key = f"{batch_id}:owner:{row.owner_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="migration_actions",
                            operation="assign_transformation_owner",
                            target=row.owner_id,
                            request_payload={"owner_id": row.owner_id, "reason": reason},
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.assign_transformation_owner(
                                    row.owner_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        LegacyMigrationActionResult(
                            integration="migration_actions",
                            operation="assign_transformation_owner",
                            target=row.owner_id,
                            success=True,
                            latency_ms=0,
                            request={"owner_id": row.owner_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto owner assignment disabled by policy",),
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
    def _priority_for(route: LegacyMigrationRoute) -> str:
        if route == "immediate_replatform_program":
            return "urgent"
        if route == "phased_strangler_with_parallel_run":
            return "high"
        if route == "targeted_refactor_wave":
            return "normal"
        return "low"

    @staticmethod
    def _confidence_for(
        *,
        route: LegacyMigrationRoute,
        system_enriched: bool,
        dependency_enriched: bool,
    ) -> float:
        base = {
            "immediate_replatform_program": 0.90,
            "phased_strangler_with_parallel_run": 0.84,
            "targeted_refactor_wave": 0.76,
            "monitor": 0.68,
        }[route]
        if not system_enriched:
            base -= 0.15
        if not dependency_enriched:
            base -= 0.15
        return round(min(0.99, max(0.05, base)), 3)

    @staticmethod
    def _build_stats(
        *,
        signals: list[LegacyMigrationSignal],
        enrichments: list[LegacyMigrationActionResult],
        decisions: list[LegacyMigrationDecision],
        actions: list[LegacyMigrationActionResult],
    ) -> LegacyMigrationExecutionStats:
        route_counts: dict[LegacyMigrationRoute, int] = defaultdict(int)
        for row in decisions:
            route_counts[row.route] += 1

        actions_success = sum(1 for row in actions if row.success and row.status == "executed")
        actions_skipped = sum(1 for row in actions if row.status == "skipped")
        actions_failed = sum(1 for row in actions if not row.success)

        return LegacyMigrationExecutionStats(
            systems_total=len(signals),
            enrichment_total=len(enrichments),
            enrichment_success=sum(1 for row in enrichments if row.success),
            actions_total=len(actions),
            actions_success=actions_success,
            actions_skipped=actions_skipped,
            actions_failed=actions_failed,
            immediate_count=route_counts["immediate_replatform_program"],
            phased_count=route_counts["phased_strangler_with_parallel_run"],
            targeted_count=route_counts["targeted_refactor_wave"],
            monitor_count=route_counts["monitor"],
        )

    @staticmethod
    def _recommendations(
        *,
        pipeline_report: UseCaseExecutionReport,
        stats: LegacyMigrationExecutionStats,
        decisions: list[LegacyMigrationDecision],
        errors: list[str],
    ) -> list[str]:
        recs: list[str] = [
            (
                "Decision mix: "
                f"immediate={stats.immediate_count}, "
                f"phased={stats.phased_count}, "
                f"targeted={stats.targeted_count}, monitor={stats.monitor_count}."
            ),
            (
                f"Enrichment success {stats.enrichment_success}/{stats.enrichment_total}; "
                f"actions success={stats.actions_success}, skipped={stats.actions_skipped}, failed={stats.actions_failed}."
            ),
            "For immediate systems, lock rollback plans and parallel-run criteria before cutovers.",
            "For phased systems, sequence strangler waves around dependency hotspots.",
            "For targeted systems, track wave throughput and defect-escape rate week over week.",
        ]

        if pipeline_report.ranked_actions:
            recs.append(f"Primary tri-provider action: {pipeline_report.ranked_actions[0].action}")

        if errors:
            recs.append(
                "At least one integration failed; route affected systems to manual architecture review."
            )

        top = decisions[:3]
        if top:
            recs.append(
                "Top systems: "
                + ", ".join(
                    f"{row.system_id}:{row.route}:{row.risk_score:.2f}:{row.service_id}"
                    for row in top
                )
                + "."
            )

        return recs
