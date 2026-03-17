from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .models import ContextItem, ContextKind, ContextPacket


class MessageAdapter(Protocol):
    def shape(self, packet: ContextPacket) -> dict[str, Any]: ...


def _format_context_item(item: ContextItem) -> str:
    if item.kind == ContextKind.SYSTEM:
        return item.text

    prefix = item.kind.value
    if item.source:
        return f"[{prefix}:{item.source}] {item.text}"
    return f"[{prefix}] {item.text}"


@dataclass(slots=True)
class OpenAIChatAdapter:
    """
    Shapes ContextPacket data for OpenAI Chat Completions-compatible payloads.
    """

    def messages(self, packet: ContextPacket) -> list[dict[str, str]]:
        return packet.as_messages()

    def shape(self, packet: ContextPacket) -> dict[str, Any]:
        return {"messages": self.messages(packet)}

    def request(self, packet: ContextPacket, *, model: str, **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "messages": self.messages(packet)}
        payload.update(extra)
        return payload


@dataclass(slots=True)
class AnthropicMessagesAdapter:
    """
    Shapes ContextPacket data for Anthropic Messages API payloads.

    Anthropic expects:
    - top-level `system` string
    - `messages` list with `user` and `assistant` roles only
    """

    wrap_text_blocks: bool = True

    def shape(self, packet: ContextPacket) -> dict[str, Any]:
        system_lines: list[str] = []
        messages: list[dict[str, Any]] = []

        for item in packet.items:
            if item.kind == ContextKind.MESSAGE:
                role = item.role if item.role in {"user", "assistant"} else "user"
                content: Any
                if self.wrap_text_blocks:
                    content = [{"type": "text", "text": item.text}]
                else:
                    content = item.text
                messages.append({"role": role, "content": content})
                continue

            system_lines.append(_format_context_item(item))

        payload: dict[str, Any] = {"messages": messages}
        if system_lines:
            payload["system"] = "\n\n".join(system_lines)
        return payload

    def request(
        self,
        packet: ContextPacket,
        *,
        model: str,
        max_tokens: int,
        **extra: Any,
    ) -> dict[str, Any]:
        payload = self.shape(packet)
        payload["model"] = model
        payload["max_tokens"] = max_tokens
        payload.update(extra)
        return payload


@dataclass(slots=True)
class OllamaChatAdapter:
    """
    Shapes ContextPacket data for Ollama chat payloads.

    Supports both:
    - local/native Ollama `/api/chat` style requests
    - cloud/OpenAI-compatible `/v1/chat/completions` style requests
    """

    cloud_mode: bool = False

    def messages(self, packet: ContextPacket) -> list[dict[str, str]]:
        return packet.as_messages()

    def shape(self, packet: ContextPacket) -> dict[str, Any]:
        return {"messages": self.messages(packet)}

    def request(
        self,
        packet: ContextPacket,
        *,
        model: str,
        stream: bool = False,
        cloud_mode: bool | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        use_cloud = self.cloud_mode if cloud_mode is None else cloud_mode
        messages = self.messages(packet)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if not use_cloud:
            # Native Ollama /api/chat uses 'options' for model parameters
            # rather than top-level keys like 'temperature', 'top_p', etc.
            native_option_keys = {"temperature", "top_p", "top_k", "num_predict", "seed", "stop"}
            options: dict[str, Any] = {}
            for key in native_option_keys:
                if key in extra:
                    options[key] = extra.pop(key)
            if options:
                payload["options"] = options
        payload.update(extra)
        return payload
