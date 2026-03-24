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
ManufacturingActionResult = IntegrationActionResult

_ANOMALY_RE = re.compile(
    r"\b(?:MFG|ANOM|FAULT|INC)(?:[-_][A-Za-z0-9]{2,}|[0-9]{2,}[A-Za-z0-9]*)\b",
    re.IGNORECASE,
)
_LINE_RE = re.compile(
    r"\b(?:LINE|CELL|STATION)(?:[-_][A-Za-z0-9]{2,}|[0-9]{2,}[A-Za-z0-9]*)\b",
    re.IGNORECASE,
)
_ASSET_RE = re.compile(
    r"\b(?:ASSET|MACHINE|ROBOT|PRESS|MILL)(?:[-_][A-Za-z0-9]{2,}|[0-9]{2,}[A-Za-z0-9]*)\b",
    re.IGNORECASE,
)
_YIELD_DROP_RE = re.compile(
    r"\b(\d{1,3}(?:\.\d+)?)\s*%\s*(?:yield\s*)?(?:drop|decline|decrease|down)\b",
    re.IGNORECASE,
)
_VIBRATION_RE = re.compile(
    r"\b(\d{1,4}(?:\.\d+)?)\s*(?:mm/s|ips|vibration)\b",
    re.IGNORECASE,
)
_THERMAL_RE = re.compile(r"\b(\d{1,4}(?:\.\d+)?)\s*(?:c|f|deg|°c|°f)\b", re.IGNORECASE)
_SHIFT_RE = re.compile(r"\b(?:shift|batch)[-_ ]?([A-Za-z0-9]{1,8})\b", re.IGNORECASE)

_ROOT_CAUSE_HINTS = (
    "firmware",
    "calibration",
    "bearing",
    "alignment",
    "contamination",
    "tool wear",
    "sensor drift",
    "coolant",
)
_ROOT_CAUSE_RE = re.compile(
    "|".join(re.escape(keyword) for keyword in _ROOT_CAUSE_HINTS), re.IGNORECASE
)
_SAFETY_RE = re.compile(
    r"(?:safety interlock|near miss|operator injury|emergency stop|lockout)",
    re.IGNORECASE,
)


def _normalize(value: str) -> str:
    return value.strip().replace("_", "-").upper()


class LineTelemetryAdapter(Protocol):
    def lookup_line(self, line_id: str) -> dict[str, Any]: ...


class MaintenanceHistoryAdapter(Protocol):
    def lookup_asset(self, asset_id: str) -> dict[str, Any]: ...


class ManufacturingActionAdapter(Protocol):
    def pause_line(self, line_id: str, *, reason: str) -> dict[str, Any]: ...

    def rollback_firmware(self, line_id: str, *, reason: str) -> dict[str, Any]: ...

    def dispatch_reliability_engineer(self, asset_id: str, *, reason: str) -> dict[str, Any]: ...

    def increase_quality_inspection(self, line_id: str, *, reason: str) -> dict[str, Any]: ...


class NoOpLineTelemetryAdapter:
    def lookup_line(self, line_id: str) -> dict[str, Any]:
        return {
            "line_id": line_id,
            "yield_rate": 0.87,
            "vibration_risk": 0.35,
            "thermal_risk": 0.32,
            "fault_rate_per_hour": 0.8,
            "source": "noop",
        }


class NoOpMaintenanceHistoryAdapter:
    def lookup_asset(self, asset_id: str) -> dict[str, Any]:
        return {
            "asset_id": asset_id,
            "recent_failures_30d": 1,
            "overdue_pm_days": 4,
            "firmware_change_recent": False,
            "source": "noop",
        }


class NoOpManufacturingActionAdapter:
    def pause_line(self, line_id: str, *, reason: str) -> dict[str, Any]:
        return {"line_id": line_id, "action": "pause_line", "reason": reason, "status": "noop"}

    def rollback_firmware(self, line_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "line_id": line_id,
            "action": "rollback_firmware",
            "reason": reason,
            "status": "noop",
        }

    def dispatch_reliability_engineer(self, asset_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "asset_id": asset_id,
            "action": "dispatch_reliability_engineer",
            "reason": reason,
            "status": "noop",
        }

    def increase_quality_inspection(self, line_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "line_id": line_id,
            "action": "increase_quality_inspection",
            "reason": reason,
            "status": "noop",
        }


@dataclass(slots=True)
class InMemoryLineTelemetryAdapter:
    lines: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_line(self, line_id: str) -> dict[str, Any]:
        line = _normalize(line_id)
        payload = self.lines.get(line, {})
        yield_rate = float(payload.get("yield_rate", 0.88))
        vibration_risk = float(payload.get("vibration_risk", 0.35))
        thermal_risk = float(payload.get("thermal_risk", 0.33))
        fault_rate = float(payload.get("fault_rate_per_hour", 0.8))
        return {
            "line_id": line,
            "yield_rate": max(0.0, min(1.0, yield_rate)),
            "vibration_risk": max(0.0, min(1.0, vibration_risk)),
            "thermal_risk": max(0.0, min(1.0, thermal_risk)),
            "fault_rate_per_hour": max(0.0, fault_rate),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryMaintenanceHistoryAdapter:
    assets: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_asset(self, asset_id: str) -> dict[str, Any]:
        asset = _normalize(asset_id)
        payload = self.assets.get(asset, {})
        failures = int(payload.get("recent_failures_30d", 1))
        overdue_days = int(payload.get("overdue_pm_days", 5))
        firmware_recent = bool(payload.get("firmware_change_recent", False))
        return {
            "asset_id": asset,
            "recent_failures_30d": max(0, failures),
            "overdue_pm_days": max(0, overdue_days),
            "firmware_change_recent": firmware_recent,
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryManufacturingActionAdapter:
    paused_lines: set[str] = field(default_factory=set)
    rollback_lines: set[str] = field(default_factory=set)
    dispatched_assets: set[str] = field(default_factory=set)
    inspection_lines: set[str] = field(default_factory=set)

    def pause_line(self, line_id: str, *, reason: str) -> dict[str, Any]:
        line = _normalize(line_id)
        self.paused_lines.add(line)
        return {
            "line_id": line,
            "action": "pause_line",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def rollback_firmware(self, line_id: str, *, reason: str) -> dict[str, Any]:
        line = _normalize(line_id)
        self.rollback_lines.add(line)
        return {
            "line_id": line,
            "action": "rollback_firmware",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def dispatch_reliability_engineer(self, asset_id: str, *, reason: str) -> dict[str, Any]:
        asset = _normalize(asset_id)
        self.dispatched_assets.add(asset)
        return {
            "asset_id": asset,
            "action": "dispatch_reliability_engineer",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def increase_quality_inspection(self, line_id: str, *, reason: str) -> dict[str, Any]:
        line = _normalize(line_id)
        self.inspection_lines.add(line)
        return {
            "line_id": line,
            "action": "increase_quality_inspection",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }


_HTTPJSONAdapterBase = HTTPJSONAdapterBase


@dataclass(slots=True)
class HTTPLineTelemetryAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/mfg/line_telemetry"

    def lookup_line(self, line_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"line_id": line_id})


@dataclass(slots=True)
class HTTPMaintenanceHistoryAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/mfg/maintenance_history"

    def lookup_asset(self, asset_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"asset_id": asset_id})


@dataclass(slots=True)
class HTTPManufacturingActionAdapter(HTTPJSONAdapterBase):
    pause_path: str = "/mfg/pause_line"
    rollback_path: str = "/mfg/rollback_firmware"
    dispatch_path: str = "/mfg/dispatch_reliability"
    inspect_path: str = "/mfg/increase_inspection"

    def pause_line(self, line_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.pause_path,
            {"line_id": line_id, "reason": reason},
        )

    def rollback_firmware(self, line_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.rollback_path,
            {"line_id": line_id, "reason": reason},
        )

    def dispatch_reliability_engineer(self, asset_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.dispatch_path,
            {"asset_id": asset_id, "reason": reason},
        )

    def increase_quality_inspection(self, line_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.inspect_path,
            {"line_id": line_id, "reason": reason},
        )


def build_line_telemetry_adapter_from_env() -> LineTelemetryAdapter:
    base = os.getenv("MFG_TELEMETRY_BASE_URL")
    token = os.getenv("MFG_TELEMETRY_API_KEY")
    if base and token:
        path = os.getenv("MFG_TELEMETRY_LOOKUP_PATH", "/mfg/line_telemetry")
        return HTTPLineTelemetryAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpLineTelemetryAdapter()


def build_maintenance_history_adapter_from_env() -> MaintenanceHistoryAdapter:
    base = os.getenv("MFG_MAINT_BASE_URL")
    token = os.getenv("MFG_MAINT_API_KEY")
    if base and token:
        path = os.getenv("MFG_MAINT_LOOKUP_PATH", "/mfg/maintenance_history")
        return HTTPMaintenanceHistoryAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpMaintenanceHistoryAdapter()


def build_manufacturing_action_adapter_from_env() -> ManufacturingActionAdapter:
    base = os.getenv("MFG_ACTION_BASE_URL")
    token = os.getenv("MFG_ACTION_API_KEY")
    if base and token:
        return HTTPManufacturingActionAdapter(
            base_url=base,
            api_key=token,
            pause_path=os.getenv("MFG_ACTION_PAUSE_PATH", "/mfg/pause_line"),
            rollback_path=os.getenv("MFG_ACTION_ROLLBACK_PATH", "/mfg/rollback_firmware"),
            dispatch_path=os.getenv("MFG_ACTION_DISPATCH_PATH", "/mfg/dispatch_reliability"),
            inspect_path=os.getenv("MFG_ACTION_INSPECT_PATH", "/mfg/increase_inspection"),
        )
    return NoOpManufacturingActionAdapter()


ManufacturingRoute = Literal[
    "contain_and_rollback",
    "targeted_diagnostics",
    "enhanced_quality_gate",
    "monitor",
]


@dataclass(slots=True, frozen=True)
class ManufacturingSignal:
    anomaly_id: str
    line_id: str
    asset_id: str
    shift_id: str
    root_cause_hint: str | None
    observed_yield_drop_pct: float | None
    observed_vibration_value: float | None
    observed_thermal_value: float | None
    safety_indicator: bool


@dataclass(slots=True, frozen=True)
class ManufacturingDecision:
    anomaly_id: str
    line_id: str
    asset_id: str
    shift_id: str
    route: ManufacturingRoute
    priority: str
    confidence: float
    risk_score: float
    yield_loss: float
    vibration_risk: float
    thermal_risk: float
    fault_rate_per_hour: float
    recent_failures_30d: int
    overdue_pm_days: int
    firmware_change_recent: bool
    rationale: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ManufacturingExecutionPolicy:
    execute_actions_in_dry_run: bool = False
    max_parallel_tasks: int = 6
    max_anomalies_to_process: int = 20
    containment_risk_threshold: float = 0.82
    diagnostic_risk_threshold: float = 0.58
    quality_gate_risk_threshold: float = 0.38
    high_yield_loss_threshold: float = 0.16
    high_fault_rate_threshold: float = 2.5
    allow_auto_line_pause: bool = True
    allow_auto_firmware_rollback: bool = True
    allow_auto_engineer_dispatch: bool = True
    allow_auto_quality_gate: bool = True

    def __post_init__(self) -> None:
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be >= 1")
        if self.max_anomalies_to_process < 1:
            raise ValueError("max_anomalies_to_process must be >= 1")
        if self.high_fault_rate_threshold < 0:
            raise ValueError("high_fault_rate_threshold must be >= 0")
        for name, value in (
            ("containment_risk_threshold", self.containment_risk_threshold),
            ("diagnostic_risk_threshold", self.diagnostic_risk_threshold),
            ("quality_gate_risk_threshold", self.quality_gate_risk_threshold),
            ("high_yield_loss_threshold", self.high_yield_loss_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(slots=True, frozen=True)
class ManufacturingExecutionStats:
    anomalies_total: int
    enrichment_total: int
    enrichment_success: int
    actions_total: int
    actions_success: int
    actions_skipped: int
    actions_failed: int
    contain_and_rollback_count: int
    targeted_diagnostics_count: int
    enhanced_quality_gate_count: int
    monitor_count: int


@dataclass(slots=True, frozen=True)
class ManufacturingExecutionReport:
    batch_id: str
    pipeline_report: UseCaseExecutionReport
    mode: str
    started_at: datetime
    completed_at: datetime
    signals: tuple[ManufacturingSignal, ...]
    enrichments: tuple[ManufacturingActionResult, ...]
    decisions: tuple[ManufacturingDecision, ...]
    actions: tuple[ManufacturingActionResult, ...]
    stats: ManufacturingExecutionStats
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
class ManufacturingRootCauseCommander(BaseIntegrationCommanderMixin):
    pipeline: TriProviderPipeline
    line_telemetry_adapter: LineTelemetryAdapter
    maintenance_history_adapter: MaintenanceHistoryAdapter
    action_adapter: ManufacturingActionAdapter
    execution_policy: ManufacturingExecutionPolicy = field(
        default_factory=ManufacturingExecutionPolicy
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
    ) -> ManufacturingExecutionReport:
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
            max_signals=self.execution_policy.max_anomalies_to_process,
        )

        enrichments = self._run_enrichment(signals)
        decisions = self._build_decisions(signals, enrichments)

        execute_actions = True
        if mode == "dry" and not self.execution_policy.execute_actions_in_dry_run:
            execute_actions = False
            warnings.append("Manufacturing actions skipped in dry mode by execution policy.")

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
        return ManufacturingExecutionReport(
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
    def extract_signals(text: str, *, max_signals: int = 20) -> list[ManufacturingSignal]:
        anomaly_matches = list(_ANOMALY_RE.finditer(text))
        lines = [_normalize(m.group(0)) for m in _LINE_RE.finditer(text)]
        assets = [_normalize(m.group(0)) for m in _ASSET_RE.finditer(text)]
        shifts = [f"SHIFT-{m.group(1).upper()}" for m in _SHIFT_RE.finditer(text)]

        yield_drop_values = [float(m.group(1)) / 100.0 for m in _YIELD_DROP_RE.finditer(text)]
        vibration_values = [float(m.group(1)) for m in _VIBRATION_RE.finditer(text)]
        thermal_values = [float(m.group(1)) for m in _THERMAL_RE.finditer(text)]
        root_cause_hits = [m.group(0).lower() for m in _ROOT_CAUSE_RE.finditer(text)]
        has_safety = bool(_SAFETY_RE.search(text))

        def _pick(values: list[str], index: int, default: str) -> str:
            if not values:
                return default
            if index < len(values):
                return values[index]
            return values[-1]

        def _pick_float(values: list[float], index: int) -> float | None:
            if not values:
                return None
            if index < len(values):
                return values[index]
            return values[-1]

        if not anomaly_matches:
            anomaly_id = f"MFG-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:8].upper()}"
            return [
                ManufacturingSignal(
                    anomaly_id=anomaly_id,
                    line_id=_pick(lines, 0, "LINE-AUTO-01"),
                    asset_id=_pick(assets, 0, "ASSET-AUTO-01"),
                    shift_id=_pick(shifts, 0, "SHIFT-AUTO"),
                    root_cause_hint=_pick(root_cause_hits, 0, "") or None,
                    observed_yield_drop_pct=_pick_float(yield_drop_values, 0),
                    observed_vibration_value=_pick_float(vibration_values, 0),
                    observed_thermal_value=_pick_float(thermal_values, 0),
                    safety_indicator=has_safety,
                )
            ]

        rows: list[ManufacturingSignal] = []
        seen_ids: set[str] = set()
        for idx, match in enumerate(anomaly_matches):
            if len(rows) >= max_signals:
                break

            anomaly_id = _normalize(match.group(0))
            key = anomaly_id.lower()
            if key in seen_ids:
                continue
            seen_ids.add(key)

            segment_index = len(rows)
            start = match.start()
            end = anomaly_matches[idx + 1].start() if idx + 1 < len(anomaly_matches) else len(text)
            segment = text[start:end]

            line_match = _LINE_RE.search(segment)
            asset_match = _ASSET_RE.search(segment)
            shift_match = _SHIFT_RE.search(segment)
            root_cause_match = _ROOT_CAUSE_RE.search(segment)
            yield_drop_match = _YIELD_DROP_RE.search(segment)
            vibration_match = _VIBRATION_RE.search(segment)
            thermal_match = _THERMAL_RE.search(segment)

            rows.append(
                ManufacturingSignal(
                    anomaly_id=anomaly_id,
                    line_id=_normalize(line_match.group(0))
                    if line_match
                    else _pick(lines, segment_index, "LINE-AUTO-01"),
                    asset_id=_normalize(asset_match.group(0))
                    if asset_match
                    else _pick(assets, segment_index, "ASSET-AUTO-01"),
                    shift_id=f"SHIFT-{shift_match.group(1).upper()}"
                    if shift_match
                    else _pick(shifts, segment_index, "SHIFT-AUTO"),
                    root_cause_hint=root_cause_match.group(0).lower()
                    if root_cause_match
                    else (_pick(root_cause_hits, segment_index, "") or None),
                    observed_yield_drop_pct=float(yield_drop_match.group(1)) / 100.0
                    if yield_drop_match
                    else _pick_float(yield_drop_values, segment_index),
                    observed_vibration_value=float(vibration_match.group(1))
                    if vibration_match
                    else _pick_float(vibration_values, segment_index),
                    observed_thermal_value=float(thermal_match.group(1))
                    if thermal_match
                    else _pick_float(thermal_values, segment_index),
                    safety_indicator=bool(_SAFETY_RE.search(segment)) or has_safety,
                )
            )

        return rows

    @staticmethod
    def _build_batch_id(scenario: str, started_at: datetime) -> str:
        digest = hashlib.sha256(
            f"{started_at.isoformat()}::{scenario}".encode("utf-8")
        ).hexdigest()[:16]
        return f"mfg-{started_at.strftime('%Y%m%d%H%M%S')}-{digest}"

    def _run_enrichment(
        self, signals: list[ManufacturingSignal]
    ) -> list[ManufacturingActionResult]:
        tasks: list[_ExecutionTask] = []

        line_ids = _unique_preserve([signal.line_id for signal in signals])
        for line_id in line_ids:
            tasks.append(
                _ExecutionTask(
                    integration="line_telemetry",
                    operation="lookup_line",
                    target=line_id,
                    request_payload={"line_id": line_id},
                    idempotency_key=None,
                    call=lambda line_id=line_id: self.line_telemetry_adapter.lookup_line(line_id),
                )
            )

        asset_ids = _unique_preserve([signal.asset_id for signal in signals])
        for asset_id in asset_ids:
            tasks.append(
                _ExecutionTask(
                    integration="maintenance_history",
                    operation="lookup_asset",
                    target=asset_id,
                    request_payload={"asset_id": asset_id},
                    idempotency_key=None,
                    call=lambda asset_id=asset_id: self.maintenance_history_adapter.lookup_asset(
                        asset_id
                    ),
                )
            )

        return self._execute_integration_tasks(tasks)

    def _build_decisions(
        self,
        signals: list[ManufacturingSignal],
        enrichments: list[ManufacturingActionResult],
    ) -> list[ManufacturingDecision]:
        line_data: dict[str, dict[str, Any]] = {}
        maint_data: dict[str, dict[str, Any]] = {}

        for row in enrichments:
            if not row.success or row.status != "executed":
                continue
            if row.integration == "line_telemetry":
                line_data[row.target] = row.response or {}
            elif row.integration == "maintenance_history":
                maint_data[row.target] = row.response or {}

        decisions: list[ManufacturingDecision] = []
        for signal in signals:
            line = line_data.get(signal.line_id, {})
            maint = maint_data.get(signal.asset_id, {})

            yield_rate = self._as_float(
                line,
                keys=("yield_rate",),
                default=max(0.0, 1.0 - float(signal.observed_yield_drop_pct or 0.0)),
            )
            yield_loss = max(0.0, min(1.0, 1.0 - yield_rate))

            vibration_risk = self._as_float(
                line,
                keys=("vibration_risk", "vibration_score"),
                default=min(1.0, (signal.observed_vibration_value or 0.0) / 12.0),
            )
            thermal_risk = self._as_float(
                line,
                keys=("thermal_risk", "thermal_score"),
                default=min(1.0, (signal.observed_thermal_value or 0.0) / 120.0),
            )
            fault_rate = self._as_float(
                line,
                keys=("fault_rate_per_hour", "fault_rate"),
                default=0.8,
                cap_1=False,
            )
            failures = int(
                self._as_float(
                    maint,
                    keys=("recent_failures_30d",),
                    default=1.0,
                    cap_1=False,
                )
            )
            overdue_days = int(
                self._as_float(
                    maint,
                    keys=("overdue_pm_days",),
                    default=5.0,
                    cap_1=False,
                )
            )
            firmware_recent = bool(maint.get("firmware_change_recent", False))
            if signal.root_cause_hint and "firmware" in signal.root_cause_hint:
                firmware_recent = True

            risk_score = min(
                1.0,
                yield_loss * 0.28
                + vibration_risk * 0.18
                + thermal_risk * 0.16
                + min(1.0, fault_rate / 5.0) * 0.14
                + min(1.0, failures / 6.0) * 0.10
                + min(1.0, overdue_days / 60.0) * 0.06
                + (0.10 if firmware_recent else 0.0)
                + (0.12 if signal.safety_indicator else 0.0),
            )

            route: ManufacturingRoute = "monitor"
            rationale: list[str] = []

            if (
                risk_score >= self.execution_policy.containment_risk_threshold
                or signal.safety_indicator
                or (
                    firmware_recent
                    and yield_loss >= self.execution_policy.high_yield_loss_threshold
                )
            ):
                route = "contain_and_rollback"
                rationale.append(
                    "High process risk/safety concern requires containment and rollback."
                )
            elif (
                risk_score >= self.execution_policy.diagnostic_risk_threshold
                or fault_rate >= self.execution_policy.high_fault_rate_threshold
            ):
                route = "targeted_diagnostics"
                rationale.append("Elevated anomaly/failure profile requires targeted diagnostics.")
            elif risk_score >= self.execution_policy.quality_gate_risk_threshold or yield_loss >= (
                self.execution_policy.high_yield_loss_threshold * 0.75
            ):
                route = "enhanced_quality_gate"
                rationale.append(
                    "Moderate risk requires enhanced quality gating and intensified inspection."
                )
            else:
                rationale.append(
                    "Current signal strength supports monitoring with standard controls."
                )

            if not line:
                rationale.append("Line telemetry enrichment missing; confidence reduced.")
            if not maint:
                rationale.append("Maintenance-history enrichment missing; confidence reduced.")

            priority = self._priority_for(route)
            confidence = self._confidence_for(
                route=route,
                line_enriched=bool(line),
                maint_enriched=bool(maint),
            )

            decisions.append(
                ManufacturingDecision(
                    anomaly_id=signal.anomaly_id,
                    line_id=signal.line_id,
                    asset_id=signal.asset_id,
                    shift_id=signal.shift_id,
                    route=route,
                    priority=priority,
                    confidence=confidence,
                    risk_score=risk_score,
                    yield_loss=yield_loss,
                    vibration_risk=vibration_risk,
                    thermal_risk=thermal_risk,
                    fault_rate_per_hour=fault_rate,
                    recent_failures_30d=max(0, failures),
                    overdue_pm_days=max(0, overdue_days),
                    firmware_change_recent=firmware_recent,
                    rationale=tuple(rationale),
                )
            )

        decisions.sort(
            key=lambda row: (
                row.route in {"contain_and_rollback", "targeted_diagnostics"},
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
        decisions: list[ManufacturingDecision],
        execute_actions: bool,
    ) -> list[ManufacturingActionResult]:
        tasks: list[_ExecutionTask] = []
        skipped: list[ManufacturingActionResult] = []

        for row in decisions:
            reason = "; ".join(row.rationale)
            if not execute_actions:
                skipped.append(
                    ManufacturingActionResult(
                        integration="manufacturing_actions",
                        operation=row.route,
                        target=row.anomaly_id,
                        success=True,
                        latency_ms=0,
                        request={"anomaly_id": row.anomaly_id, "route": row.route},
                        status="skipped",
                        attempts=0,
                        notes=("action execution disabled by runtime policy",),
                    )
                )
                continue

            if row.route == "monitor":
                skipped.append(
                    ManufacturingActionResult(
                        integration="manufacturing_actions",
                        operation="monitor",
                        target=row.anomaly_id,
                        success=True,
                        latency_ms=0,
                        request={"anomaly_id": row.anomaly_id, "route": "monitor"},
                        status="skipped",
                        attempts=0,
                        notes=("monitor route requires no external action call",),
                    )
                )
                continue

            if row.route == "contain_and_rollback":
                if self.execution_policy.allow_auto_line_pause:
                    pause_key = f"{batch_id}:pause:{row.line_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="manufacturing_actions",
                            operation="pause_line",
                            target=row.line_id,
                            request_payload={"line_id": row.line_id, "reason": reason},
                            idempotency_key=pause_key,
                            call=lambda row=row, reason=reason: self.action_adapter.pause_line(
                                row.line_id,
                                reason=reason,
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ManufacturingActionResult(
                            integration="manufacturing_actions",
                            operation="pause_line",
                            target=row.line_id,
                            success=True,
                            latency_ms=0,
                            request={"line_id": row.line_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto line pause disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_firmware_rollback:
                    rollback_key = f"{batch_id}:rollback:{row.line_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="manufacturing_actions",
                            operation="rollback_firmware",
                            target=row.line_id,
                            request_payload={"line_id": row.line_id, "reason": reason},
                            idempotency_key=rollback_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.rollback_firmware(
                                    row.line_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ManufacturingActionResult(
                            integration="manufacturing_actions",
                            operation="rollback_firmware",
                            target=row.line_id,
                            success=True,
                            latency_ms=0,
                            request={"line_id": row.line_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto firmware rollback disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_engineer_dispatch:
                    dispatch_key = f"{batch_id}:dispatch:{row.asset_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="manufacturing_actions",
                            operation="dispatch_reliability_engineer",
                            target=row.asset_id,
                            request_payload={"asset_id": row.asset_id, "reason": reason},
                            idempotency_key=dispatch_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.dispatch_reliability_engineer(
                                    row.asset_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ManufacturingActionResult(
                            integration="manufacturing_actions",
                            operation="dispatch_reliability_engineer",
                            target=row.asset_id,
                            success=True,
                            latency_ms=0,
                            request={"asset_id": row.asset_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto reliability dispatch disabled by policy",),
                        )
                    )
                continue

            if row.route == "targeted_diagnostics":
                if self.execution_policy.allow_auto_engineer_dispatch:
                    dispatch_key = f"{batch_id}:dispatch:{row.asset_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="manufacturing_actions",
                            operation="dispatch_reliability_engineer",
                            target=row.asset_id,
                            request_payload={"asset_id": row.asset_id, "reason": reason},
                            idempotency_key=dispatch_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.dispatch_reliability_engineer(
                                    row.asset_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ManufacturingActionResult(
                            integration="manufacturing_actions",
                            operation="dispatch_reliability_engineer",
                            target=row.asset_id,
                            success=True,
                            latency_ms=0,
                            request={"asset_id": row.asset_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto reliability dispatch disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_quality_gate:
                    inspect_key = f"{batch_id}:inspect:{row.line_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="manufacturing_actions",
                            operation="increase_quality_inspection",
                            target=row.line_id,
                            request_payload={"line_id": row.line_id, "reason": reason},
                            idempotency_key=inspect_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.increase_quality_inspection(
                                    row.line_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ManufacturingActionResult(
                            integration="manufacturing_actions",
                            operation="increase_quality_inspection",
                            target=row.line_id,
                            success=True,
                            latency_ms=0,
                            request={"line_id": row.line_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto quality gate disabled by policy",),
                        )
                    )
                continue

            if row.route == "enhanced_quality_gate":
                if self.execution_policy.allow_auto_quality_gate:
                    inspect_key = f"{batch_id}:inspect:{row.line_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="manufacturing_actions",
                            operation="increase_quality_inspection",
                            target=row.line_id,
                            request_payload={"line_id": row.line_id, "reason": reason},
                            idempotency_key=inspect_key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.increase_quality_inspection(
                                    row.line_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ManufacturingActionResult(
                            integration="manufacturing_actions",
                            operation="increase_quality_inspection",
                            target=row.line_id,
                            success=True,
                            latency_ms=0,
                            request={"line_id": row.line_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto quality gate disabled by policy",),
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
    def _priority_for(route: ManufacturingRoute) -> str:
        if route == "contain_and_rollback":
            return "urgent"
        if route == "targeted_diagnostics":
            return "high"
        if route == "enhanced_quality_gate":
            return "normal"
        return "low"

    @staticmethod
    def _confidence_for(
        *,
        route: ManufacturingRoute,
        line_enriched: bool,
        maint_enriched: bool,
    ) -> float:
        base = {
            "contain_and_rollback": 0.9,
            "targeted_diagnostics": 0.84,
            "enhanced_quality_gate": 0.76,
            "monitor": 0.68,
        }[route]
        if not line_enriched:
            base -= 0.15
        if not maint_enriched:
            base -= 0.15
        return round(min(0.99, max(0.05, base)), 3)

    @staticmethod
    def _build_stats(
        *,
        signals: list[ManufacturingSignal],
        enrichments: list[ManufacturingActionResult],
        decisions: list[ManufacturingDecision],
        actions: list[ManufacturingActionResult],
    ) -> ManufacturingExecutionStats:
        route_counts: dict[ManufacturingRoute, int] = defaultdict(int)
        for row in decisions:
            route_counts[row.route] += 1

        actions_success = sum(1 for row in actions if row.success and row.status == "executed")
        actions_skipped = sum(1 for row in actions if row.status == "skipped")
        actions_failed = sum(1 for row in actions if not row.success)

        return ManufacturingExecutionStats(
            anomalies_total=len(signals),
            enrichment_total=len(enrichments),
            enrichment_success=sum(1 for row in enrichments if row.success),
            actions_total=len(actions),
            actions_success=actions_success,
            actions_skipped=actions_skipped,
            actions_failed=actions_failed,
            contain_and_rollback_count=route_counts["contain_and_rollback"],
            targeted_diagnostics_count=route_counts["targeted_diagnostics"],
            enhanced_quality_gate_count=route_counts["enhanced_quality_gate"],
            monitor_count=route_counts["monitor"],
        )

    @staticmethod
    def _recommendations(
        *,
        pipeline_report: UseCaseExecutionReport,
        stats: ManufacturingExecutionStats,
        decisions: list[ManufacturingDecision],
        errors: list[str],
    ) -> list[str]:
        recs: list[str] = [
            (
                "Decision mix: "
                f"contain_and_rollback={stats.contain_and_rollback_count}, "
                f"targeted_diagnostics={stats.targeted_diagnostics_count}, "
                f"enhanced_quality_gate={stats.enhanced_quality_gate_count}, "
                f"monitor={stats.monitor_count}."
            ),
            (
                f"Enrichment success {stats.enrichment_success}/{stats.enrichment_total}; "
                f"actions success={stats.actions_success}, skipped={stats.actions_skipped}, failed={stats.actions_failed}."
            ),
            "For containment cases, verify safe-state checklist before restart and capture rollback evidence.",
            "For diagnostics cases, run focused vibration/thermal analysis with engineer sign-off.",
            "For quality-gate cases, tighten inspection sampling and quarantine suspicious output lots.",
        ]

        if pipeline_report.ranked_actions:
            recs.append(f"Primary tri-provider action: {pipeline_report.ranked_actions[0].action}")

        if errors:
            recs.append(
                "At least one integration failed; escalate affected anomalies for manual reliability review."
            )

        top = decisions[:3]
        if top:
            recs.append(
                "Top anomalies: "
                + ", ".join(
                    f"{row.anomaly_id}:{row.route}:{row.risk_score:.2f}:{row.yield_loss:.2f}"
                    for row in top
                )
                + "."
            )

        return recs
