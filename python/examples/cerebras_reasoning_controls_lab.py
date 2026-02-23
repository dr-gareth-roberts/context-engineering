from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from context_framework import CerebrasSDKBridge, ContextManager


def _attr_or_key(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _build_packet():
    manager = ContextManager(default_token_budget=4096, reserved_response_tokens=600)
    manager.add_system("You are a principal engineer preparing reliability recommendations.")
    manager.add_document(
        "Always include migration risk, observability requirements, and rollback sequencing.",
        source="migration-guide",
        importance=0.8,
    )
    manager.add_message(
        "user",
        "Design a migration plan from fixed delays to exponential backoff retries.",
    )
    return manager.build_context("migration plan retries")


def _build_experiments(bridge: CerebrasSDKBridge, packet: Any) -> list[dict[str, Any]]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup_slo",
                "description": "Lookup SLO target and burn-rate policy by service name.",
                "parameters": {
                    "type": "object",
                    "properties": {"service": {"type": "string"}},
                    "required": ["service"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_incident_history",
                "description": "Fetch incident trends for a service over N days.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string"},
                        "days": {"type": "integer"},
                    },
                    "required": ["service", "days"],
                },
            },
        },
    ]

    configs = [
        {
            "name": "structured-json-with-reasoning",
            "kwargs": {
                "prompt": "Return an implementation plan as JSON with fields: steps, risks, rollback.",
                "response_format": {"type": "json_object"},
                "reasoning_effort": "high",
                "reasoning_format": "parsed",
                "clear_thinking": True,
                "max_completion_tokens": 280,
                "temperature": 0.0,
            },
        },
        {
            "name": "minimal-latency-no-reasoning",
            "kwargs": {
                "prompt": "Give the fastest actionable migration summary.",
                "disable_reasoning": True,
                "reasoning_format": "none",
                "max_completion_tokens": 180,
                "temperature": 0.1,
            },
        },
        {
            "name": "parallel-tool-orchestration",
            "kwargs": {
                "prompt": "Use tools to gather SLO and incident context before proposing the migration.",
                "tools": tools,
                "tool_choice": "auto",
                "parallel_tool_calls": True,
                "max_completion_tokens": 250,
            },
        },
    ]

    experiments: list[dict[str, Any]] = []
    for cfg in configs:
        payload = bridge.build_chat_request(packet, **cfg["kwargs"])
        experiments.append({"name": cfg["name"], "payload": payload, "kwargs": cfg["kwargs"]})
    return experiments


def _print_payload_highlights(experiments: list[dict[str, Any]]) -> None:
    print("Cerebras reasoning-control payload highlights:\n")
    for exp in experiments:
        payload = exp["payload"]
        summary = {
            "name": exp["name"],
            "model": payload.get("model"),
            "service_tier": payload.get("service_tier"),
            "reasoning_effort": payload.get("reasoning_effort"),
            "reasoning_format": payload.get("reasoning_format"),
            "disable_reasoning": payload.get("disable_reasoning"),
            "clear_thinking": payload.get("clear_thinking"),
            "parallel_tool_calls": payload.get("parallel_tool_calls"),
            "response_format": payload.get("response_format"),
            "max_completion_tokens": payload.get("max_completion_tokens"),
        }
        print(json.dumps(summary, indent=2))
        print()


def _run_live(bridge: CerebrasSDKBridge, packet: Any, experiments: list[dict[str, Any]]) -> None:
    from cerebras.cloud.sdk import Cerebras  # type: ignore

    client = Cerebras()
    print("Live Cerebras outputs:\n")
    for exp in experiments:
        name = exp["name"]
        kwargs = dict(exp["kwargs"])
        response = bridge.create_chat(client, packet, **kwargs)
        usage = _attr_or_key(response, "usage", {}) or {}
        total_tokens = _attr_or_key(usage, "total_tokens", "n/a")
        choices = _attr_or_key(response, "choices", []) or []
        if choices:
            message = _attr_or_key(choices[0], "message", {}) or {}
            content = _attr_or_key(message, "content", "")
            if isinstance(content, list):
                text = " ".join(
                    str(_attr_or_key(block, "text", "")) for block in content
                ).strip()
            else:
                text = str(content)
        else:
            text = ""

        print(f"- {name}:")
        print(f"  total_tokens={total_tokens}")
        print(f"  preview={text[:180]}")


def main() -> None:
    bridge = CerebrasSDKBridge(
        model="qwen-3-32b",
        service_tier="priority",
        reasoning_effort="medium",
        reasoning_format="parsed",
    )
    packet = _build_packet()
    experiments = _build_experiments(bridge, packet)
    _print_payload_highlights(experiments)

    if not os.getenv("CEREBRAS_API_KEY"):
        print("CEREBRAS_API_KEY not set. Dry-run only.")
        return

    try:
        _run_live(bridge, packet, experiments)
    except Exception as exc:  # pragma: no cover - optional live path
        print(f"Live Cerebras run failed: {exc}")


if __name__ == "__main__":
    main()
