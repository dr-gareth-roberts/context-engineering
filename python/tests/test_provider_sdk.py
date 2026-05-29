from __future__ import annotations

import json
import math
import os
import unittest
from unittest.mock import patch

from context_framework import (
    AnthropicSDKBridge,
    CerebrasSDKBridge,
    ContextItem,
    ContextKind,
    ContextManager,
    ContextPacket,
    OllamaSDKBridge,
    OpenAIResponsesSDKBridge,
)


class ProviderSDKBridgeTests(unittest.TestCase):
    def _packet(self):
        manager = ContextManager(default_token_budget=140, reserved_response_tokens=20)
        manager.add_system("Be concise.")
        manager.add_memory("User likes caveats.", source="profile", pinned=True)
        manager.add_message("user", "How should retry backoff work?")
        manager.add_message("assistant", "Use exponential delay with jitter.")
        manager.add_document(
            "Retry strategy: exponential backoff with cap and idempotency keys.",
            source="runbook",
        )
        return manager.build_context("retry"), manager

    def test_openai_response_request_uses_rare_fields(self) -> None:
        packet, _ = self._packet()
        bridge = OpenAIResponsesSDKBridge(
            model="gpt-4.1-mini",
            reasoning_effort="high",
            include_reasoning_summary=True,
        )
        request = bridge.build_response_request(
            packet,
            prompt="Answer and add one caveat.",
            enable_web_search=True,
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
            json_schema_name="result",
            prediction_text="The short answer is",
            metadata={"workflow": "tests"},
        )

        self.assertEqual(request["model"], "gpt-4.1-mini")
        self.assertEqual(request["reasoning"]["effort"], "high")
        self.assertEqual(request["reasoning"]["summary"], "auto")
        self.assertEqual(request["truncation"], "auto")
        self.assertTrue(request["store"])
        self.assertEqual(request["tools"][0]["type"], "web_search_preview")
        self.assertEqual(request["text"]["format"]["name"], "result")
        self.assertIn("input", request)
        self.assertEqual(request["prediction"]["type"], "content")

    def test_openai_batch_jsonl_generation(self) -> None:
        bridge = OpenAIResponsesSDKBridge(model="gpt-4o-mini")
        requests = bridge.build_batch_chat_requests(
            prompts=["one", "two"],
            system_prompt="system",
            custom_id_prefix="batch",
        )
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["custom_id"], "batch-0")
        self.assertEqual(requests[0]["url"], "/v1/chat/completions")
        lines = bridge.to_batch_jsonl_lines(requests)
        self.assertEqual(len(lines), 2)
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["body"]["model"], "gpt-4o-mini")

    def test_anthropic_message_request_uses_cache_and_thinking(self) -> None:
        packet, _ = self._packet()
        bridge = AnthropicSDKBridge(
            model="claude-3-7-sonnet-latest",
            max_tokens=700,
            enable_prompt_cache=True,
            enable_thinking=True,
            thinking_budget_tokens=500,
        )
        request = bridge.build_message_request(
            packet,
            tools=[
                {
                    "name": "search_docs",
                    "description": "Search docs",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                }
            ],
            tool_choice={"type": "auto"},
            metadata={"workflow": "tests"},
        )

        self.assertEqual(request["model"], "claude-3-7-sonnet-latest")
        self.assertEqual(request["max_tokens"], 700)
        self.assertEqual(request["thinking"]["type"], "enabled")
        self.assertEqual(request["thinking"]["budget_tokens"], 500)
        self.assertIn("system", request)
        # Anthropic allows at most 4 cache_control breakpoints; the bridge must
        # not tag every block (that would exceed the limit and 400). With prompt
        # caching enabled and no evidence docs in this packet, exactly one
        # breakpoint should land on the last (stable) system block.
        cache_breakpoints = sum(1 for block in request["system"] if block.get("cache_control"))
        self.assertLessEqual(cache_breakpoints, 4)
        self.assertEqual(cache_breakpoints, 1)
        self.assertEqual(request["system"][-1].get("cache_control", {}).get("type"), "ephemeral")
        self.assertEqual(request["tool_choice"]["type"], "auto")
        self.assertTrue(len(request["messages"]) >= 1)

    def test_anthropic_caps_cache_control_to_one_stable_breakpoint(self) -> None:
        # Realistic packet: 1 system + 1 pinned memory + 3 default docs + 2
        # per-request evidence docs => 7 system blocks. Tagging all of them
        # exceeds Anthropic's hard limit of 4 cache_control breakpoints and
        # triggers a 400. Exactly one breakpoint must be emitted, and it must
        # land on the last STABLE block (the last default doc), never on a
        # volatile evidence doc, so the cached prefix stays constant.
        items = [
            ContextItem(text="System prompt", kind=ContextKind.SYSTEM, source="use-case:x"),
            ContextItem(text="Objective", kind=ContextKind.MEMORY, source="objective", pinned=True),
            ContextItem(text="Default 0", kind=ContextKind.DOCUMENT, source="default-doc-0"),
            ContextItem(text="Default 1", kind=ContextKind.DOCUMENT, source="default-doc-1"),
            ContextItem(text="Default 2", kind=ContextKind.DOCUMENT, source="default-doc-2"),
            ContextItem(text="Evidence 0", kind=ContextKind.DOCUMENT, source="evidence-doc-0"),
            ContextItem(text="Evidence 1", kind=ContextKind.DOCUMENT, source="evidence-doc-1"),
            ContextItem(text="Question?", kind=ContextKind.MESSAGE, role="user"),
        ]
        packet = ContextPacket(items=items, used_tokens=0, token_budget=10_000)
        bridge = AnthropicSDKBridge(enable_prompt_cache=True)
        request = bridge.build_message_request(packet)

        system_blocks = request["system"]
        self.assertEqual(len(system_blocks), 7)
        tagged = [b for b in system_blocks if b.get("cache_control")]
        self.assertEqual(len(tagged), 1)
        self.assertLessEqual(len(tagged), 4)
        # The single breakpoint sits on the last default doc (the last stable
        # block before the evidence docs), not on an evidence doc.
        breakpoint_index = next(i for i, b in enumerate(system_blocks) if b.get("cache_control"))
        self.assertEqual(breakpoint_index, 4)
        self.assertNotIn("Evidence", system_blocks[breakpoint_index]["text"])

    def test_anthropic_no_cache_control_when_disabled(self) -> None:
        items = [
            ContextItem(text="System prompt", kind=ContextKind.SYSTEM, source="use-case:x"),
            ContextItem(text="Evidence 0", kind=ContextKind.DOCUMENT, source="evidence-doc-0"),
        ]
        packet = ContextPacket(items=items, used_tokens=0, token_budget=10_000)
        bridge = AnthropicSDKBridge(enable_prompt_cache=False)
        request = bridge.build_message_request(packet)
        self.assertFalse(any(b.get("cache_control") for b in request["system"]))

    def test_anthropic_extract_tool_uses(self) -> None:
        response = {
            "content": [
                {"type": "text", "text": "Checking..."},
                {
                    "type": "tool_use",
                    "id": "toolu_123",
                    "name": "search_docs",
                    "input": {"query": "retry policy"},
                },
            ]
        }
        calls = AnthropicSDKBridge.extract_tool_uses(response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "search_docs")
        self.assertEqual(calls[0]["input"]["query"], "retry policy")

    def test_cerebras_chat_request_shape(self) -> None:
        packet, _ = self._packet()
        bridge = CerebrasSDKBridge(
            model="qwen-3-32b",
            service_tier="priority",
            reasoning_effort="low",
            reasoning_format="parsed",
        )
        request = bridge.build_chat_request(
            packet,
            prompt="Answer with one caveat.",
            service_tier="flex",
            reasoning_effort="high",
            reasoning_format="hidden",
            max_tokens=180,
            max_completion_tokens=200,
            min_completion_tokens=30,
            clear_thinking=True,
            parallel_tool_calls=True,
            response_format={"type": "json_object"},
            logprobs=True,
            top_logprobs=3,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "search_runbook",
                        "description": "Search internal runbooks",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )
        self.assertEqual(request["model"], "qwen-3-32b")
        self.assertEqual(request["service_tier"], "flex")
        self.assertEqual(request["reasoning_effort"], "high")
        self.assertEqual(request["reasoning_format"], "hidden")
        self.assertTrue(request["logprobs"])
        self.assertEqual(request["top_logprobs"], 3)
        self.assertEqual(request["max_tokens"], 180)
        self.assertEqual(request["max_completion_tokens"], 200)
        self.assertEqual(request["min_completion_tokens"], 30)
        self.assertTrue(request["clear_thinking"])
        self.assertTrue(request["parallel_tool_calls"])
        self.assertEqual(request["response_format"]["type"], "json_object")
        self.assertEqual(request["messages"][-1]["role"], "user")

    def test_cerebras_speculative_prediction_shortcuts(self) -> None:
        packet, _ = self._packet()
        bridge = CerebrasSDKBridge()
        request = bridge.build_chat_request(
            packet,
            prediction="Known scaffold text",
        )
        self.assertEqual(request["prediction"]["type"], "content")
        self.assertEqual(request["prediction"]["content"], "Known scaffold text")

        structured = bridge.build_speculative_prediction(
            ["line A", "line B", {"type": "text", "text": "line C"}]
        )
        self.assertEqual(structured["type"], "content")
        self.assertEqual(len(structured["content"]), 3)
        self.assertEqual(structured["content"][0]["text"], "line A")

    def test_cerebras_extract_speculative_metrics(self) -> None:
        response = {
            "usage": {
                "completion_tokens_details": {
                    "accepted_prediction_tokens": 120,
                    "rejected_prediction_tokens": 30,
                }
            }
        }
        metrics = CerebrasSDKBridge.extract_speculative_decoding_metrics(response)
        self.assertIsNotNone(metrics)
        assert metrics is not None
        self.assertEqual(metrics.accepted_prediction_tokens, 120)
        self.assertEqual(metrics.rejected_prediction_tokens, 30)
        self.assertEqual(metrics.total_prediction_tokens, 150)
        self.assertAlmostEqual(metrics.acceptance_rate, 0.8, places=6)
        self.assertAlmostEqual(metrics.rejection_rate, 0.2, places=6)

    def test_cerebras_perplexity_parsing(self) -> None:
        response = {
            "choices": [
                {
                    "logprobs": {
                        "token_logprobs": [-0.2, -0.3, -0.1],
                        "tokens": ["A", "B", "C"],
                    }
                }
            ]
        }
        result = CerebrasSDKBridge.parse_perplexity_response(response)
        expected = 1.2214027581601699  # exp(0.2)
        self.assertAlmostEqual(result.perplexity, expected, places=8)
        self.assertEqual(result.token_count, 3)
        self.assertEqual(result.tokens, ("A", "B", "C"))

    def test_cerebras_perplexity_leading_none_alignment(self) -> None:
        # echo=True completions always return token_logprobs[0] == None because
        # the first token has no preceding context. The dropped logprob must drop
        # the FIRST token too, so the returned tokens still label the logprobs
        # they accompany: logprobs (-0.2, -0.3) belong to (' cat', ' sat').
        response = {
            "choices": [
                {
                    "logprobs": {
                        "token_logprobs": [None, -0.2, -0.3],
                        "tokens": ["The", " cat", " sat"],
                    }
                }
            ]
        }
        result = CerebrasSDKBridge.parse_perplexity_response(response)
        self.assertEqual(result.tokens, (" cat", " sat"))
        self.assertEqual(result.token_logprobs, (-0.2, -0.3))
        self.assertEqual(result.token_count, 2)
        expected = math.exp(0.25)  # mean of 0.2 and 0.3
        self.assertAlmostEqual(result.perplexity, expected, places=8)

    def test_cerebras_candidate_ranking_by_perplexity(self) -> None:
        class _FakeCompletions:
            def create(self, **kwargs):
                prompt = kwargs["prompt"]
                if "strong candidate" in prompt:
                    logs = [-0.05, -0.08]
                else:
                    logs = [-0.8, -0.7]
                return {"choices": [{"logprobs": {"token_logprobs": logs, "tokens": ["x", "y"]}}]}

        class _FakeClient:
            completions = _FakeCompletions()

        bridge = CerebrasSDKBridge()
        ranked = bridge.score_candidates_by_perplexity(
            _FakeClient(),
            prefix="Pick the most plausible completion.",
            candidates=["weak candidate", "strong candidate"],
        )
        self.assertEqual(ranked[0][0], "strong candidate")
        self.assertLess(ranked[0][1].perplexity, ranked[1][1].perplexity)

    def test_ollama_native_and_cloud_payloads(self) -> None:
        packet, _ = self._packet()
        bridge = OllamaSDKBridge(model="llama3.1:8b", base_url="http://localhost:11434")

        native = bridge.build_native_chat_request(
            packet,
            prompt="Summarize retry guidance.",
            options={"temperature": 0.1},
            keep_alive="10m",
        )
        self.assertEqual(native["model"], "llama3.1:8b")
        self.assertIn("options", native)
        self.assertEqual(native["keep_alive"], "10m")
        self.assertEqual(native["messages"][-1]["role"], "user")

        cloud = bridge.build_cloud_chat_request(
            packet,
            prompt="Summarize retry guidance.",
            temperature=0.1,
            max_tokens=200,
            metadata={"workflow": "tests"},
        )
        self.assertEqual(cloud["model"], "llama3.1:8b")
        self.assertEqual(cloud["temperature"], 0.1)
        self.assertEqual(cloud["max_tokens"], 200)
        self.assertEqual(cloud["metadata"]["workflow"], "tests")

    def test_ollama_build_http_request_paths(self) -> None:
        packet, _ = self._packet()
        bridge = OllamaSDKBridge(
            model="llama3.1:8b",
            base_url="http://localhost:11434",
            local_chat_path="/api/chat",
            cloud_chat_path="/v1/chat/completions",
        )

        local_request = bridge.build_http_request(packet, cloud_mode=False)
        self.assertEqual(local_request["url"], "http://localhost:11434/api/chat")
        self.assertEqual(local_request["json"]["model"], "llama3.1:8b")

        cloud_request = bridge.build_http_request(packet, cloud_mode=True)
        self.assertEqual(
            cloud_request["url"],
            "http://localhost:11434/v1/chat/completions",
        )
        self.assertEqual(cloud_request["json"]["model"], "llama3.1:8b")

    def test_ollama_from_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OLLAMA_MODEL": "qwen2.5:14b",
                "OLLAMA_BASE_URL": "https://example.ollama.host",
                "OLLAMA_API_KEY": "secret",
                "OLLAMA_CLOUD_MODE": "true",
                "OLLAMA_LOCAL_CHAT_PATH": "/local/chat",
                "OLLAMA_CLOUD_CHAT_PATH": "/cloud/chat",
            },
            clear=False,
        ):
            bridge = OllamaSDKBridge.from_env()

        self.assertEqual(bridge.model, "qwen2.5:14b")
        self.assertEqual(bridge.base_url, "https://example.ollama.host")
        self.assertEqual(bridge.api_key, "secret")
        self.assertTrue(bridge.cloud_mode)
        self.assertEqual(bridge.local_chat_path, "/local/chat")
        self.assertEqual(bridge.cloud_chat_path, "/cloud/chat")

    def test_ollama_create_chat_client_shapes(self) -> None:
        packet, _ = self._packet()
        bridge = OllamaSDKBridge(model="llama3.1:8b")

        class _NativeClient:
            def __init__(self) -> None:
                self.payload: dict[str, object] | None = None

            def chat(self, **kwargs):
                self.payload = kwargs
                return {"message": {"content": "native ok"}}

        class _CloudCompletions:
            def __init__(self) -> None:
                self.payload: dict[str, object] | None = None

            def create(self, **kwargs):
                self.payload = kwargs
                return {"choices": [{"message": {"content": "cloud ok"}}]}

        class _CloudClient:
            def __init__(self) -> None:
                self.chat = type("Chat", (), {"completions": _CloudCompletions()})()

        native_client = _NativeClient()
        native_response = bridge.create_chat(native_client, packet, cloud_mode=False)
        self.assertEqual(native_response["message"]["content"], "native ok")
        assert native_client.payload is not None
        self.assertEqual(native_client.payload["model"], "llama3.1:8b")

        cloud_client = _CloudClient()
        cloud_response = bridge.create_chat(cloud_client, packet, cloud_mode=True)
        self.assertEqual(cloud_response["choices"][0]["message"]["content"], "cloud ok")
        self.assertEqual(cloud_client.chat.completions.payload["model"], "llama3.1:8b")

    def test_ollama_parse_chat_text(self) -> None:
        self.assertEqual(
            OllamaSDKBridge.parse_chat_text({"message": {"content": "native response"}}),
            "native response",
        )
        self.assertEqual(
            OllamaSDKBridge.parse_chat_text(
                {"choices": [{"message": {"content": "cloud response"}}]}
            ),
            "cloud response",
        )
        self.assertEqual(
            OllamaSDKBridge.parse_chat_text(
                {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "text", "text": "line one"},
                                    {"type": "text", "text": "line two"},
                                ]
                            }
                        }
                    ]
                }
            ),
            "line one\nline two",
        )
        self.assertEqual(
            OllamaSDKBridge.parse_chat_text(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "reasoning": "reasoning fallback",
                            }
                        }
                    ]
                }
            ),
            "reasoning fallback",
        )

    def test_ollama_create_chat_http_client(self) -> None:
        packet, _ = self._packet()
        bridge = OllamaSDKBridge(
            model="llama3.1:8b",
            base_url="http://localhost:11434",
            cloud_mode=False,
        )

        class _HttpClient:
            def __init__(self) -> None:
                self.last_call: tuple[str, dict[str, str], dict[str, object]] | None = None

            def post(self, url, headers=None, json=None):
                self.last_call = (url, headers or {}, json or {})
                return {"message": {"content": "http fallback"}}

        client = _HttpClient()
        response = bridge.create_chat(client, packet, cloud_mode=False)
        self.assertEqual(response["message"]["content"], "http fallback")
        assert client.last_call is not None
        self.assertEqual(client.last_call[0], "http://localhost:11434/api/chat")
        self.assertIn("Content-Type", client.last_call[1])


if __name__ == "__main__":
    unittest.main()
