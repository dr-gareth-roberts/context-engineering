from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest.mock import patch

from context_framework.anthropic_agentic_text_system import (
    AgenticSDKBindings,
    AnthropicAgenticTextSystem,
    TextManipulationToolkit,
)


class AnthropicAgenticTextSystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.system = AnthropicAgenticTextSystem()

    def test_normalize_whitespace_and_regex_replace(self) -> None:
        toolkit = TextManipulationToolkit()
        normalized = toolkit.normalize_whitespace("A   line\n\n\nB\tline")
        transformed, count = toolkit.regex_replace(
            normalized,
            pattern=r"line",
            replacement="row",
            ignore_case=False,
        )

        self.assertEqual(normalized, "A line\n\nB line")
        self.assertEqual(transformed, "A row\n\nB row")
        self.assertEqual(count, 2)

    def test_redact_and_stats(self) -> None:
        toolkit = TextManipulationToolkit()
        text = "Reach me at alice@example.com and +1 (415) 555-0101."
        redacted, count = toolkit.redact(text)
        stats = toolkit.text_stats(redacted)

        self.assertGreaterEqual(count, 2)
        self.assertIn("[REDACTED]", redacted)
        self.assertGreater(stats["word_count"], 0)
        self.assertEqual(stats["sentence_count"], 1)

    def test_apply_transform_report(self) -> None:
        report = self.system.toolkit.apply_transform(
            "Policy   draft for bob@example.com",
            replacements=((r"\bPolicy\b", "Guideline"),),
        )
        self.assertIn("Guideline", report.transformed_text)
        self.assertGreaterEqual(report.redaction_count, 1)
        self.assertGreater(report.character_count, 0)

    def test_collect_text_from_mixed_message_shapes(self) -> None:
        class _TextBlock:
            def __init__(self, text: str) -> None:
                self.text = text

        class _Message:
            def __init__(self) -> None:
                self.role = "assistant"
                self.content = [_TextBlock("block text")]

        messages = [
            {"role": "assistant", "content": [{"type": "text", "text": "dict text"}]},
            _Message(),
        ]

        text = AnthropicAgenticTextSystem.collect_text(messages)
        self.assertIn("dict text", text)
        self.assertIn("block text", text)

    def test_load_bindings_prefers_agent_sdk(self) -> None:
        module = types.ModuleType("claude_agent_sdk")
        module.query = lambda **kwargs: []

        class _Options:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        module.ClaudeAgentOptions = _Options
        module.ClaudeSDKClient = object

        with patch.dict(sys.modules, {"claude_agent_sdk": module, "claude_code_sdk": None}):
            bindings = self.system.load_bindings()

        self.assertEqual(bindings.package, "claude_agent_sdk")
        self.assertIs(bindings.options_cls, _Options)

    def test_build_options_filters_unsupported_fields(self) -> None:
        class _Options:
            def __init__(self, system_prompt: str, allowed_tools: list[str], max_turns: int):
                self.system_prompt = system_prompt
                self.allowed_tools = allowed_tools
                self.max_turns = max_turns

        bindings = AgenticSDKBindings(
            package="test",
            query=lambda **kwargs: [],
            options_cls=_Options,
            client_cls=None,
            tool_decorator=None,
            create_sdk_mcp_server=None,
        )

        options = self.system.build_options(
            bindings,
            allowed_tools=["a"],
            max_turns=4,
            cwd="/tmp/ignored",
            permission_mode="acceptEdits",
        )

        self.assertEqual(options.system_prompt, self.system.system_prompt)
        self.assertEqual(options.allowed_tools, ["a"])
        self.assertEqual(options.max_turns, 4)

    def test_build_text_mcp_server(self) -> None:
        def _tool(name, description, schema):
            def _decorate(fn):
                fn.tool_name = name
                fn.description = description
                fn.schema = schema
                return fn

            return _decorate

        def _create_sdk_mcp_server(name, version, tools):
            return {
                "name": name,
                "version": version,
                "tools": tools,
            }

        bindings = AgenticSDKBindings(
            package="test",
            query=lambda **kwargs: [],
            options_cls=dict,
            client_cls=None,
            tool_decorator=_tool,
            create_sdk_mcp_server=_create_sdk_mcp_server,
        )

        server, allowed_tools = self.system.build_text_mcp_server(bindings)
        self.assertEqual(server["name"], "text_ops")
        self.assertEqual(len(server["tools"]), 4)
        self.assertIn("mcp__text_ops__normalize_text", allowed_tools)

        normalize = next(
            fn for fn in server["tools"] if getattr(fn, "tool_name", "") == "normalize_text"
        )
        result = asyncio.run(normalize({"text": "A   B", "preserve_paragraphs": True}))
        self.assertEqual(result["content"][0]["text"], "A B")

    def test_run_query_with_async_stream(self) -> None:
        async def _query(**kwargs):
            async def _stream():
                yield {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}

            return _stream()

        class _Options:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        bindings = AgenticSDKBindings(
            package="test",
            query=lambda **kwargs: _query(**kwargs),
            options_cls=_Options,
            client_cls=None,
            tool_decorator=None,
            create_sdk_mcp_server=None,
        )
        options = _Options()

        messages = self.system.run_query("prompt", options=options, bindings=bindings)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "assistant")

    def test_run_with_client(self) -> None:
        class _Client:
            def __init__(self, options=None):
                self.options = options

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def query(self, prompt: str):
                self.prompt = prompt

            async def receive_response(self):
                yield {"role": "assistant", "content": [{"type": "text", "text": "client ok"}]}

        bindings = AgenticSDKBindings(
            package="test",
            query=lambda **kwargs: [],
            options_cls=dict,
            client_cls=_Client,
            tool_decorator=None,
            create_sdk_mcp_server=None,
        )

        messages = self.system.run_with_client("prompt", options={}, bindings=bindings)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "assistant")

    def test_run_text_workflow(self) -> None:
        class _Options:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        async def _stream(**kwargs):
            async def _inner():
                yield {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "workflow response"}],
                }

            return _inner()

        bindings = AgenticSDKBindings(
            package="test",
            query=lambda **kwargs: _stream(**kwargs),
            options_cls=_Options,
            client_cls=None,
            tool_decorator=None,
            create_sdk_mcp_server=None,
        )

        with patch.object(AnthropicAgenticTextSystem, "load_bindings", return_value=bindings):
            result = self.system.run_text_workflow(
                source_text="hello world",
                instruction="normalize",
                method="query",
                enable_tool_server=False,
            )

        self.assertEqual(result["sdk_package"], "test")
        self.assertEqual(result["assistant_text"], "workflow response")


if __name__ == "__main__":
    unittest.main()
