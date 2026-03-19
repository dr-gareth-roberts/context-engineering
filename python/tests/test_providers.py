from __future__ import annotations

import unittest

from context_framework import (
    AnthropicMessagesAdapter,
    ContextManager,
    OllamaChatAdapter,
    OpenAIChatAdapter,
)


class ProviderAdapterTests(unittest.TestCase):
    def test_openai_chat_adapter_shapes_messages(self) -> None:
        manager = ContextManager(default_token_budget=120, reserved_response_tokens=20)
        manager.add_system("Answer with concise explanations.")
        manager.add_memory("User prefers bullet lists.", source="profile")
        manager.add_message("user", "Explain retry backoff.")

        packet = manager.build_context("retry backoff")
        payload = OpenAIChatAdapter().shape(packet)
        messages = payload["messages"]

        self.assertTrue(any(message["role"] == "system" for message in messages))
        self.assertTrue(any(message["role"] == "user" for message in messages))
        self.assertTrue(any("[memory:profile]" in message["content"] for message in messages))

    def test_anthropic_adapter_uses_system_and_message_roles(self) -> None:
        manager = ContextManager(default_token_budget=120, reserved_response_tokens=20)
        manager.add_system("Be accurate and brief.")
        manager.add_document("Retry backoff doubles delay after failure.", source="retry-doc")
        manager.add_message("user", "How should retries work?")
        manager.add_message("assistant", "Use exponential delays with a cap.")

        packet = manager.build_context("retry")
        payload = AnthropicMessagesAdapter().shape(packet)

        self.assertIn("system", payload)
        self.assertIn("[document:retry-doc]", payload["system"])
        self.assertEqual([m["role"] for m in payload["messages"]], ["user", "assistant"])
        self.assertIsInstance(payload["messages"][0]["content"], list)
        self.assertEqual(payload["messages"][0]["content"][0]["type"], "text")

    def test_ollama_adapter_shapes_local_request(self) -> None:
        manager = ContextManager(default_token_budget=120, reserved_response_tokens=20)
        manager.add_system("Be concise.")
        manager.add_message("user", "Summarize incident status.")
        packet = manager.build_context("incident")

        adapter = OllamaChatAdapter(cloud_mode=False)
        request = adapter.request(packet, model="llama3.1:8b", stream=False)

        self.assertEqual(request["model"], "llama3.1:8b")
        self.assertIn("messages", request)
        self.assertFalse(request["stream"])
        self.assertTrue(any(m["role"] == "system" for m in request["messages"]))

    def test_ollama_adapter_shapes_cloud_request(self) -> None:
        manager = ContextManager(default_token_budget=120, reserved_response_tokens=20)
        manager.add_system("Be concise.")
        manager.add_message("user", "Summarize incident status.")
        packet = manager.build_context("incident")

        adapter = OllamaChatAdapter(cloud_mode=True)
        request = adapter.request(
            packet,
            model="llama3.1-70b",
            stream=True,
            temperature=0.1,
            max_tokens=200,
        )

        self.assertEqual(request["model"], "llama3.1-70b")
        self.assertTrue(request["stream"])
        self.assertEqual(request["temperature"], 0.1)
        self.assertEqual(request["max_tokens"], 200)
        self.assertIn("messages", request)

    def test_ollama_adapter_does_not_mutate_caller_kwargs(self) -> None:
        manager = ContextManager(default_token_budget=120, reserved_response_tokens=20)
        manager.add_system("Be concise.")
        manager.add_message("user", "Hello.")
        packet = manager.build_context("hello")

        adapter = OllamaChatAdapter(cloud_mode=False)
        kwargs = {"temperature": 0.5, "top_p": 0.9, "custom_key": "value"}
        kwargs_copy = dict(kwargs)

        adapter.request(packet, model="llama3.1:8b", **kwargs)

        # The original kwargs dict must not be mutated
        self.assertEqual(kwargs, kwargs_copy)


if __name__ == "__main__":
    unittest.main()
