from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from context_framework import (
    USE_CASE_INDEX,
    DeepAgentsBridge,
    LangGraphBridge,
    PydanticAIBridge,
    TriProviderPipeline,
)


def run_tri_provider_once() -> dict[str, object]:
    pipeline = TriProviderPipeline(USE_CASE_INDEX["soc_incident_commander"])
    node = LangGraphBridge.make_tri_provider_node(pipeline)
    return node(
        {
            "scenario": "Possible endpoint compromise and data staging on multiple hosts.",
            "evidence_documents": [
                "SIEM shows unusual process trees and outbound spikes.",
                "EDR flagged suspicious credential-dumping behavior.",
            ],
            "mode": "dry",
            "metadata": {"demo": "framework_bridge_lab"},
        }
    )


def run_deepagents_style_tool() -> dict[str, object]:
    pipeline = TriProviderPipeline(USE_CASE_INDEX["supply_chain_control_tower"])
    tool = DeepAgentsBridge.make_tri_provider_tool(pipeline)
    return tool(
        "Port disruption and supplier delays are compounding.",
        ["Lane ETA drifted by 72 hours for two primary lanes."],
        "dry",
    )


def run_pydantic_ai_style_tool() -> dict[str, object]:
    pipeline = TriProviderPipeline(USE_CASE_INDEX["regulatory_change_impact"])
    tool = PydanticAIBridge.make_tri_provider_tool(pipeline)
    return tool(
        "New cross-border data transfer obligations are effective in 30 days.",
        ["Control inventory has partial coverage for data residency."],
        "dry",
    )


def main() -> None:
    payload = {
        "langgraph_node_output": run_tri_provider_once(),
        "deepagents_tool_output": run_deepagents_style_tool(),
        "pydantic_ai_tool_output": run_pydantic_ai_style_tool(),
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
