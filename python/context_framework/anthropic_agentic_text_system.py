from __future__ import annotations

import asyncio
import importlib
import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(slots=True, frozen=True)
class AgenticSDKBindings:
    package: str
    query: Any
    options_cls: Any
    client_cls: Any | None
    tool_decorator: Any | None
    create_sdk_mcp_server: Any | None


@dataclass(slots=True, frozen=True)
class TextOperationReport:
    normalized_text: str
    transformed_text: str
    replacement_count: int
    redaction_count: int
    sentence_count: int
    word_count: int
    character_count: int


@dataclass(slots=True)
class TextManipulationToolkit:
    """Deterministic text manipulation helpers used by the agentic workflow."""

    default_redaction_patterns: tuple[str, ...] = (
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        r"\b\+?\d[\d\s().-]{7,}\d\b",
        r"\b\d{3}-\d{2}-\d{4}\b",
    )

    def normalize_whitespace(
        self,
        text: str,
        *,
        preserve_paragraphs: bool = True,
    ) -> str:
        if preserve_paragraphs:
            cleaned_lines: list[str] = []
            previous_blank = False
            for raw_line in text.splitlines():
                line = re.sub(r"[\t ]+", " ", raw_line).strip()
                is_blank = line == ""
                if is_blank and previous_blank:
                    continue
                cleaned_lines.append(line)
                previous_blank = is_blank
            return "\n".join(cleaned_lines).strip()

        return re.sub(r"\s+", " ", text).strip()

    def regex_replace(
        self,
        text: str,
        *,
        pattern: str,
        replacement: str,
        ignore_case: bool = False,
    ) -> tuple[str, int]:
        flags = re.IGNORECASE if ignore_case else 0
        return re.subn(pattern, replacement, text, flags=flags)

    def redact(
        self,
        text: str,
        *,
        patterns: Sequence[str] | None = None,
        replacement: str = "[REDACTED]",
        ignore_case: bool = True,
    ) -> tuple[str, int]:
        redaction_patterns = tuple(patterns or self.default_redaction_patterns)
        if not redaction_patterns:
            return text, 0

        total = 0
        output = text
        flags = re.IGNORECASE if ignore_case else 0
        for pattern in redaction_patterns:
            output, count = re.subn(pattern, replacement, output, flags=flags)
            total += count
        return output, total

    @staticmethod
    def text_stats(text: str) -> dict[str, int]:
        words = len(re.findall(r"\b\w+\b", text))
        sentence_chunks = [chunk.strip() for chunk in re.split(r"[.!?]+", text) if chunk.strip()]
        return {
            "word_count": words,
            "sentence_count": len(sentence_chunks),
            "character_count": len(text),
        }

    def apply_transform(
        self,
        text: str,
        *,
        replacements: Sequence[tuple[str, str]] = (),
        redaction_patterns: Sequence[str] | None = None,
    ) -> TextOperationReport:
        normalized = self.normalize_whitespace(text)

        transformed = normalized
        replacement_count = 0
        for pattern, repl in replacements:
            transformed, count = self.regex_replace(
                transformed,
                pattern=pattern,
                replacement=repl,
            )
            replacement_count += count

        transformed, redaction_count = self.redact(
            transformed,
            patterns=redaction_patterns,
        )
        stats = self.text_stats(transformed)

        return TextOperationReport(
            normalized_text=normalized,
            transformed_text=transformed,
            replacement_count=replacement_count,
            redaction_count=redaction_count,
            sentence_count=stats["sentence_count"],
            word_count=stats["word_count"],
            character_count=stats["character_count"],
        )


@dataclass(slots=True)
class AnthropicAgenticTextSystem:
    """
    High-level bridge around Anthropic's agentic SDKs.

    Supports both package names in the ecosystem:
    - `claude_agent_sdk` (current docs)
    - `claude_code_sdk` (legacy package naming)
    """

    system_prompt: str = (
        "You are a text-operations specialist. "
        "Use tools for deterministic transformations and keep outputs concise."
    )
    toolkit: TextManipulationToolkit = field(default_factory=TextManipulationToolkit)

    def load_bindings(self) -> AgenticSDKBindings:
        candidates: tuple[tuple[str, str], ...] = (
            ("claude_agent_sdk", "ClaudeAgentOptions"),
            ("claude_code_sdk", "ClaudeCodeOptions"),
        )

        last_error: Exception | None = None
        for module_name, options_name in candidates:
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:  # pragma: no cover - environment dependent
                last_error = exc
                continue

            query = getattr(module, "query", None)
            options_cls = getattr(module, options_name, None)
            if query is None or options_cls is None:
                continue

            return AgenticSDKBindings(
                package=module_name,
                query=query,
                options_cls=options_cls,
                client_cls=getattr(module, "ClaudeSDKClient", None),
                tool_decorator=getattr(module, "tool", None),
                create_sdk_mcp_server=getattr(module, "create_sdk_mcp_server", None),
            )

        if last_error is not None:
            raise ImportError(
                "Anthropic agentic SDK not available. Install `claude-agent-sdk` "
                "or `claude-code-sdk`."
            ) from last_error
        raise ImportError(
            "Anthropic agentic SDK not available. Install `claude-agent-sdk` "
            "or `claude-code-sdk`."
        )

    @staticmethod
    def _build_options(options_cls: Any, kwargs: dict[str, Any]) -> Any:
        try:
            signature = inspect.signature(options_cls)
        except (TypeError, ValueError):
            return options_cls(**kwargs)

        accepts_var_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        )
        if accepts_var_kwargs:
            return options_cls(**kwargs)

        filtered = {
            key: value
            for key, value in kwargs.items()
            if key in signature.parameters and value is not None
        }
        return options_cls(**filtered)

    @staticmethod
    def _resolve_awaitable(value: Any) -> Any:
        if not inspect.isawaitable(value):
            return value

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(value)

        raise RuntimeError(
            "Cannot synchronously resolve coroutine while an event loop is running."
        )

    def build_options(
        self,
        bindings: AgenticSDKBindings,
        *,
        allowed_tools: Sequence[str] | None = None,
        mcp_servers: dict[str, Any] | None = None,
        max_turns: int = 8,
        cwd: str | None = None,
        permission_mode: str = "acceptEdits",
        system_prompt: str | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "system_prompt": system_prompt or self.system_prompt,
            "allowed_tools": list(allowed_tools or ()),
            "max_turns": max_turns,
            "cwd": cwd,
            "permission_mode": permission_mode,
        }
        if mcp_servers:
            payload["mcp_servers"] = dict(mcp_servers)
        if extra_options:
            payload.update(extra_options)
        return self._build_options(bindings.options_cls, payload)

    def build_text_mcp_server(
        self,
        bindings: AgenticSDKBindings,
        *,
        server_name: str = "text_ops",
    ) -> tuple[Any, list[str]]:
        tool = bindings.tool_decorator
        create_server = bindings.create_sdk_mcp_server
        if tool is None or create_server is None:
            raise RuntimeError(
                "This SDK version does not expose in-process MCP tool APIs "
                "(`tool` and `create_sdk_mcp_server`)."
            )

        toolkit = self.toolkit

        @tool(
            "normalize_text",
            "Normalize whitespace and collapse duplicate blank lines.",
            {"text": str, "preserve_paragraphs": bool},
        )
        async def normalize_text(args: dict[str, Any]) -> dict[str, Any]:
            raw_text = str(args.get("text", ""))
            preserve = bool(args.get("preserve_paragraphs", True))
            normalized = toolkit.normalize_whitespace(
                raw_text,
                preserve_paragraphs=preserve,
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": normalized,
                    }
                ]
            }

        @tool(
            "regex_replace",
            "Apply regex replacement and return transformed text + replacement count.",
            {"text": str, "pattern": str, "replacement": str, "ignore_case": bool},
        )
        async def regex_replace(args: dict[str, Any]) -> dict[str, Any]:
            raw_text = str(args.get("text", ""))
            pattern = str(args.get("pattern", ""))
            replacement = str(args.get("replacement", ""))
            ignore_case = bool(args.get("ignore_case", False))
            transformed, count = toolkit.regex_replace(
                raw_text,
                pattern=pattern,
                replacement=replacement,
                ignore_case=ignore_case,
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": transformed,
                    }
                ],
                "replacement_count": count,
            }

        @tool(
            "redact_sensitive",
            "Redact sensitive patterns (emails/phones/SSNs by default).",
            {"text": str, "replacement": str},
        )
        async def redact_sensitive(args: dict[str, Any]) -> dict[str, Any]:
            raw_text = str(args.get("text", ""))
            replacement = str(args.get("replacement", "[REDACTED]"))
            transformed, count = toolkit.redact(raw_text, replacement=replacement)
            return {
                "content": [{"type": "text", "text": transformed}],
                "redaction_count": count,
            }

        @tool(
            "text_stats",
            "Return sentence/word/character counts.",
            {"text": str},
        )
        async def text_stats(args: dict[str, Any]) -> dict[str, Any]:
            raw_text = str(args.get("text", ""))
            stats = toolkit.text_stats(raw_text)
            return {
                "content": [{"type": "text", "text": str(stats)}],
                "stats": stats,
            }

        server = create_server(
            name=server_name,
            version="1.0.0",
            tools=[normalize_text, regex_replace, redact_sensitive, text_stats],
        )
        allowed_tools = [
            f"mcp__{server_name}__normalize_text",
            f"mcp__{server_name}__regex_replace",
            f"mcp__{server_name}__redact_sensitive",
            f"mcp__{server_name}__text_stats",
        ]
        return server, allowed_tools

    @staticmethod
    def collect_text(messages: Sequence[Any]) -> str:
        parts: list[str] = []

        for message in messages:
            if isinstance(message, dict):
                role = message.get("role")
                if role not in (None, "assistant"):
                    continue
                content = message.get("content")
                if content is None and message.get("text") is not None:
                    parts.append(str(message["text"]))
                    continue
            else:
                role = getattr(message, "role", None)
                if role not in (None, "assistant"):
                    continue
                content = getattr(message, "content", None)
                if content is None and getattr(message, "text", None) is not None:
                    parts.append(str(getattr(message, "text")))
                    continue

            if isinstance(content, str):
                parts.append(content)
                continue

            if isinstance(content, dict):
                if content.get("text") is not None:
                    parts.append(str(content.get("text")))
                continue

            if isinstance(content, list):
                for block in content:
                    if isinstance(block, str):
                        parts.append(block)
                        continue
                    if isinstance(block, dict):
                        if block.get("type") == "text" and block.get("text") is not None:
                            parts.append(str(block["text"]))
                        continue
                    block_text = getattr(block, "text", None)
                    if block_text is not None:
                        parts.append(str(block_text))

        return "\n".join(part for part in parts if part).strip()

    def run_query(
        self,
        prompt: str,
        *,
        options: Any,
        bindings: AgenticSDKBindings,
    ) -> list[Any]:
        stream = bindings.query(prompt=prompt, options=options)
        if inspect.isawaitable(stream):
            stream = self._resolve_awaitable(stream)

        async def _collect_async(async_stream: Any) -> list[Any]:
            collected: list[Any] = []
            async for message in async_stream:
                collected.append(message)
            return collected

        if hasattr(stream, "__aiter__"):
            return self._resolve_awaitable(_collect_async(stream))
        if isinstance(stream, list):
            return stream
        return list(stream)

    def run_with_client(
        self,
        prompt: str,
        *,
        options: Any,
        bindings: AgenticSDKBindings,
    ) -> list[Any]:
        if bindings.client_cls is None:
            raise RuntimeError(
                f"{bindings.package} does not expose ClaudeSDKClient for client mode."
            )

        async def _run() -> list[Any]:
            output: list[Any] = []
            async with bindings.client_cls(options=options) as client:
                result = client.query(prompt)
                if inspect.isawaitable(result):
                    await result
                if hasattr(client, "receive_response"):
                    async for message in client.receive_response():
                        output.append(message)
            return output

        return self._resolve_awaitable(_run())

    def run_text_workflow(
        self,
        *,
        source_text: str,
        instruction: str,
        method: str = "query",
        cwd: str | None = None,
        max_turns: int = 8,
        enable_tool_server: bool = True,
    ) -> dict[str, Any]:
        bindings = self.load_bindings()

        mcp_servers: dict[str, Any] = {}
        allowed_tools: list[str] = []
        if enable_tool_server:
            try:
                server, allowed_tools = self.build_text_mcp_server(bindings)
                mcp_servers = {"text_ops": server}
            except RuntimeError:
                mcp_servers = {}
                allowed_tools = []

        options = self.build_options(
            bindings,
            allowed_tools=allowed_tools,
            mcp_servers=mcp_servers,
            max_turns=max_turns,
            cwd=cwd,
        )

        prompt = (
            "Instruction:\n"
            f"{instruction}\n\n"
            "Input text:\n"
            "```\n"
            f"{source_text}\n"
            "```\n\n"
            "Return a concise transformed output. If tools are available, use them."
        )

        if method == "client":
            messages = self.run_with_client(prompt, options=options, bindings=bindings)
        elif method == "query":
            messages = self.run_query(prompt, options=options, bindings=bindings)
        else:
            raise ValueError("method must be 'query' or 'client'")

        return {
            "sdk_package": bindings.package,
            "method": method,
            "message_count": len(messages),
            "assistant_text": self.collect_text(messages),
            "allowed_tools": allowed_tools,
        }
