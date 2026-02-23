from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Sequence

from .manager import ContextManager
from .provider_sdk import (
    AnthropicSDKBridge,
    CerebrasSDKBridge,
    OpenAIResponsesSDKBridge,
    PerplexityResult,
    SpeculativeDecodingMetrics,
)
from .tri_provider_use_cases import TriProviderUseCaseSpec


RunMode = Literal["dry", "live"]


@dataclass(slots=True, frozen=True)
class CandidateRanking:
    action: str
    score: float
    source: str
    rationale: str
    perplexity: float | None = None


@dataclass(slots=True, frozen=True)
class StageOutcome:
    provider: str
    request: dict[str, Any]
    response_preview: str
    success: bool
    notes: tuple[str, ...] = ()
    error: str | None = None


@dataclass(slots=True, frozen=True)
class UseCaseExecutionReport:
    use_case_id: str
    title: str
    mode: RunMode
    started_at: datetime
    completed_at: datetime
    context_tokens_used: int
    context_token_budget: int
    openai_stage: StageOutcome
    anthropic_stage: StageOutcome
    cerebras_stage: StageOutcome
    ranked_actions: tuple[CandidateRanking, ...]
    final_plan: str
    speculative_metrics: SpeculativeDecodingMetrics | None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "use_case_id": self.use_case_id,
            "title": self.title,
            "mode": self.mode,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "context_tokens_used": self.context_tokens_used,
            "context_token_budget": self.context_token_budget,
            "openai_stage": asdict(self.openai_stage),
            "anthropic_stage": asdict(self.anthropic_stage),
            "cerebras_stage": asdict(self.cerebras_stage),
            "ranked_actions": [asdict(row) for row in self.ranked_actions],
            "final_plan": self.final_plan,
            "speculative_metrics": asdict(self.speculative_metrics)
            if self.speculative_metrics
            else None,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(slots=True)
class TriProviderPipeline:
    """
    Production-focused orchestrator for tri-provider workflows.

    Execution model:
    1) OpenAI Responses stage for structured extraction.
    2) Anthropic stage for high-quality reasoning / tool planning.
    3) Cerebras stage for fast action generation and ranking.
    """

    spec: TriProviderUseCaseSpec
    openai_bridge: OpenAIResponsesSDKBridge = field(init=False)
    anthropic_bridge: AnthropicSDKBridge = field(init=False)
    cerebras_bridge: CerebrasSDKBridge = field(init=False)

    def __post_init__(self) -> None:
        self.openai_bridge = OpenAIResponsesSDKBridge(
            model=self.spec.openai.model,
            reasoning_effort=self.spec.openai.reasoning_effort,
            include_reasoning_summary=True,
            store=True,
            truncation="auto",
            service_tier="auto",
        )
        self.anthropic_bridge = AnthropicSDKBridge(
            model=self.spec.anthropic.model,
            max_tokens=self.spec.anthropic.max_tokens,
            enable_prompt_cache=self.spec.anthropic.enable_prompt_cache,
            enable_thinking=self.spec.anthropic.enable_thinking,
            thinking_budget_tokens=self.spec.anthropic.thinking_budget_tokens,
        )
        self.cerebras_bridge = CerebrasSDKBridge(
            model=self.spec.cerebras.model,
            service_tier=self.spec.cerebras.service_tier,
            reasoning_effort=self.spec.cerebras.reasoning_effort,
            reasoning_format=self.spec.cerebras.reasoning_format,
        )

    def run(
        self,
        *,
        scenario: str,
        evidence_documents: Sequence[str] = (),
        mode: RunMode = "dry",
        metadata: dict[str, str] | None = None,
    ) -> UseCaseExecutionReport:
        if mode not in {"dry", "live"}:
            raise ValueError("mode must be 'dry' or 'live'")

        started_at = datetime.now(timezone.utc)
        warnings: list[str] = []
        errors: list[str] = []

        packet = self._build_context_packet(scenario, evidence_documents)
        openai_request, anthropic_request, cerebras_request = self._build_requests(
            packet=packet,
            metadata=metadata or {},
        )

        if mode == "live":
            live_report = self._run_live(
                packet=packet,
                openai_request=openai_request,
                anthropic_request=anthropic_request,
                cerebras_request=cerebras_request,
                scenario=scenario,
                warnings=warnings,
                errors=errors,
            )
            completed_at = datetime.now(timezone.utc)
            return UseCaseExecutionReport(
                use_case_id=self.spec.use_case_id,
                title=self.spec.title,
                mode=mode,
                started_at=started_at,
                completed_at=completed_at,
                context_tokens_used=packet.used_tokens,
                context_token_budget=packet.token_budget,
                openai_stage=live_report["openai_stage"],
                anthropic_stage=live_report["anthropic_stage"],
                cerebras_stage=live_report["cerebras_stage"],
                ranked_actions=live_report["ranked_actions"],
                final_plan=live_report["final_plan"],
                speculative_metrics=live_report["speculative_metrics"],
                warnings=tuple(warnings),
                errors=tuple(errors),
            )

        dry = self._run_dry(
            packet=packet,
            openai_request=openai_request,
            anthropic_request=anthropic_request,
            cerebras_request=cerebras_request,
            scenario=scenario,
        )
        completed_at = datetime.now(timezone.utc)
        return UseCaseExecutionReport(
            use_case_id=self.spec.use_case_id,
            title=self.spec.title,
            mode=mode,
            started_at=started_at,
            completed_at=completed_at,
            context_tokens_used=packet.used_tokens,
            context_token_budget=packet.token_budget,
            openai_stage=dry["openai_stage"],
            anthropic_stage=dry["anthropic_stage"],
            cerebras_stage=dry["cerebras_stage"],
            ranked_actions=dry["ranked_actions"],
            final_plan=dry["final_plan"],
            speculative_metrics=None,
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    def _build_context_packet(
        self,
        scenario: str,
        evidence_documents: Sequence[str],
    ):
        manager = ContextManager(default_token_budget=6144, reserved_response_tokens=768)
        manager.add_system(self.spec.system_prompt, source=f"use-case:{self.spec.use_case_id}")
        manager.add_memory(self.spec.objective, source="objective", pinned=True, importance=1.0)
        default_docs = (
            self.spec.default_documents
            if self.spec.default_documents
            else tuple(self._generated_default_documents())
        )
        for idx, doc in enumerate(default_docs):
            manager.add_document(doc, source=f"default-doc-{idx}", importance=0.7)
        for idx, doc in enumerate(evidence_documents):
            manager.add_document(doc, source=f"evidence-doc-{idx}", importance=0.85)
        manager.add_message("user", scenario)
        return manager.build_context(query=scenario)

    def _build_requests(
        self,
        *,
        packet: Any,
        metadata: dict[str, str],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        openai_request = self.openai_bridge.build_response_request(
            packet,
            prompt=self.spec.openai.prompt,
            metadata={"use_case_id": self.spec.use_case_id, **metadata},
            enable_web_search=self.spec.openai.enable_web_search,
            json_schema=self.spec.openai.json_schema,
            json_schema_name=self.spec.openai.json_schema_name,
        )

        anthropic_tools = (
            self.spec.anthropic.tools
            if self.spec.anthropic.tools
            else tuple(self._domain_tools())
        )
        tool_choice = self.spec.anthropic.tool_choice
        if tool_choice is None and anthropic_tools:
            tool_choice = {"type": "auto"}

        anthropic_request = self.anthropic_bridge.build_message_request(
            packet,
            tools=anthropic_tools,
            tool_choice=tool_choice,
            metadata={"use_case_id": self.spec.use_case_id, **metadata},
        )
        if anthropic_request["messages"]:
            anthropic_request["messages"].append(
                {
                    "role": "user",
                    "content": [{"type": "text", "text": self.spec.anthropic.prompt}],
                }
            )

        cerebras_request = self.cerebras_bridge.build_chat_request(
            packet,
            prompt=self.spec.cerebras.prompt,
            prediction=self.spec.cerebras.speculative_seed
            if self.spec.cerebras.speculative_seed
            else None,
            max_completion_tokens=self.spec.cerebras.max_completion_tokens,
            logprobs=True,
            top_logprobs=2,
            temperature=0.1,
            metadata={"use_case_id": self.spec.use_case_id, **metadata},
        )
        return openai_request, anthropic_request, cerebras_request

    def _run_dry(
        self,
        *,
        packet: Any,
        openai_request: dict[str, Any],
        anthropic_request: dict[str, Any],
        cerebras_request: dict[str, Any],
        scenario: str,
    ) -> dict[str, Any]:
        extraction_preview = self._simulate_openai_extraction(scenario)
        investigation_preview = self._simulate_anthropic_plan(scenario)
        ranked_actions = self._offline_rank_candidates(scenario)
        final_plan = self._compose_final_plan(investigation_preview, ranked_actions)

        return {
            "openai_stage": StageOutcome(
                provider="openai",
                request=openai_request,
                response_preview=extraction_preview,
                success=True,
                notes=("dry-run simulated extraction",),
            ),
            "anthropic_stage": StageOutcome(
                provider="anthropic",
                request=anthropic_request,
                response_preview=investigation_preview,
                success=True,
                notes=("dry-run simulated reasoning/tool plan",),
            ),
            "cerebras_stage": StageOutcome(
                provider="cerebras",
                request=cerebras_request,
                response_preview=(
                    ranked_actions[0].action if ranked_actions else "No candidate actions."
                ),
                success=True,
                notes=("dry-run simulated fast ranking",),
            ),
            "ranked_actions": tuple(ranked_actions),
            "final_plan": final_plan,
        }

    def _run_live(
        self,
        *,
        packet: Any,
        openai_request: dict[str, Any],
        anthropic_request: dict[str, Any],
        cerebras_request: dict[str, Any],
        scenario: str,
        warnings: list[str],
        errors: list[str],
    ) -> dict[str, Any]:
        openai_stage = StageOutcome(
            provider="openai",
            request=openai_request,
            response_preview="",
            success=False,
            notes=(),
            error="not executed",
        )
        anthropic_stage = StageOutcome(
            provider="anthropic",
            request=anthropic_request,
            response_preview="",
            success=False,
            notes=(),
            error="not executed",
        )
        cerebras_stage = StageOutcome(
            provider="cerebras",
            request=cerebras_request,
            response_preview="",
            success=False,
            notes=(),
            error="not executed",
        )
        speculative_metrics: SpeculativeDecodingMetrics | None = None
        ranked_actions: tuple[CandidateRanking, ...] = tuple(
            self._offline_rank_candidates(scenario)
        )

        # OpenAI
        try:
            from openai import OpenAI  # type: ignore

            client = OpenAI()
            response = client.responses.create(**openai_request)
            preview = self._extract_openai_preview(response)
            openai_stage = StageOutcome(
                provider="openai",
                request=openai_request,
                response_preview=preview,
                success=True,
                notes=(),
            )
        except Exception as exc:
            errors.append(f"OpenAI stage failed: {exc}")
            warnings.append("Falling back to simulated OpenAI extraction.")
            openai_stage = StageOutcome(
                provider="openai",
                request=openai_request,
                response_preview=self._simulate_openai_extraction(scenario),
                success=False,
                notes=("fallback simulated extraction",),
                error=str(exc),
            )

        # Anthropic
        try:
            from anthropic import Anthropic  # type: ignore

            client = Anthropic()
            response = client.messages.create(**anthropic_request)
            preview = self._extract_anthropic_preview(response)
            anthropic_stage = StageOutcome(
                provider="anthropic",
                request=anthropic_request,
                response_preview=preview,
                success=True,
                notes=(),
            )
        except Exception as exc:
            errors.append(f"Anthropic stage failed: {exc}")
            warnings.append("Falling back to simulated Anthropic planning.")
            anthropic_stage = StageOutcome(
                provider="anthropic",
                request=anthropic_request,
                response_preview=self._simulate_anthropic_plan(scenario),
                success=False,
                notes=("fallback simulated planning",),
                error=str(exc),
            )

        # Cerebras
        try:
            from cerebras.cloud.sdk import Cerebras  # type: ignore

            client = Cerebras()
            response = client.chat.completions.create(**cerebras_request)
            preview = self._extract_cerebras_preview(response)
            speculative_metrics = (
                self.cerebras_bridge.extract_speculative_decoding_metrics(response)
            )

            live_ranked: list[CandidateRanking] = []
            candidate_actions = self._candidate_actions()
            if candidate_actions:
                ranked = self.cerebras_bridge.score_candidates_by_perplexity(
                    client,
                    prefix=f"{self.spec.objective}\nScenario:\n{scenario}",
                    candidates=candidate_actions,
                )
                for action, score in ranked:
                    live_ranked.append(
                        CandidateRanking(
                            action=action,
                            score=1 / max(score.perplexity, 1e-6),
                            source="cerebras_perplexity",
                            rationale=(
                                f"Perplexity {score.perplexity:.4f}, "
                                f"avg_neg_logprob {score.average_negative_logprob:.4f}"
                            ),
                            perplexity=score.perplexity,
                        )
                    )
                ranked_actions = tuple(live_ranked)

            cerebras_stage = StageOutcome(
                provider="cerebras",
                request=cerebras_request,
                response_preview=preview,
                success=True,
                notes=(
                    "live execution",
                    "perplexity ranking used" if live_ranked else "no candidate rerank",
                ),
            )
        except Exception as exc:
            errors.append(f"Cerebras stage failed: {exc}")
            warnings.append("Falling back to offline candidate ranking.")
            ranked_actions = tuple(self._offline_rank_candidates(scenario))
            cerebras_stage = StageOutcome(
                provider="cerebras",
                request=cerebras_request,
                response_preview=(
                    ranked_actions[0].action if ranked_actions else "No candidate actions."
                ),
                success=False,
                notes=("fallback offline ranking",),
                error=str(exc),
            )

        final_plan = self._compose_final_plan(
            anthropic_stage.response_preview, list(ranked_actions)
        )
        return {
            "openai_stage": openai_stage,
            "anthropic_stage": anthropic_stage,
            "cerebras_stage": cerebras_stage,
            "ranked_actions": ranked_actions,
            "final_plan": final_plan,
            "speculative_metrics": speculative_metrics,
        }

    def _candidate_actions(self) -> list[str]:
        if self.spec.cerebras.candidate_actions:
            return list(self.spec.cerebras.candidate_actions)
        return self._domain_candidate_actions()

    def _offline_rank_candidates(self, scenario: str) -> list[CandidateRanking]:
        candidates = self._candidate_actions()
        if not candidates:
            return []

        positive = {
            "contain": 0.22,
            "targeted": 0.14,
            "rollback": 0.18,
            "monitor": 0.1,
            "idempotency": 0.2,
            "isolate": 0.18,
            "priority": 0.12,
            "safe": 0.2,
        }
        negative = {"delay": 0.35, "wait": 0.3, "monitor-only": 0.5}

        lower_context = f"{scenario.lower()} {self.spec.objective.lower()}"
        urgent_context = any(
            token in lower_context
            for token in (
                "critical",
                "incident",
                "compromise",
                "containment",
                "outage",
                "fraud",
                "patient safety",
            )
        )
        rows: list[CandidateRanking] = []
        for action in candidates:
            text = action.lower()
            score = 0.5
            for word, weight in positive.items():
                if word in text:
                    score += weight
                if word in lower_context and word in text:
                    score += weight * 0.5
            for word, penalty in negative.items():
                if word in text and urgent_context:
                    score -= penalty
            score = max(0.0, score)
            rows.append(
                CandidateRanking(
                    action=action,
                    score=score,
                    source="offline_heuristic",
                    rationale="Keyword/intent weighted scoring against objective and scenario.",
                )
            )
        rows.sort(key=lambda row: row.score, reverse=True)
        return rows

    def _generated_default_documents(self) -> list[str]:
        base = [
            f"Operating objective: {self.spec.objective}",
            "All plans must include rollback criteria and owner assignment.",
            "Escalate when customer safety, compliance, or material business impact is detected.",
        ]
        if "security" in self.spec.system_prompt.lower() or "incident" in self.spec.use_case_id:
            base.append("Preserve forensic integrity and maintain incident timeline artifacts.")
        return base

    def _domain_tools(self) -> list[dict[str, Any]]:
        by_case: dict[str, list[dict[str, Any]]] = {
            "catastrophe_claims_pipeline": [
                {
                    "name": "policy_lookup",
                    "description": "Lookup policy coverage and exclusions by claim id.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"claim_id": {"type": "string"}},
                        "required": ["claim_id"],
                    },
                },
                {
                    "name": "fraud_signal_search",
                    "description": "Search prior claim patterns and fraud indicators.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"claimant_id": {"type": "string"}},
                        "required": ["claimant_id"],
                    },
                },
            ],
            "supply_chain_control_tower": [
                {
                    "name": "lane_delay_query",
                    "description": "Fetch delay estimates for shipping lanes and ports.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"lane": {"type": "string"}},
                        "required": ["lane"],
                    },
                },
                {
                    "name": "supplier_risk_lookup",
                    "description": "Get risk profile and capacity by supplier id.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"supplier_id": {"type": "string"}},
                        "required": ["supplier_id"],
                    },
                },
            ],
            "aml_kyc_fincrime": [
                {
                    "name": "transaction_graph_search",
                    "description": "Expand transaction counterparties and routing paths.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"account_id": {"type": "string"}},
                        "required": ["account_id"],
                    },
                },
                {
                    "name": "sanctions_screen",
                    "description": "Check entities against sanctions/PEP/watchlists.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"entity": {"type": "string"}},
                        "required": ["entity"],
                    },
                },
            ],
            "pharmacovigilance_events": [
                {
                    "name": "faers_lookup",
                    "description": "Query adverse event records by compound and symptom.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "compound": {"type": "string"},
                            "symptom": {"type": "string"},
                        },
                        "required": ["compound", "symptom"],
                    },
                },
                {
                    "name": "lot_traceability_search",
                    "description": "Find manufacturing lots and distribution regions.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"lot_id": {"type": "string"}},
                        "required": ["lot_id"],
                    },
                },
            ],
            "grid_outage_response": [
                {
                    "name": "substation_status",
                    "description": "Fetch substation state and feeder dependencies.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"substation_id": {"type": "string"}},
                        "required": ["substation_id"],
                    },
                },
                {
                    "name": "crew_availability",
                    "description": "Return available crews, skills, and ETA.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"region": {"type": "string"}},
                        "required": ["region"],
                    },
                },
            ],
            "emergency_operations_center": [
                {
                    "name": "shelter_capacity",
                    "description": "Get remaining shelter capacity by zone.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"zone": {"type": "string"}},
                        "required": ["zone"],
                    },
                },
                {
                    "name": "road_closure_map",
                    "description": "Retrieve road closure and hazard overlays.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"region": {"type": "string"}},
                        "required": ["region"],
                    },
                },
            ],
            "manufacturing_root_cause": [
                {
                    "name": "sensor_window_query",
                    "description": "Fetch sensor time series for a production line window.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "line_id": {"type": "string"},
                            "window": {"type": "string"},
                        },
                        "required": ["line_id", "window"],
                    },
                },
                {
                    "name": "maintenance_log_lookup",
                    "description": "Get recent maintenance events and parts replaced.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"line_id": {"type": "string"}},
                        "required": ["line_id"],
                    },
                },
            ],
            "regulatory_change_impact": [
                {
                    "name": "control_registry_search",
                    "description": "Map obligations to existing controls and owners.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"obligation": {"type": "string"}},
                        "required": ["obligation"],
                    },
                },
                {
                    "name": "policy_clause_lookup",
                    "description": "Retrieve policy clauses relevant to a requirement.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"topic": {"type": "string"}},
                        "required": ["topic"],
                    },
                },
            ],
            "contract_risk_negotiation": [
                {
                    "name": "clause_library_search",
                    "description": "Find approved fallback clauses by risk category.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"risk_type": {"type": "string"}},
                        "required": ["risk_type"],
                    },
                },
                {
                    "name": "counterparty_profile_lookup",
                    "description": "Get counterparty negotiation history and risk profile.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"counterparty": {"type": "string"}},
                        "required": ["counterparty"],
                    },
                },
            ],
            "legacy_modern_migration": [
                {
                    "name": "dependency_graph_query",
                    "description": "Fetch service and data dependency graph around component.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"component": {"type": "string"}},
                        "required": ["component"],
                    },
                },
                {
                    "name": "test_coverage_lookup",
                    "description": "Return coverage and flaky test stats for module.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"module": {"type": "string"}},
                        "required": ["module"],
                    },
                },
            ],
            "contact_center_autopilot": [
                {
                    "name": "crm_account_snapshot",
                    "description": "Fetch customer account timeline and issue history.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"account_id": {"type": "string"}},
                        "required": ["account_id"],
                    },
                },
                {
                    "name": "policy_guardrail_check",
                    "description": "Verify proposed action against policy and compliance rules.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"action": {"type": "string"}},
                        "required": ["action"],
                    },
                },
            ],
            "clinical_operations_optimizer": [
                {
                    "name": "bed_state_query",
                    "description": "Fetch bed occupancy and discharge forecast by unit.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"unit": {"type": "string"}},
                        "required": ["unit"],
                    },
                },
                {
                    "name": "staffing_roster_lookup",
                    "description": "Get staffing roster, skill mix, and expected absenteeism.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"shift": {"type": "string"}},
                        "required": ["shift"],
                    },
                },
            ],
        }
        return by_case.get(self.spec.use_case_id, [])

    def _domain_candidate_actions(self) -> list[str]:
        by_case: dict[str, list[str]] = {
            "catastrophe_claims_pipeline": [
                "Fast-track life/safety claims while running fraud checks in parallel for high-risk submissions.",
                "Batch all claims by region before severity triage to maximize adjuster utilization.",
                "Require complete documentation before any payout decision to reduce rework.",
            ],
            "supply_chain_control_tower": [
                "Reallocate inventory to highest-margin at-risk orders and reroute via secondary ports.",
                "Pause all shipments for 24 hours while waiting for complete disruption data.",
                "Split orders across alternate suppliers and trigger expedited replenishment.",
            ],
            "aml_kyc_fincrime": [
                "Escalate high-velocity cross-border clusters for immediate manual review and temporary hold.",
                "Delay intervention until weekly review to reduce false-positive impact.",
                "Apply risk-based holds only for entities with sanctions adjacency and anomalous graph patterns.",
            ],
            "pharmacovigilance_events": [
                "Prioritize severe-event cohorts for immediate medical review and lot correlation.",
                "Publish broad safety alert before causality checks complete.",
                "Run targeted follow-up on high-confidence events while maintaining active monitoring.",
            ],
            "grid_outage_response": [
                "Restore critical infrastructure feeders first, then sequence residential circuits by dependency.",
                "Restore lowest-complexity feeders first regardless of criticality.",
                "Dispatch mobile generation to hospitals and water treatment while repair crews isolate root faults.",
            ],
            "emergency_operations_center": [
                "Re-route evacuations to secondary corridors and prioritize high-vulnerability zones.",
                "Maintain current evacuation orders while waiting for another forecast cycle.",
                "Shift logistics toward shelter expansion and staged transport for medically fragile populations.",
            ],
            "manufacturing_root_cause": [
                "Rollback recent firmware and isolate affected lines while validating sensor drift hypotheses.",
                "Continue full production while collecting two days of additional telemetry.",
                "Run controlled pilot recovery on one line before broad restart.",
            ],
            "regulatory_change_impact": [
                "Map top-risk obligations to existing controls and launch owner-assigned remediation sprints.",
                "Postpone control updates until formal audit request arrives.",
                "Implement interim compensating controls for unmet requirements within 30 days.",
            ],
            "contract_risk_negotiation": [
                "Counter with capped liability and narrow data-use rights tied to explicit purpose.",
                "Accept all high-risk clauses to preserve deal velocity.",
                "Offer phased concession package with reciprocal indemnity and audit rights.",
            ],
            "legacy_modern_migration": [
                "Start strangler migration on highest-change domains with parallel shadow traffic validation.",
                "Big-bang cutover in one weekend to minimize prolonged dual-run complexity.",
                "Sequence migration by dependency criticality and rollback readiness.",
            ],
            "contact_center_autopilot": [
                "Route high-friction billing cases to specialist queue with policy-safe instant credits.",
                "Apply standard scripts to all cases to maximize consistency.",
                "Use intent+risk triage to trigger personalized next-best-action with compliance checks.",
            ],
            "clinical_operations_optimizer": [
                "Prioritize discharge acceleration and flex staffing for highest acuity bottlenecks.",
                "Hold all non-emergency admissions until occupancy normalizes.",
                "Dynamically rebalance bed assignments by acuity and downstream capacity forecasts.",
            ],
        }
        return by_case.get(
            self.spec.use_case_id,
            [
                "Execute targeted containment on confirmed high-confidence entities first.",
                "Apply broad containment quickly with a rapid false-positive review cycle.",
                "Delay containment to gather additional evidence before major actions.",
            ],
        )

    def _compose_final_plan(
        self,
        anthropic_preview: str,
        ranked_actions: Sequence[CandidateRanking],
    ) -> str:
        top = ranked_actions[0].action if ranked_actions else "No prioritized action available."
        lines = [
            f"Use Case: {self.spec.title}",
            f"Objective: {self.spec.objective}",
            "",
            "Primary Action:",
            f"- {top}",
            "",
            "Reasoning Plan:",
            anthropic_preview.strip() or "- No reasoning plan available.",
        ]
        return "\n".join(lines).strip()

    @staticmethod
    def _extract_openai_preview(response: Any) -> str:
        # SDK objects vary by version; prefer safe attribute probes.
        text = getattr(response, "output_text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        if hasattr(response, "output"):
            output = getattr(response, "output") or []
            chunks: list[str] = []
            for item in output:
                content = getattr(item, "content", None) or []
                for block in content:
                    block_text = getattr(block, "text", None)
                    if block_text:
                        chunks.append(str(block_text))
            if chunks:
                return " ".join(chunks).strip()
        return str(response)[:500]

    @staticmethod
    def _extract_anthropic_preview(response: Any) -> str:
        content = getattr(response, "content", None)
        if content is None and isinstance(response, dict):
            content = response.get("content")
        if not content:
            return str(response)[:500]
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
            else:
                text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
        return " ".join(parts).strip() if parts else str(response)[:500]

    @staticmethod
    def _extract_cerebras_preview(response: Any) -> str:
        choices = getattr(response, "choices", None)
        if choices is None and isinstance(response, dict):
            choices = response.get("choices")
        if not choices:
            return str(response)[:500]
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
        content = (
            message.get("content")
            if isinstance(message, dict)
            else getattr(message, "content", None)
        )
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    value = block.get("text")
                else:
                    value = getattr(block, "text", None)
                if value:
                    parts.append(str(value))
            if parts:
                return " ".join(parts).strip()
        return str(response)[:500]

    @staticmethod
    def _simulate_openai_extraction(scenario: str) -> str:
        # Deterministic fallback extraction used when live API is unavailable.
        text = " ".join(scenario.split())
        return (
            "Structured extraction summary: "
            f"scenario_length={len(text)} chars; key_signals="
            "['high-priority event detected', 'requires cross-system validation']; "
            "risk_level='high'."
        )

    @staticmethod
    def _simulate_anthropic_plan(scenario: str) -> str:
        condensed = " ".join(scenario.split())[:220]
        return (
            "1) Validate scope and impact with telemetry/tool checks. "
            "2) Execute targeted containment and preserve forensic data. "
            "3) Confirm stabilization with monitoring queries. "
            f"Scenario focus: {condensed}"
        )
