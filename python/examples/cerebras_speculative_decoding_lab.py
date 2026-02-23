from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from context_framework import CerebrasSDKBridge, ContextManager


def _as_plain_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict):
                chunks.append(str(block.get("text", "")))
            else:
                chunks.append(str(block))
        return " ".join(chunk for chunk in chunks if chunk).strip()
    return str(content)


def _build_packet():
    manager = ContextManager(default_token_budget=4096, reserved_response_tokens=512)
    manager.add_system("You are a senior SRE writing production runbooks.")
    manager.add_document(
        "Runbooks must include rollback steps, blast-radius constraints, and paging impact.",
        source="runbook-style-guide",
        importance=0.8,
    )
    manager.add_message(
        "user",
        "Regenerate the retry-policy runbook section with one extra risk warning.",
    )
    return manager.build_context("retry policy runbook")


def _baseline_and_speculative_payloads(
    bridge: CerebrasSDKBridge,
    packet: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    predicted_scaffold = (
        "Retry Policy (Draft)\n\n"
        "1. Use exponential backoff with jitter.\n"
        "2. Cap retries to prevent retry storms.\n"
        "3. Require idempotency keys for side-effecting operations.\n"
    )

    baseline = bridge.build_chat_request(
        packet,
        prompt="Add rollback guidance and one risk warning section.",
        max_completion_tokens=350,
        temperature=0.1,
        service_tier=bridge.service_tier,
    )
    speculative = bridge.build_chat_request(
        packet,
        prompt="Add rollback guidance and one risk warning section.",
        prediction=predicted_scaffold,
        max_completion_tokens=350,
        temperature=0.1,
    )
    return baseline, speculative


def _run_live(bridge: CerebrasSDKBridge, packet: Any) -> None:
    from cerebras.cloud.sdk import Cerebras  # type: ignore

    client = Cerebras()
    predicted_scaffold = (
        "Retry Policy (Draft)\n\n"
        "1. Use exponential backoff with jitter.\n"
        "2. Cap retries to prevent retry storms.\n"
        "3. Require idempotency keys for side-effecting operations.\n"
    )

    started = time.perf_counter()
    baseline = bridge.create_chat(
        client,
        packet,
        prompt="Add rollback guidance and one risk warning section.",
        max_completion_tokens=350,
        temperature=0.1,
    )
    baseline_s = time.perf_counter() - started

    started = time.perf_counter()
    speculative = bridge.create_speculative_chat(
        client,
        packet,
        predicted_output=predicted_scaffold,
        prompt="Add rollback guidance and one risk warning section.",
        max_completion_tokens=350,
        temperature=0.1,
    )
    speculative_s = time.perf_counter() - started

    baseline_content = baseline.choices[0].message.content  # type: ignore[index]
    speculative_content = speculative.choices[0].message.content  # type: ignore[index]
    baseline_preview = _as_plain_text(baseline_content)[:180]
    speculative_preview = _as_plain_text(speculative_content)[:180]

    metrics = bridge.extract_speculative_decoding_metrics(speculative)
    print("\nLive Results")
    print(f"- Baseline latency: {baseline_s:.3f}s")
    print(f"- Speculative latency: {speculative_s:.3f}s")
    if speculative_s > 0:
        print(f"- Speed ratio (baseline/spec): {baseline_s / speculative_s:.2f}x")
    print(f"- Baseline preview: {baseline_preview}")
    print(f"- Speculative preview: {speculative_preview}")
    if metrics:
        print(
            "- Speculative token acceptance:",
            f"{metrics.accepted_prediction_tokens}/{metrics.total_prediction_tokens}",
            f"({metrics.acceptance_rate:.2%})",
        )
    else:
        print("- No speculative acceptance metrics returned.")


def main() -> None:
    bridge = CerebrasSDKBridge(
        model="qwen-3-32b",
        service_tier="priority",
        reasoning_effort="low",
        reasoning_format="parsed",
    )
    packet = _build_packet()
    baseline, speculative = _baseline_and_speculative_payloads(bridge, packet)

    print("Baseline Cerebras payload (excerpt):")
    print(
        json.dumps(
            {
                "model": baseline["model"],
                "service_tier": baseline["service_tier"],
                "reasoning_effort": baseline["reasoning_effort"],
                "max_completion_tokens": baseline.get("max_completion_tokens"),
            },
            indent=2,
        )
    )
    print("\nSpeculative Cerebras payload (excerpt):")
    print(
        json.dumps(
            {
                "prediction": speculative.get("prediction"),
                "max_completion_tokens": speculative.get("max_completion_tokens"),
            },
            indent=2,
        )
    )

    if not os.getenv("CEREBRAS_API_KEY"):
        print("\nCEREBRAS_API_KEY not set. Dry-run only.")
        return

    try:
        _run_live(bridge, packet)
    except Exception as exc:  # pragma: no cover - optional live path
        print(f"\nLive Cerebras run failed: {exc}")


if __name__ == "__main__":
    main()
