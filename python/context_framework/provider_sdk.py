from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .models import ContextItem, ContextKind, ContextPacket


def _as_text_block(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def _normalize_anthropic_message_role(role: str) -> str:
    if role in {"assistant", "user"}:
        return role
    return "user"


def _to_anthropic_system_block(item: ContextItem) -> dict[str, Any]:
    if item.kind == ContextKind.SYSTEM:
        text = item.text
    elif item.source:
        text = f"[{item.kind.value}:{item.source}] {item.text}"
    else:
        text = f"[{item.kind.value}] {item.text}"
    return {"type": "text", "text": text}


def _get_attr_or_key(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class OpenAIResponsesSDKBridge:
    """
    Bridges ContextPacket data to OpenAI Responses API request payloads.

    This intentionally exposes less-common fields such as:
    - `store`
    - `truncation`
    - `reasoning`
    - batch JSONL request generation
    """

    model: str = "gpt-4.1-mini"
    reasoning_effort: str = "medium"
    include_reasoning_summary: bool = True
    store: bool = True
    truncation: str = "auto"
    service_tier: str = "auto"

    def build_response_request(
        self,
        packet: ContextPacket,
        *,
        prompt: str | None = None,
        metadata: dict[str, str] | None = None,
        enable_web_search: bool = False,
        json_schema: dict[str, Any] | None = None,
        json_schema_name: str = "response",
        prediction_text: str | None = None,
        previous_response_id: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        input_items = self._to_responses_input(packet)
        if prompt:
            input_items.append(
                {"role": "user", "content": [{"type": "input_text", "text": prompt}]}
            )

        request: dict[str, Any] = {
            "model": model or self.model,
            "input": input_items,
            "store": self.store,
            "truncation": self.truncation,
            "service_tier": self.service_tier,
            "reasoning": {
                "effort": self.reasoning_effort,
                "summary": "auto" if self.include_reasoning_summary else "none",
            },
        }

        if previous_response_id:
            request["previous_response_id"] = previous_response_id
        if metadata:
            request["metadata"] = metadata
        if enable_web_search:
            request["tools"] = [{"type": "web_search_preview"}]
        if json_schema:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": json_schema_name,
                    "schema": json_schema,
                    "strict": True,
                }
            }
        if prediction_text:
            request["prediction"] = {
                "type": "content",
                "content": prediction_text,
            }

        return request

    def create(
        self,
        client: Any,
        packet: ContextPacket,
        **kwargs: Any,
    ) -> Any:
        payload = self.build_response_request(packet, **kwargs)
        return client.responses.create(**payload)

    def build_batch_chat_requests(
        self,
        prompts: Sequence[str],
        *,
        system_prompt: str | None = None,
        custom_id_prefix: str = "ctx",
        model: str | None = None,
        temperature: float = 0.0,
    ) -> list[dict[str, Any]]:
        requests: list[dict[str, Any]] = []
        for idx, prompt in enumerate(prompts):
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            requests.append(
                {
                    "custom_id": f"{custom_id_prefix}-{idx}",
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": model or self.model,
                        "messages": messages,
                        "temperature": temperature,
                    },
                }
            )
        return requests

    @staticmethod
    def to_batch_jsonl_lines(requests: Iterable[dict[str, Any]]) -> list[str]:
        return [json.dumps(request) for request in requests]

    @staticmethod
    def _to_responses_input(packet: ContextPacket) -> list[dict[str, Any]]:
        input_items: list[dict[str, Any]] = []
        for message in packet.as_messages():
            role = message["role"]
            content = message["content"]
            input_items.append(
                {
                    "role": role,
                    "content": [{"type": "input_text", "text": content}],
                }
            )
        return input_items


@dataclass(slots=True)
class AnthropicSDKBridge:
    """
    Bridges ContextPacket data to Anthropic Messages API payloads.

    This intentionally exposes less-common features such as:
    - prompt caching via `cache_control`
    - `thinking` configuration
    - tool-use extraction helpers
    """

    model: str = "claude-3-7-sonnet-latest"
    max_tokens: int = 1024
    enable_prompt_cache: bool = True
    enable_thinking: bool = False
    thinking_budget_tokens: int = 1024

    def build_message_request(
        self,
        packet: ContextPacket,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        system_blocks: list[dict[str, Any]] = []
        messages: list[dict[str, Any]] = []

        for item in packet.items:
            if item.kind == ContextKind.MESSAGE:
                messages.append(
                    {
                        "role": _normalize_anthropic_message_role(item.role),
                        "content": [_as_text_block(item.text)],
                    }
                )
                continue

            block = _to_anthropic_system_block(item)
            if self.enable_prompt_cache:
                block["cache_control"] = {"type": "ephemeral"}
            system_blocks.append(block)

        request: dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "messages": messages,
        }
        if system_blocks:
            request["system"] = system_blocks
        if self.enable_thinking:
            request["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget_tokens,
            }
        if tools:
            request["tools"] = list(tools)
        if tool_choice:
            request["tool_choice"] = dict(tool_choice)
        if metadata:
            request["metadata"] = dict(metadata)
        return request

    def create(
        self,
        client: Any,
        packet: ContextPacket,
        **kwargs: Any,
    ) -> Any:
        payload = self.build_message_request(packet, **kwargs)
        return client.messages.create(**payload)

    @staticmethod
    def extract_tool_uses(response: Any) -> list[dict[str, Any]]:
        if isinstance(response, dict):
            content = response.get("content") or []
        else:
            content = getattr(response, "content", []) or []

        tool_uses: list[dict[str, Any]] = []
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type")
                if block_type != "tool_use":
                    continue
                tool_uses.append(
                    {
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "input": block.get("input", {}),
                    }
                )
                continue

            block_type = getattr(block, "type", None)
            if block_type != "tool_use":
                continue
            tool_uses.append(
                {
                    "id": getattr(block, "id", None),
                    "name": getattr(block, "name", None),
                    "input": getattr(block, "input", {}),
                }
            )
        return tool_uses


@dataclass(slots=True, frozen=True)
class PerplexityResult:
    perplexity: float
    average_negative_logprob: float
    token_count: int
    token_logprobs: tuple[float, ...]
    tokens: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class SpeculativeDecodingMetrics:
    accepted_prediction_tokens: int
    rejected_prediction_tokens: int
    total_prediction_tokens: int
    acceptance_rate: float

    @property
    def rejection_rate(self) -> float:
        return 1.0 - self.acceptance_rate


@dataclass(slots=True)
class CerebrasSDKBridge:
    """
    Bridges ContextPacket data to Cerebras SDK payloads and perplexity workflows.

    Exposes uncommon Cerebras knobs such as:
    - `service_tier`
    - `reasoning_effort` + `reasoning_format`
    - completion-logprob based perplexity scoring
    """

    model: str = "qwen-3-32b"
    service_tier: str = "auto"
    reasoning_effort: str = "medium"
    reasoning_format: str = "none"

    @staticmethod
    def build_speculative_prediction(
        content: str | Sequence[str] | Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        if isinstance(content, str):
            normalized_content: str | list[dict[str, str]] = content
        else:
            blocks: list[dict[str, str]] = []
            for block in content:
                if isinstance(block, str):
                    blocks.append({"type": "text", "text": block})
                    continue
                block_type = str(block.get("type", "text"))
                block_text = str(block.get("text", ""))
                blocks.append({"type": block_type, "text": block_text})
            normalized_content = blocks

        return {"type": "content", "content": normalized_content}

    def build_chat_request(
        self,
        packet: ContextPacket,
        *,
        prompt: str | None = None,
        model: str | None = None,
        service_tier: str | None = None,
        reasoning_effort: str | None = None,
        reasoning_format: str | None = None,
        max_tokens: int | None = None,
        max_completion_tokens: int | None = None,
        min_completion_tokens: int | None = None,
        temperature: float = 0.2,
        top_p: float = 1.0,
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        prediction: str | dict[str, Any] | Sequence[str] | Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        clear_thinking: bool | None = None,
        disable_reasoning: bool | None = None,
        parallel_tool_calls: bool | None = None,
        stop: str | Sequence[str] | None = None,
        logprobs: bool = False,
        top_logprobs: int | None = None,
        seed: int | None = None,
        user: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        messages = packet.as_messages()
        if prompt:
            messages.append({"role": "user", "content": prompt})

        request: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "service_tier": service_tier or self.service_tier,
            "reasoning_effort": reasoning_effort or self.reasoning_effort,
            "reasoning_format": reasoning_format or self.reasoning_format,
            "logprobs": logprobs,
        }
        if max_tokens is not None:
            request["max_tokens"] = max_tokens
        if max_completion_tokens is not None:
            request["max_completion_tokens"] = max_completion_tokens
        if min_completion_tokens is not None:
            request["min_completion_tokens"] = min_completion_tokens
        if top_logprobs is not None:
            request["top_logprobs"] = top_logprobs
        if seed is not None:
            request["seed"] = seed
        if user is not None:
            request["user"] = user
        if response_format is not None:
            request["response_format"] = dict(response_format)
        if clear_thinking is not None:
            request["clear_thinking"] = clear_thinking
        if disable_reasoning is not None:
            request["disable_reasoning"] = disable_reasoning
        if parallel_tool_calls is not None:
            request["parallel_tool_calls"] = parallel_tool_calls
        if stop is not None:
            request["stop"] = stop
        if tools:
            request["tools"] = list(tools)
        if tool_choice is not None:
            request["tool_choice"] = tool_choice
        if prediction:
            if isinstance(prediction, dict):
                request["prediction"] = dict(prediction)
            else:
                request["prediction"] = self.build_speculative_prediction(prediction)
        if metadata:
            request["metadata"] = dict(metadata)
        return request

    def create_chat(
        self,
        client: Any,
        packet: ContextPacket,
        **kwargs: Any,
    ) -> Any:
        payload = self.build_chat_request(packet, **kwargs)
        return client.chat.completions.create(**payload)

    def create_speculative_chat(
        self,
        client: Any,
        packet: ContextPacket,
        *,
        predicted_output: str | Sequence[str] | Sequence[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        payload = self.build_chat_request(
            packet,
            prediction=self.build_speculative_prediction(predicted_output),
            **kwargs,
        )
        return client.chat.completions.create(**payload)

    def build_perplexity_request(
        self,
        text: str,
        *,
        model: str | None = None,
        top_logprobs: int = 1,
        include_raw_tokens: bool = False,
    ) -> dict[str, Any]:
        return {
            "model": model or self.model,
            "prompt": text,
            "echo": True,
            "logprobs": max(1, top_logprobs),
            "max_tokens": 0,
            "temperature": 0.0,
            "top_p": 1.0,
            "return_raw_tokens": include_raw_tokens,
        }

    def score_perplexity(
        self,
        client: Any,
        text: str,
        *,
        model: str | None = None,
        top_logprobs: int = 1,
    ) -> PerplexityResult:
        payload = self.build_perplexity_request(
            text,
            model=model,
            top_logprobs=top_logprobs,
        )
        response = client.completions.create(**payload)
        return self.parse_perplexity_response(response)

    def score_candidates_by_perplexity(
        self,
        client: Any,
        *,
        prefix: str,
        candidates: Sequence[str],
        separator: str = "\n\nCandidate:\n",
        model: str | None = None,
    ) -> list[tuple[str, PerplexityResult]]:
        scored: list[tuple[str, PerplexityResult]] = []
        for candidate in candidates:
            text = f"{prefix}{separator}{candidate}"
            result = self.score_perplexity(client, text, model=model)
            scored.append((candidate, result))
        return sorted(scored, key=lambda row: row[1].perplexity)

    @staticmethod
    def extract_speculative_decoding_metrics(
        response: Any,
    ) -> SpeculativeDecodingMetrics | None:
        usage = _get_attr_or_key(response, "usage", None)
        if usage is None:
            return None

        details = _get_attr_or_key(usage, "completion_tokens_details", None)
        if details is None:
            return None

        accepted = int(_get_attr_or_key(details, "accepted_prediction_tokens", 0) or 0)
        rejected = int(_get_attr_or_key(details, "rejected_prediction_tokens", 0) or 0)
        total = accepted + rejected
        acceptance_rate = accepted / total if total > 0 else 0.0
        return SpeculativeDecodingMetrics(
            accepted_prediction_tokens=accepted,
            rejected_prediction_tokens=rejected,
            total_prediction_tokens=total,
            acceptance_rate=acceptance_rate,
        )

    @staticmethod
    def compute_perplexity(token_logprobs: Sequence[float]) -> PerplexityResult:
        values = [float(value) for value in token_logprobs if value is not None]
        if not values:
            raise ValueError("token_logprobs must contain at least one numeric value")
        average_negative_logprob = -sum(values) / len(values)
        perplexity = math.exp(average_negative_logprob)
        return PerplexityResult(
            perplexity=perplexity,
            average_negative_logprob=average_negative_logprob,
            token_count=len(values),
            token_logprobs=tuple(values),
            tokens=(),
        )

    @staticmethod
    def parse_perplexity_response(
        response: Any, *, choice_index: int = 0
    ) -> PerplexityResult:
        choices = _get_attr_or_key(response, "choices", None) or []
        if not choices:
            raise ValueError("No completion choices available to compute perplexity")
        if choice_index < 0 or choice_index >= len(choices):
            raise ValueError("choice_index out of range")

        choice = choices[choice_index]
        logprobs_obj = _get_attr_or_key(choice, "logprobs", None)
        if logprobs_obj is None:
            raise ValueError(
                "Completion choice does not include logprobs. "
                "Call completions with echo=True and logprobs>=1."
            )

        token_logprobs_raw = _get_attr_or_key(logprobs_obj, "token_logprobs", None) or []
        tokens_raw = _get_attr_or_key(logprobs_obj, "tokens", None) or []

        values = [float(value) for value in token_logprobs_raw if value is not None]
        if not values:
            raise ValueError(
                "No token logprobs found in response. "
                "Ensure the model returns `logprobs` for the prompt."
            )

        average_negative_logprob = -sum(values) / len(values)
        perplexity = math.exp(average_negative_logprob)
        tokens = tuple(str(token) for token in tokens_raw[: len(values)])
        return PerplexityResult(
            perplexity=perplexity,
            average_negative_logprob=average_negative_logprob,
            token_count=len(values),
            token_logprobs=tuple(values),
            tokens=tokens,
        )


@dataclass(slots=True)
class OllamaSDKBridge:
    """
    Bridges ContextPacket data to Ollama local and cloud/OpenAI-compatible APIs.

    Modes:
    - local/native: POST /api/chat
    - cloud/openai-compatible: POST /v1/chat/completions
    """

    model: str = "llama3.1:8b"
    base_url: str = "http://localhost:11434"
    api_key: str | None = None
    cloud_mode: bool = False
    local_chat_path: str = "/api/chat"
    cloud_chat_path: str = "/v1/chat/completions"

    @classmethod
    def from_env(cls) -> "OllamaSDKBridge":
        return cls(
            model=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            api_key=os.getenv("OLLAMA_API_KEY"),
            cloud_mode=_as_bool(os.getenv("OLLAMA_CLOUD_MODE")),
            local_chat_path=os.getenv("OLLAMA_LOCAL_CHAT_PATH", "/api/chat"),
            cloud_chat_path=os.getenv("OLLAMA_CLOUD_CHAT_PATH", "/v1/chat/completions"),
        )

    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def build_native_chat_request(
        self,
        packet: ContextPacket,
        *,
        prompt: str | None = None,
        model: str | None = None,
        stream: bool = False,
        options: dict[str, Any] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        format: str | dict[str, Any] | None = None,
        keep_alive: str | int | None = None,
    ) -> dict[str, Any]:
        messages = packet.as_messages()
        if prompt:
            messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": stream,
        }
        if options:
            payload["options"] = dict(options)
        if tools:
            payload["tools"] = list(tools)
        if format is not None:
            payload["format"] = format
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        return payload

    def build_cloud_chat_request(
        self,
        packet: ContextPacket,
        *,
        prompt: str | None = None,
        model: str | None = None,
        stream: bool = False,
        temperature: float = 0.2,
        top_p: float = 1.0,
        max_tokens: int | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        messages = packet.as_messages()
        if prompt:
            messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature,
            "top_p": top_p,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = list(tools)
        if response_format:
            payload["response_format"] = dict(response_format)
        if metadata:
            payload["metadata"] = dict(metadata)
        return payload

    def build_http_request(
        self,
        packet: ContextPacket,
        *,
        prompt: str | None = None,
        cloud_mode: bool | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        use_cloud = self.cloud_mode if cloud_mode is None else cloud_mode
        if use_cloud:
            path = self.cloud_chat_path
            payload = self.build_cloud_chat_request(packet, prompt=prompt, **kwargs)
        else:
            path = self.local_chat_path
            payload = self.build_native_chat_request(packet, prompt=prompt, **kwargs)

        if path.startswith(("http://", "https://")):
            url = path
        else:
            url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        return {
            "url": url,
            "headers": self.headers(),
            "json": payload,
        }

    def create_chat(
        self,
        client: Any,
        packet: ContextPacket,
        *,
        prompt: str | None = None,
        cloud_mode: bool | None = None,
        **kwargs: Any,
    ) -> Any:
        use_cloud = self.cloud_mode if cloud_mode is None else cloud_mode
        if use_cloud and hasattr(client, "chat") and hasattr(client.chat, "completions"):
            payload = self.build_cloud_chat_request(packet, prompt=prompt, **kwargs)
            return client.chat.completions.create(**payload)

        if hasattr(client, "chat"):
            payload = self.build_native_chat_request(packet, prompt=prompt, **kwargs)
            return client.chat(**payload)

        if hasattr(client, "post"):
            request = self.build_http_request(
                packet,
                prompt=prompt,
                cloud_mode=use_cloud,
                **kwargs,
            )
            return client.post(
                request["url"],
                headers=request["headers"],
                json=request["json"],
            )

        raise TypeError("Unsupported client interface for Ollama chat request")

    def create_with_httpx(
        self,
        packet: ContextPacket,
        *,
        prompt: str | None = None,
        cloud_mode: bool | None = None,
        timeout_seconds: float = 30.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        import httpx

        request = self.build_http_request(
            packet,
            prompt=prompt,
            cloud_mode=cloud_mode,
            **kwargs,
        )
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(
                request["url"],
                headers=request["headers"],
                json=request["json"],
            )
            response.raise_for_status()
            return response.json()

    @staticmethod
    def parse_chat_text(response: Any) -> str:
        def _from_content(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                if value.get("text") is not None:
                    return str(value.get("text"))
                return ""
            if isinstance(value, list):
                chunks: list[str] = []
                for block in value:
                    if isinstance(block, str):
                        if block.strip():
                            chunks.append(block)
                        continue
                    if isinstance(block, dict):
                        text = block.get("text")
                        if text is not None and str(text).strip():
                            chunks.append(str(text))
                        continue
                    block_text = getattr(block, "text", None)
                    if block_text is not None and str(block_text).strip():
                        chunks.append(str(block_text))
                return "\n".join(chunks).strip()
            return str(value)

        payload = response
        if hasattr(response, "json") and callable(response.json):
            payload = response.json()

        if isinstance(payload, dict):
            message = payload.get("message")
            if isinstance(message, dict):
                text = _from_content(message.get("content"))
                if text.strip():
                    return text
                if message.get("reasoning") is not None:
                    return str(message.get("reasoning"))

            if "response" in payload:
                return str(payload.get("response", ""))

            choices = payload.get("choices") or []
            if choices:
                first = choices[0]
                if isinstance(first, dict):
                    msg = first.get("message")
                    if isinstance(msg, dict):
                        text = _from_content(msg.get("content"))
                        if text.strip():
                            return text
                        if msg.get("reasoning") is not None:
                            return str(msg.get("reasoning"))
                    if first.get("text") is not None:
                        return str(first["text"])
                    if first.get("delta") is not None:
                        delta_text = _from_content(first.get("delta"))
                        if delta_text.strip():
                            return delta_text

        return str(payload)
