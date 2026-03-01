from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Sequence

from .anthropic_agentic_text_system import AnthropicAgenticTextSystem
from .framework_bridges import DeepAgentsBridge, LangGraphBridge, PydanticAIBridge
from .manager import ContextManager
from .provider_sdk import OllamaSDKBridge
from .tri_provider_pipeline import TriProviderPipeline
from .tri_provider_use_cases import USE_CASE_INDEX

CheckStatus = Literal["passed", "failed", "skipped"]


@dataclass(slots=True, frozen=True)
class IntegrationCheckResult:
    check: str
    status: CheckStatus
    duration_ms: int
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class IntegrationHarnessReport:
    started_at: datetime
    completed_at: datetime
    strict: bool
    checks: tuple[IntegrationCheckResult, ...]

    @property
    def passed(self) -> int:
        return sum(1 for row in self.checks if row.status == "passed")

    @property
    def failed(self) -> int:
        return sum(1 for row in self.checks if row.status == "failed")

    @property
    def skipped(self) -> int:
        return sum(1 for row in self.checks if row.status == "skipped")

    @property
    def success(self) -> bool:
        if self.failed > 0:
            return False
        if self.strict and self.skipped > 0:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "strict": self.strict,
            "success": self.success,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "checks": [asdict(row) for row in self.checks],
        }


def _as_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


@dataclass(slots=True)
class LiveIntegrationHarness:
    strict: bool = False
    use_case_id: str = "text_governance_orchestrator"
    anthropic_method: str = "query"

    def available_checks(self) -> tuple[str, ...]:
        return (
            "framework_bridges",
            "ollama_local",
            "ollama_cloud",
            "anthropic_agentic",
            "tri_provider_live",
        )

    def run(self, checks: Sequence[str] | None = None) -> IntegrationHarnessReport:
        selected = tuple(checks or self.available_checks())
        handlers: dict[str, Callable[[], IntegrationCheckResult]] = {
            "framework_bridges": self._check_framework_bridges,
            "ollama_local": self._check_ollama_local,
            "ollama_cloud": self._check_ollama_cloud,
            "anthropic_agentic": self._check_anthropic_agentic,
            "tri_provider_live": self._check_tri_provider_live,
        }

        unknown = [name for name in selected if name not in handlers]
        if unknown:
            unknown_csv = ", ".join(sorted(set(unknown)))
            raise ValueError(f"Unknown integration check(s): {unknown_csv}")

        started_at = datetime.now(timezone.utc)
        results = tuple(handlers[name]() for name in selected)
        completed_at = datetime.now(timezone.utc)

        return IntegrationHarnessReport(
            started_at=started_at,
            completed_at=completed_at,
            strict=self.strict,
            checks=results,
        )

    @staticmethod
    def _build_packet() -> Any:
        manager = ContextManager(default_token_budget=1536, reserved_response_tokens=256)
        manager.add_system("You are a reliability operations assistant.")
        manager.add_memory("Prefer concise, actionable outputs.", source="profile")
        manager.add_document(
            "Incident policy: include impact, current mitigation, and next update ETA.",
            source="policy",
            importance=0.8,
        )
        manager.add_message("user", "Summarize current platform incident state.")
        return manager.build_context("platform incident")

    @staticmethod
    def _result(
        *,
        check: str,
        status: CheckStatus,
        started: float,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> IntegrationCheckResult:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return IntegrationCheckResult(
            check=check,
            status=status,
            duration_ms=elapsed_ms,
            message=message,
            details=dict(details or {}),
        )

    def _check_framework_bridges(self) -> IntegrationCheckResult:
        started = time.perf_counter()
        try:
            pipeline = TriProviderPipeline(USE_CASE_INDEX["soc_incident_commander"])

            node = LangGraphBridge.make_tri_provider_node(pipeline)
            node_output = node(
                {
                    "scenario": "Potential endpoint compromise and unusual outbound traffic.",
                    "evidence_documents": [
                        "SIEM and EDR indicators corroborate suspicious activity."
                    ],
                    "mode": "dry",
                }
            )

            deep_result = DeepAgentsBridge.run(
                type(
                    "_DeepAgent",
                    (),
                    {"run": lambda self, task, **kwargs: {"task": task, "kwargs": kwargs}},
                )(),
                "Create a response checklist",
                trace=True,
            )
            pyd_result = PydanticAIBridge.run_sync(
                type(
                    "_PydAgent",
                    (),
                    {
                        "run_sync": lambda self, prompt, **kwargs: {
                            "prompt": prompt,
                            "kwargs": kwargs,
                        }
                    },
                )(),
                "Summarize containment actions",
            )

            return self._result(
                check="framework_bridges",
                status="passed",
                started=started,
                message="LangGraph/DeepAgents/PydanticAI bridge contracts passed.",
                details={
                    "langgraph_keys": sorted(node_output.keys()),
                    "deepagents_method": deep_result.metadata.get("method"),
                    "pydantic_ai_method": pyd_result.metadata.get("method"),
                },
            )
        except Exception as exc:
            return self._result(
                check="framework_bridges",
                status="failed",
                started=started,
                message=f"Framework bridge smoke failed: {exc}",
            )

    @staticmethod
    def _ollama_timeout_seconds() -> float:
        return _as_float(os.getenv("OLLAMA_SMOKE_TIMEOUT_SECONDS"), 90.0)

    @staticmethod
    def _discover_ollama_models(bridge: OllamaSDKBridge) -> tuple[str, ...]:
        import httpx

        base_url = bridge.base_url.rstrip("/")
        headers = bridge.headers()
        urls = (
            f"{base_url}/api/tags",
            f"{base_url}/v1/models",
        )
        models: list[str] = []

        with httpx.Client(timeout=10.0) as client:
            for url in urls:
                try:
                    response = client.get(url, headers=headers)
                    response.raise_for_status()
                    payload = response.json()
                except Exception:
                    continue

                if isinstance(payload, dict):
                    if isinstance(payload.get("models"), list):
                        for row in payload["models"]:
                            if not isinstance(row, dict):
                                continue
                            name = row.get("name") or row.get("model")
                            if isinstance(name, str) and name.strip():
                                models.append(name.strip())
                    if isinstance(payload.get("data"), list):
                        for row in payload["data"]:
                            if not isinstance(row, dict):
                                continue
                            model_id = row.get("id")
                            if isinstance(model_id, str) and model_id.strip():
                                models.append(model_id.strip())

        seen: set[str] = set()
        ordered: list[str] = []
        for model in models:
            if model in seen:
                continue
            seen.add(model)
            ordered.append(model)
        return tuple(ordered)

    @staticmethod
    def _select_ollama_model(
        bridge: OllamaSDKBridge,
        available_models: tuple[str, ...],
    ) -> str:
        configured_model = os.getenv("OLLAMA_MODEL")
        if configured_model:
            return configured_model

        if not available_models:
            return bridge.model
        if bridge.model in available_models:
            return bridge.model
        return available_models[0]

    def _check_ollama_local(self) -> IntegrationCheckResult:
        started = time.perf_counter()
        if not _as_bool(os.getenv("OLLAMA_RUN_LOCAL_SMOKE")):
            return self._result(
                check="ollama_local",
                status="skipped",
                started=started,
                message="Set OLLAMA_RUN_LOCAL_SMOKE=1 to execute local Ollama call.",
            )

        try:
            packet = self._build_packet()
            bridge = OllamaSDKBridge.from_env()
            available_models = self._discover_ollama_models(bridge)
            selected_model = self._select_ollama_model(bridge, available_models)
            bridge.model = selected_model
            response = bridge.create_with_httpx(
                packet,
                prompt="Provide an operations incident update in 3 bullets.",
                cloud_mode=False,
                stream=False,
                timeout_seconds=self._ollama_timeout_seconds(),
            )
            preview = OllamaSDKBridge.parse_chat_text(response)[:240]
            if not preview.strip():
                raise RuntimeError("Empty response preview from Ollama local call")
            return self._result(
                check="ollama_local",
                status="passed",
                started=started,
                message="Local Ollama call succeeded.",
                details={
                    "model": selected_model,
                    "available_models": list(available_models),
                    "preview": preview,
                },
            )
        except Exception as exc:
            return self._result(
                check="ollama_local",
                status="failed",
                started=started,
                message=f"Local Ollama call failed: {exc}",
            )

    def _check_ollama_cloud(self) -> IntegrationCheckResult:
        started = time.perf_counter()
        if not _as_bool(os.getenv("OLLAMA_RUN_CLOUD_SMOKE")):
            return self._result(
                check="ollama_cloud",
                status="skipped",
                started=started,
                message="Set OLLAMA_RUN_CLOUD_SMOKE=1 to execute cloud Ollama call.",
            )

        try:
            packet = self._build_packet()
            bridge = OllamaSDKBridge.from_env()
            available_models = self._discover_ollama_models(bridge)
            selected_model = self._select_ollama_model(bridge, available_models)
            bridge.model = selected_model
            response = bridge.create_with_httpx(
                packet,
                prompt="Provide an operations incident update in 3 bullets.",
                cloud_mode=True,
                stream=False,
                max_tokens=220,
                timeout_seconds=self._ollama_timeout_seconds(),
            )
            preview = OllamaSDKBridge.parse_chat_text(response)[:240]
            if not preview.strip():
                raise RuntimeError("Empty response preview from Ollama cloud call")
            return self._result(
                check="ollama_cloud",
                status="passed",
                started=started,
                message="Cloud Ollama call succeeded.",
                details={
                    "model": selected_model,
                    "available_models": list(available_models),
                    "preview": preview,
                },
            )
        except Exception as exc:
            return self._result(
                check="ollama_cloud",
                status="failed",
                started=started,
                message=f"Cloud Ollama call failed: {exc}",
            )

    def _check_anthropic_agentic(self) -> IntegrationCheckResult:
        started = time.perf_counter()
        if not _as_bool(os.getenv("ANTHROPIC_AGENTIC_SMOKE")):
            return self._result(
                check="anthropic_agentic",
                status="skipped",
                started=started,
                message=(
                    "Set ANTHROPIC_AGENTIC_SMOKE=1 to run Anthropic agentic SDK query/client smoke."
                ),
            )

        try:
            system = AnthropicAgenticTextSystem()
            output = system.run_text_workflow(
                source_text=(
                    "Please send the customer report to jane.doe@example.com "
                    "and remove internal-only details."
                ),
                instruction=(
                    "Normalize whitespace, redact PII, and produce a customer-safe message."
                ),
                method=self.anthropic_method,
                max_turns=6,
                enable_tool_server=True,
            )
            text = str(output.get("assistant_text", "")).strip()
            if not text:
                raise RuntimeError("Agentic workflow returned empty assistant text")
            return self._result(
                check="anthropic_agentic",
                status="passed",
                started=started,
                message="Anthropic agentic SDK workflow succeeded.",
                details={
                    "sdk_package": output.get("sdk_package"),
                    "message_count": output.get("message_count"),
                    "preview": text[:240],
                },
            )
        except Exception as exc:
            return self._result(
                check="anthropic_agentic",
                status="failed",
                started=started,
                message=f"Anthropic agentic smoke failed: {exc}",
            )

    def _check_tri_provider_live(self) -> IntegrationCheckResult:
        started = time.perf_counter()
        if not _as_bool(os.getenv("TRI_PROVIDER_LIVE_SMOKE")):
            return self._result(
                check="tri_provider_live",
                status="skipped",
                started=started,
                message=(
                    "Set TRI_PROVIDER_LIVE_SMOKE=1 to run live OpenAI/Anthropic/Cerebras pipeline call."
                ),
            )

        required_env = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CEREBRAS_API_KEY")
        missing = [name for name in required_env if not os.getenv(name)]
        if missing:
            return self._result(
                check="tri_provider_live",
                status="failed",
                started=started,
                message=f"Missing required env vars: {', '.join(missing)}",
            )

        try:
            spec = USE_CASE_INDEX[self.use_case_id]
            report = TriProviderPipeline(spec).run(
                scenario=(
                    "Urgent customer-communication rewrite required after a high-severity "
                    "incident, with strict privacy and policy controls."
                ),
                evidence_documents=(
                    "Draft notice includes sensitive internal references and contact details.",
                ),
                mode="live",
                metadata={"harness": "live_integration"},
            )
            return self._result(
                check="tri_provider_live",
                status="passed",
                started=started,
                message="Live tri-provider pipeline call succeeded.",
                details={
                    "use_case_id": report.use_case_id,
                    "ranked_actions": len(report.ranked_actions),
                    "final_plan_preview": report.final_plan[:240],
                },
            )
        except Exception as exc:
            return self._result(
                check="tri_provider_live",
                status="failed",
                started=started,
                message=f"Live tri-provider pipeline call failed: {exc}",
            )
