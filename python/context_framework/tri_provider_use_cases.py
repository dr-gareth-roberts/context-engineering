from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class OpenAIStageSpec:
    model: str
    prompt: str
    json_schema_name: str
    json_schema: dict[str, Any]
    enable_web_search: bool = False
    reasoning_effort: str = "medium"


@dataclass(slots=True, frozen=True)
class AnthropicStageSpec:
    model: str
    prompt: str
    max_tokens: int
    tools: tuple[dict[str, Any], ...] = ()
    tool_choice: dict[str, Any] | None = None
    enable_prompt_cache: bool = True
    enable_thinking: bool = True
    thinking_budget_tokens: int = 512


@dataclass(slots=True, frozen=True)
class CerebrasStageSpec:
    model: str
    prompt: str
    service_tier: str = "priority"
    reasoning_effort: str = "low"
    reasoning_format: str = "parsed"
    max_completion_tokens: int = 320
    speculative_seed: str = ""
    candidate_actions: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class TriProviderUseCaseSpec:
    use_case_id: str
    title: str
    objective: str
    system_prompt: str
    openai: OpenAIStageSpec
    anthropic: AnthropicStageSpec
    cerebras: CerebrasStageSpec
    default_documents: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.use_case_id.strip():
            raise ValueError("use_case_id cannot be empty")
        if not self.title.strip():
            raise ValueError("title cannot be empty")
        if not self.objective.strip():
            raise ValueError("objective cannot be empty")
        if not self.system_prompt.strip():
            raise ValueError("system_prompt cannot be empty")


def _risk_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "executive_summary": {"type": "string"},
            "key_signals": {
                "type": "array",
                "items": {"type": "string"},
            },
            "risk_level": {
                "type": "string",
                "enum": ["low", "medium", "high", "critical"],
            },
            "immediate_actions": {
                "type": "array",
                "items": {"type": "string"},
            },
            "monitoring_queries": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "executive_summary",
            "key_signals",
            "risk_level",
            "immediate_actions",
            "monitoring_queries",
        ],
        "additionalProperties": False,
    }


USE_CASES: tuple[TriProviderUseCaseSpec, ...] = (
    TriProviderUseCaseSpec(
        use_case_id="soc_incident_commander",
        title="SOC Incident Commander",
        objective=(
            "Fuse security telemetry and external intel, propose containment options, "
            "and dispatch a fastest-safe response plan."
        ),
        system_prompt=(
            "You are an incident commander for enterprise security operations. "
            "Prioritize containment speed, evidentiary integrity, and business continuity."
        ),
        default_documents=(
            "Containment policy: isolate impacted identities and endpoints before broad takedown.",
            "Escalation policy: page legal/comms for critical incidents with customer impact.",
            "Post-incident requirement: capture detection gaps and compensating controls.",
        ),
        openai=OpenAIStageSpec(
            model="gpt-4.1-mini",
            prompt=(
                "Extract the attack narrative, confidence level, impacted assets, "
                "and likely blast radius from the provided incident context."
            ),
            json_schema_name="soc_triage",
            json_schema=_risk_schema(),
            enable_web_search=True,
            reasoning_effort="high",
        ),
        anthropic=AnthropicStageSpec(
            model="claude-3-7-sonnet-latest",
            prompt=(
                "Build a stepwise investigation and containment plan. "
                "Use available tools for SIEM, EDR, and IAM checks before final actions."
            ),
            max_tokens=900,
            tools=(
                {
                    "name": "siem_query",
                    "description": "Run a SIEM query and return suspicious event clusters.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
                {
                    "name": "edr_isolate_host",
                    "description": "Isolate a host in the endpoint platform.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"hostname": {"type": "string"}},
                        "required": ["hostname"],
                    },
                },
                {
                    "name": "iam_suspend_user",
                    "description": "Suspend a compromised user account.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"user_id": {"type": "string"}},
                        "required": ["user_id"],
                    },
                },
            ),
            tool_choice={"type": "auto"},
            enable_prompt_cache=True,
            enable_thinking=True,
            thinking_budget_tokens=700,
        ),
        cerebras=CerebrasStageSpec(
            model="qwen-3-32b",
            prompt=(
                "Generate a 15-minute action plan with explicit owner assignment "
                "and rollback criteria for each step."
            ),
            service_tier="priority",
            reasoning_effort="low",
            reasoning_format="parsed",
            max_completion_tokens=340,
            speculative_seed=(
                "Incident Response Plan (Draft)\n"
                "1. Confirm affected accounts and hosts.\n"
                "2. Isolate suspicious endpoints.\n"
                "3. Suspend compromised identities.\n"
                "4. Validate containment and monitor for reentry.\n"
            ),
            candidate_actions=(
                "Immediate broad isolation of all suspected hosts, then review false positives.",
                "Targeted identity suspension and endpoint isolation based on high-confidence indicators first.",
                "Monitor-only mode for 30 minutes before containment to gather more evidence.",
            ),
        ),
    ),
    TriProviderUseCaseSpec(
        use_case_id="catastrophe_claims_pipeline",
        title="Catastrophe Insurance Claims Pipeline",
        objective="Triage and prioritize surge claims with fraud and policy-awareness.",
        system_prompt="You are a catastrophe claims operations copilot for an insurance carrier.",
        default_documents=("Prioritize life/safety claims before property-only claims.",),
        openai=OpenAIStageSpec(
            model="gpt-4.1-mini",
            prompt="Extract claim severity, fraud indicators, and policy applicability signals.",
            json_schema_name="claims_triage",
            json_schema=_risk_schema(),
        ),
        anthropic=AnthropicStageSpec(
            model="claude-3-7-sonnet-latest",
            prompt="Create an adjudication and fraud-review workflow with tool checks.",
            max_tokens=700,
        ),
        cerebras=CerebrasStageSpec(
            model="qwen-3-32b",
            prompt="Produce a fast priority queue policy and customer communication sequence.",
        ),
    ),
    TriProviderUseCaseSpec(
        use_case_id="supply_chain_control_tower",
        title="Supply Chain Disruption Control Tower",
        objective="Detect supply disruptions and coordinate mitigation plans.",
        system_prompt="You are a global supply chain resilience analyst.",
        openai=OpenAIStageSpec(
            model="gpt-4.1-mini",
            prompt="Extract disruption signals, impacted lanes, and expected delay windows.",
            json_schema_name="supply_disruption",
            json_schema=_risk_schema(),
        ),
        anthropic=AnthropicStageSpec(
            model="claude-3-7-sonnet-latest",
            prompt="Design mitigations across inventory, logistics, and supplier alternatives.",
            max_tokens=700,
        ),
        cerebras=CerebrasStageSpec(
            model="qwen-3-32b",
            prompt="Emit rapid rerouting and allocation decisions with explicit tradeoffs.",
        ),
    ),
    TriProviderUseCaseSpec(
        use_case_id="aml_kyc_fincrime",
        title="AML/KYC Financial Crime Copilot",
        objective="Investigate suspicious activity while preserving compliance controls.",
        system_prompt="You are an AML investigator assistant focused on explainability.",
        openai=OpenAIStageSpec(
            model="gpt-4.1-mini",
            prompt="Extract suspicious entities, transaction patterns, and typology hints.",
            json_schema_name="aml_triage",
            json_schema=_risk_schema(),
        ),
        anthropic=AnthropicStageSpec(
            model="claude-3-7-sonnet-latest",
            prompt="Create a case investigation plan with SAR-relevant evidence structure.",
            max_tokens=700,
        ),
        cerebras=CerebrasStageSpec(
            model="qwen-3-32b",
            prompt="Prioritize cases for escalation with fast rationale summaries.",
        ),
    ),
    TriProviderUseCaseSpec(
        use_case_id="pharmacovigilance_events",
        title="Pharmacovigilance Event Detection",
        objective="Detect and prioritize adverse events from multimodal sources.",
        system_prompt="You are a pharmacovigilance operations copilot.",
        openai=OpenAIStageSpec(
            model="gpt-4.1-mini",
            prompt="Extract adverse event candidates, confidence, and patient safety impact.",
            json_schema_name="adverse_event_triage",
            json_schema=_risk_schema(),
        ),
        anthropic=AnthropicStageSpec(
            model="claude-3-7-sonnet-latest",
            prompt="Generate case-processing and regulatory reporting recommendations.",
            max_tokens=700,
        ),
        cerebras=CerebrasStageSpec(
            model="qwen-3-32b",
            prompt="Produce high-throughput priority ordering for event review teams.",
        ),
    ),
    TriProviderUseCaseSpec(
        use_case_id="grid_outage_response",
        title="Grid Outage Response Orchestration",
        objective="Coordinate safe restoration plans under outage pressure.",
        system_prompt="You are a power grid outage response planner.",
        openai=OpenAIStageSpec(
            model="gpt-4.1-mini",
            prompt="Extract outage scope, critical infrastructure impact, and restoration risks.",
            json_schema_name="grid_outage_triage",
            json_schema=_risk_schema(),
        ),
        anthropic=AnthropicStageSpec(
            model="claude-3-7-sonnet-latest",
            prompt="Plan restoration sequence with dependency-aware safety checks.",
            max_tokens=700,
        ),
        cerebras=CerebrasStageSpec(
            model="qwen-3-32b",
            prompt="Generate minute-by-minute dispatch priorities for restoration crews.",
        ),
    ),
    TriProviderUseCaseSpec(
        use_case_id="emergency_operations_center",
        title="Emergency Operations Center",
        objective="Synthesize disaster intelligence and coordinate public safety response.",
        system_prompt="You are an emergency operations planning assistant.",
        openai=OpenAIStageSpec(
            model="gpt-4.1-mini",
            prompt="Extract hazard zones, vulnerable populations, and logistics bottlenecks.",
            json_schema_name="eoc_triage",
            json_schema=_risk_schema(),
        ),
        anthropic=AnthropicStageSpec(
            model="claude-3-7-sonnet-latest",
            prompt="Build evacuation/resource plans with justifications and fallback options.",
            max_tokens=700,
        ),
        cerebras=CerebrasStageSpec(
            model="qwen-3-32b",
            prompt="Produce rapid priority updates for field coordinators.",
        ),
    ),
    TriProviderUseCaseSpec(
        use_case_id="manufacturing_root_cause",
        title="Manufacturing Root Cause and Recovery",
        objective="Diagnose production anomalies and minimize downtime.",
        system_prompt="You are an industrial reliability engineer assistant.",
        openai=OpenAIStageSpec(
            model="gpt-4.1-mini",
            prompt="Extract anomaly signatures, likely causes, and affected production lines.",
            json_schema_name="manufacturing_anomaly",
            json_schema=_risk_schema(),
        ),
        anthropic=AnthropicStageSpec(
            model="claude-3-7-sonnet-latest",
            prompt="Design diagnostic workflow and safe recovery playbook.",
            max_tokens=700,
        ),
        cerebras=CerebrasStageSpec(
            model="qwen-3-32b",
            prompt="Rank remediation actions by speed-to-stability and risk.",
        ),
    ),
    TriProviderUseCaseSpec(
        use_case_id="regulatory_change_impact",
        title="Regulatory Change Impact Engine",
        objective="Map new regulations to controls and prioritized remediation.",
        system_prompt="You are a regulatory change analysis assistant.",
        openai=OpenAIStageSpec(
            model="gpt-4.1-mini",
            prompt="Extract new obligations, timelines, and impacted policy areas.",
            json_schema_name="reg_change",
            json_schema=_risk_schema(),
        ),
        anthropic=AnthropicStageSpec(
            model="claude-3-7-sonnet-latest",
            prompt="Create control-mapping and remediation sequencing plan.",
            max_tokens=700,
        ),
        cerebras=CerebrasStageSpec(
            model="qwen-3-32b",
            prompt="Generate high-frequency reprioritization guidance as requirements evolve.",
        ),
    ),
    TriProviderUseCaseSpec(
        use_case_id="contract_risk_negotiation",
        title="Contract Risk Negotiation Assistant",
        objective="Assess clause risk and draft negotiation alternatives.",
        system_prompt="You are a contract risk and negotiation copilot.",
        openai=OpenAIStageSpec(
            model="gpt-4.1-mini",
            prompt="Extract risky clauses, obligations, and fallback terms.",
            json_schema_name="contract_risk",
            json_schema=_risk_schema(),
        ),
        anthropic=AnthropicStageSpec(
            model="claude-3-7-sonnet-latest",
            prompt="Propose negotiation strategy with legal/commercial rationale.",
            max_tokens=700,
        ),
        cerebras=CerebrasStageSpec(
            model="qwen-3-32b",
            prompt="Generate and rank alternative clause drafts quickly.",
        ),
    ),
    TriProviderUseCaseSpec(
        use_case_id="legacy_modern_migration",
        title="Legacy-to-Modern Migration Factory",
        objective="Plan and execute safe, staged modernization.",
        system_prompt="You are a software modernization architect assistant.",
        openai=OpenAIStageSpec(
            model="gpt-4.1-mini",
            prompt="Extract legacy dependencies, migration blockers, and sequencing hints.",
            json_schema_name="migration_triage",
            json_schema=_risk_schema(),
        ),
        anthropic=AnthropicStageSpec(
            model="claude-3-7-sonnet-latest",
            prompt="Create phased migration plan with testing and rollback gates.",
            max_tokens=700,
        ),
        cerebras=CerebrasStageSpec(
            model="qwen-3-32b",
            prompt="Rapidly generate candidate refactor plans and rank for execution.",
        ),
    ),
    TriProviderUseCaseSpec(
        use_case_id="contact_center_autopilot",
        title="Contact Center Resolution Autopilot",
        objective="Improve resolution speed while maintaining policy compliance.",
        system_prompt="You are a customer operations quality and resolution assistant.",
        openai=OpenAIStageSpec(
            model="gpt-4.1-mini",
            prompt="Extract customer intent, sentiment, risk, and policy constraints.",
            json_schema_name="contact_center_triage",
            json_schema=_risk_schema(),
        ),
        anthropic=AnthropicStageSpec(
            model="claude-3-7-sonnet-latest",
            prompt="Plan compliant resolution actions and tool workflow.",
            max_tokens=700,
        ),
        cerebras=CerebrasStageSpec(
            model="qwen-3-32b",
            prompt="Draft low-latency response options and rank next-best-actions.",
        ),
    ),
    TriProviderUseCaseSpec(
        use_case_id="clinical_operations_optimizer",
        title="Clinical Operations Optimizer",
        objective="Prioritize interventions and staffing actions in near real-time.",
        system_prompt="You are a clinical operations optimization assistant.",
        openai=OpenAIStageSpec(
            model="gpt-4.1-mini",
            prompt="Extract patient flow bottlenecks, care risk, and staffing signals.",
            json_schema_name="clinical_ops_triage",
            json_schema=_risk_schema(),
        ),
        anthropic=AnthropicStageSpec(
            model="claude-3-7-sonnet-latest",
            prompt="Create intervention plan with protocol-aware safeguards.",
            max_tokens=700,
        ),
        cerebras=CerebrasStageSpec(
            model="qwen-3-32b",
            prompt="Produce fast reprioritization suggestions for bed/staff allocation.",
        ),
    ),
    TriProviderUseCaseSpec(
        use_case_id="text_governance_orchestrator",
        title="Cross-Channel Text Governance Orchestrator",
        objective=(
            "Sanitize, standardize, and approve high-risk outbound text while preserving intent, "
            "policy compliance, and channel-specific clarity."
        ),
        system_prompt=(
            "You are a communications governance assistant for regulated enterprises. "
            "Prioritize privacy protection, policy conformance, and concise customer-safe language."
        ),
        default_documents=(
            "Outbound messaging policy: remove sensitive personal data and internal-only operational details.",
            "Voice/tone policy: preserve factual precision, avoid speculation, and keep channel-appropriate brevity.",
            "Approval policy: any legal/regulatory uncertainty must be escalated for human review before send.",
        ),
        openai=OpenAIStageSpec(
            model="gpt-4.1-mini",
            prompt=(
                "Extract policy risks, sensitive data markers, channel constraints, and severity from the text context."
            ),
            json_schema_name="text_governance_risk",
            json_schema=_risk_schema(),
            reasoning_effort="high",
        ),
        anthropic=AnthropicStageSpec(
            model="claude-3-7-sonnet-latest",
            prompt=(
                "Design a deterministic transform-and-review workflow using text-normalization, redaction, "
                "and policy-check tools before publication."
            ),
            max_tokens=900,
            tools=(
                {
                    "name": "normalize_text",
                    "description": "Normalize whitespace and structural formatting for deterministic processing.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
                {
                    "name": "redact_sensitive",
                    "description": "Redact PII and sensitive strings before external publication.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
                {
                    "name": "policy_clause_lookup",
                    "description": "Retrieve relevant communication policy clauses by topic.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"topic": {"type": "string"}},
                        "required": ["topic"],
                    },
                },
            ),
            tool_choice={"type": "auto"},
            enable_prompt_cache=True,
            enable_thinking=True,
            thinking_budget_tokens=600,
        ),
        cerebras=CerebrasStageSpec(
            model="qwen-3-32b",
            prompt=(
                "Generate low-latency channel-specific rewrites (email, status-page, in-app banner) and rank "
                "options by compliance confidence and clarity."
            ),
            service_tier="priority",
            reasoning_effort="low",
            reasoning_format="parsed",
            max_completion_tokens=340,
            speculative_seed=(
                "Governed Message Draft\n"
                "1) Remove sensitive tokens and internal references.\n"
                "2) Preserve customer-facing facts and impact window.\n"
                "3) Apply channel-specific tone and length constraints.\n"
                "4) Flag uncertainties for human legal review.\n"
            ),
            candidate_actions=(
                "Publish a concise customer-safe notice after deterministic redaction and policy checks.",
                "Delay publication until full legal review despite available compliant draft options.",
                "Generate channel-specific variants and route medium-risk segments for partial human approval.",
            ),
        ),
    ),
)


USE_CASE_INDEX: dict[str, TriProviderUseCaseSpec] = {spec.use_case_id: spec for spec in USE_CASES}


def validate_use_case_catalog(
    use_cases: tuple[TriProviderUseCaseSpec, ...] = USE_CASES,
) -> None:
    ids = [spec.use_case_id for spec in use_cases]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate use_case_id values detected in catalog")
    if len(use_cases) < 10:
        raise ValueError("Catalog must include at least 10 advanced use cases")
    for spec in use_cases:
        if not spec.openai.json_schema.get("required"):
            raise ValueError(f"{spec.use_case_id} must define required json schema fields")
        if spec.anthropic.max_tokens < 300:
            raise ValueError(f"{spec.use_case_id} anthropic max_tokens must be at least 300")
        if spec.cerebras.max_completion_tokens < 200:
            raise ValueError(
                f"{spec.use_case_id} cerebras max_completion_tokens must be at least 200"
            )
