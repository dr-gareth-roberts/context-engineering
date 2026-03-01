from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from context_framework import (
    AnthropicSDKBridge,
    CerebrasSDKBridge,
    ContextManager,
    OpenAIResponsesSDKBridge,
)


def build_context_packet() -> tuple[ContextManager, object]:
    manager = ContextManager(default_token_budget=2048, reserved_response_tokens=384)
    manager.add_system("You are a staff engineer. Be precise and brief.")
    manager.add_memory(
        "User preference: include one practical caveat in each answer.",
        source="profile",
        pinned=True,
    )
    manager.add_message("user", "What is an operationally safe retry strategy?")
    manager.add_document(
        "Recommended policy: exponential backoff with jitter, max-attempt cap, and idempotency keys.",
        source="reliability-guide",
        importance=0.8,
    )
    packet = manager.build_context("retry strategy")
    return manager, packet


def write_openai_batch_jsonl(path: Path) -> Path:
    openai_bridge = OpenAIResponsesSDKBridge(model="gpt-4.1-mini")
    requests = openai_bridge.build_batch_chat_requests(
        prompts=[
            "Explain idempotency keys in one paragraph.",
            "Give a 5-step rollout plan for retry policy changes.",
        ],
        system_prompt="You are a production reliability assistant.",
        custom_id_prefix="rare-batch",
    )
    lines = openai_bridge.to_batch_jsonl_lines(requests)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    manager, packet = build_context_packet()

    openai_bridge = OpenAIResponsesSDKBridge(
        model="gpt-4.1-mini",
        reasoning_effort="high",
        include_reasoning_summary=True,
    )
    openai_request = openai_bridge.build_response_request(
        packet,
        prompt="Answer the user and add one caveat.",
        enable_web_search=True,
        json_schema={
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "caveat": {"type": "string"},
            },
            "required": ["answer", "caveat"],
            "additionalProperties": False,
        },
        json_schema_name="retry_advice",
        metadata={"workflow": "rare-sdk-demo"},
    )
    print("OpenAI request payload:")
    print(json.dumps(openai_request, indent=2))

    anthropic_bridge = AnthropicSDKBridge(
        model="claude-3-7-sonnet-latest",
        max_tokens=700,
        enable_prompt_cache=True,
        enable_thinking=True,
        thinking_budget_tokens=512,
    )
    anthropic_request = anthropic_bridge.build_message_request(
        packet,
        tools=[
            {
                "name": "search_runbooks",
                "description": "Search reliability runbooks by keyword.",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ],
        tool_choice={"type": "auto"},
        metadata={"workflow": "rare-sdk-demo"},
    )
    print("\nAnthropic request payload:")
    print(json.dumps(anthropic_request, indent=2))

    cerebras_bridge = CerebrasSDKBridge(
        model="qwen-3-32b",
        service_tier="priority",
        reasoning_effort="low",
        reasoning_format="parsed",
    )
    cerebras_chat_request = cerebras_bridge.build_chat_request(
        packet,
        prompt="Answer with one caveat and an implementation warning.",
        max_tokens=320,
        logprobs=True,
        top_logprobs=3,
    )
    print("\nCerebras chat request payload:")
    print(json.dumps(cerebras_chat_request, indent=2))

    speculative_request = cerebras_bridge.build_chat_request(
        packet,
        prompt="Regenerate the policy doc with one extra warning section.",
        prediction=(
            "Retry Policy\n\n1) Use exponential backoff.\n"
            "2) Cap max attempts.\n"
            "3) Require idempotency keys.\n"
        ),
        max_tokens=320,
    )
    print("\nCerebras speculative-decoding request payload:")
    print(json.dumps(speculative_request, indent=2))

    cerebras_perplexity_request = cerebras_bridge.build_perplexity_request(
        "Reliable retries use exponential backoff and idempotency keys."
    )
    print("\nCerebras perplexity request payload:")
    print(json.dumps(cerebras_perplexity_request, indent=2))

    batch_file = write_openai_batch_jsonl(
        Path(tempfile.gettempdir()) / "openai_rare_features_batch.jsonl"
    )
    print(f"\nWrote OpenAI batch input file to: {batch_file}")

    # Optional live calls when SDKs + keys are configured.
    if os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI  # type: ignore

            client = OpenAI()
            # Underused flow: upload JSONL and start async batch.
            uploaded = client.files.create(
                file=open(batch_file, "rb"),
                purpose="batch",
            )
            batch = client.batches.create(
                input_file_id=uploaded.id,
                endpoint="/v1/chat/completions",
                completion_window="24h",
                metadata={"workflow": "rare-sdk-demo"},
            )
            print(f"Started OpenAI batch job: {batch.id}")
        except Exception as exc:  # pragma: no cover - optional runtime integration
            print(f"OpenAI live call skipped/failed: {exc}")
    else:
        print("OPENAI_API_KEY not set. Skipping live OpenAI call.")

    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            from anthropic import Anthropic  # type: ignore

            client = Anthropic()
            response = anthropic_bridge.create(client, packet)
            tool_uses = anthropic_bridge.extract_tool_uses(response)
            print(f"Anthropic response received. Tool uses: {len(tool_uses)}")
        except Exception as exc:  # pragma: no cover - optional runtime integration
            print(f"Anthropic live call skipped/failed: {exc}")
    else:
        print("ANTHROPIC_API_KEY not set. Skipping live Anthropic call.")

    if os.getenv("CEREBRAS_API_KEY"):
        try:
            from cerebras.cloud.sdk import Cerebras  # type: ignore

            client = Cerebras()
            chat_response = cerebras_bridge.create_chat(client, packet, max_tokens=256)
            content = chat_response.choices[0].message.content  # type: ignore[index]
            if isinstance(content, list):
                first_text = " ".join(
                    str(block.get("text", "")) if isinstance(block, dict) else str(block)
                    for block in content
                )
            else:
                first_text = str(content)
            print(f"Cerebras chat response preview: {first_text[:120]}")

            speculative_response = cerebras_bridge.create_speculative_chat(
                client,
                packet,
                predicted_output=(
                    "Retry Policy\n\n1) Use exponential backoff.\n"
                    "2) Cap max attempts.\n"
                    "3) Require idempotency keys.\n"
                ),
                prompt="Regenerate with one extra warning section.",
                max_tokens=320,
            )
            metrics = cerebras_bridge.extract_speculative_decoding_metrics(speculative_response)
            if metrics is not None:
                print(
                    "Cerebras speculative metrics:",
                    f"accepted={metrics.accepted_prediction_tokens}",
                    f"rejected={metrics.rejected_prediction_tokens}",
                    f"acceptance_rate={metrics.acceptance_rate:.2%}",
                )

            perplexity = cerebras_bridge.score_perplexity(
                client,
                "Reliable retries use exponential backoff and idempotency keys.",
            )
            print(
                "Cerebras perplexity score:",
                f"ppl={perplexity.perplexity:.4f}",
                f"tokens={perplexity.token_count}",
            )
        except Exception as exc:  # pragma: no cover - optional runtime integration
            print(f"Cerebras live call skipped/failed: {exc}")
    else:
        print("CEREBRAS_API_KEY not set. Skipping live Cerebras call.")

    # Keep manager referenced to show how this sits in the full framework flow.
    _ = manager


if __name__ == "__main__":
    main()
