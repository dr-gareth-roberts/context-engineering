from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from context_framework import ContextManager, OllamaChatAdapter, OllamaSDKBridge


DEFAULT_PROMPT = "Draft a concise incident update for an API latency spike."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["local", "cloud"], default="local")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--live", action="store_true", help="Execute an HTTP call.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def build_packet() -> object:
    manager = ContextManager(default_token_budget=1024, reserved_response_tokens=128)
    manager.add_system("You are an operations assistant. Be direct.")
    manager.add_memory("Prefer actionable bullets over paragraphs.", source="profile")
    manager.add_message("user", "Summarize current API incident status.")
    manager.add_document(
        "Telemetry: p95 latency increased 4x over baseline in us-east-1 during deploy.",
        source="telemetry",
        importance=0.8,
    )
    return manager.build_context("api incident")


def main() -> None:
    args = parse_args()
    cloud_mode = args.mode == "cloud"

    packet = build_packet()
    adapter = OllamaChatAdapter(cloud_mode=cloud_mode)
    bridge = OllamaSDKBridge.from_env()

    adapter_payload = adapter.request(
        packet,
        model=os.getenv("OLLAMA_MODEL", bridge.model),
        cloud_mode=cloud_mode,
        stream=False,
    )

    request_kwargs: dict[str, object] = {"stream": False}
    if cloud_mode:
        request_kwargs["max_tokens"] = 256
    else:
        request_kwargs["options"] = {"temperature": 0.2}

    request_payload = bridge.build_http_request(
        packet,
        prompt=args.prompt,
        cloud_mode=cloud_mode,
        **request_kwargs,
    )

    output: dict[str, object] = {
        "mode": args.mode,
        "adapter_payload": adapter_payload,
        "http_request": request_payload,
    }

    if args.live:
        try:
            response = bridge.create_with_httpx(
                packet,
                prompt=args.prompt,
                cloud_mode=cloud_mode,
                **request_kwargs,
            )
            output["live_response_preview"] = OllamaSDKBridge.parse_chat_text(response)[:240]
        except Exception as exc:  # pragma: no cover - live path
            output["live_error"] = str(exc)

    if args.json:
        print(json.dumps(output, indent=2))
        return

    print(f"Mode: {args.mode}")
    print(f"Endpoint: {request_payload['url']}")
    print("Adapter payload keys:", sorted(adapter_payload.keys()))
    if args.live:
        if "live_error" in output:
            print("Live call failed:", output["live_error"])
        else:
            print("Live response preview:", output["live_response_preview"])


if __name__ == "__main__":
    main()
