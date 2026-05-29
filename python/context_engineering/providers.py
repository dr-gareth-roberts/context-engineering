from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, List, Optional, Protocol

if TYPE_CHECKING:
    import httpx
else:
    try:
        import httpx
    except ImportError:  # httpx is an optional extra (providers / server / webhooks)
        httpx = None

from .core import ContextItem, estimate_tokens


@dataclass
class LLMMessage:
    role: str
    content: str


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


@dataclass
class EmbeddingResult:
    vectors: List[List[float]]
    model: str


class EmbeddingProvider:
    def embed(self, texts: List[str], model: str) -> EmbeddingResult:
        raise NotImplementedError


class OpenAIProvider:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        if httpx is None:
            raise ImportError(
                "httpx is required for provider HTTP calls; install context-engineering[providers]"
            )
        if self._client is None or self._client.is_closed:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=30)
        return self._client

    def generate(
        self,
        messages: List[LLMMessage],
        model: str = "gpt-4o-mini",
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> LLMResult:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required")

        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        client = self._get_client()
        response = client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMResult(
            text=text,
            model=data.get("model", model),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    def embed(self, texts: List[str], model: str = "text-embedding-3-small") -> EmbeddingResult:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required")

        payload = {
            "model": model,
            "input": texts,
        }

        client = self._get_client()
        response = client.post("/embeddings", json=payload)
        response.raise_for_status()
        data = response.json()

        vectors = [item["embedding"] for item in data["data"]]
        return EmbeddingResult(vectors=vectors, model=data.get("model", model))


class CerebrasProvider:
    """
    Provider for Cerebras Cloud SDK.
    Supports high-speed inference and perplexity scoring.
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or os.environ.get("CEREBRAS_API_KEY")
        self.base_url = base_url or os.environ.get(
            "CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1"
        )
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        if httpx is None:
            raise ImportError(
                "httpx is required for provider HTTP calls; install context-engineering[providers]"
            )
        if self._client is None or self._client.is_closed:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=30)
        return self._client

    def score_perplexity(self, text: str, model: str = "llama3.1-8b") -> float:
        """
        Returns the perplexity score for the given text.
        Calculated as exp(-avg(log_probs)).
        """
        if not self.api_key:
            raise ValueError("CEREBRAS_API_KEY is required")

        payload = {
            "model": model,
            "prompt": text,
            "echo": True,
            "logprobs": 1,
            "max_tokens": 0,
        }

        client = self._get_client()
        response = client.post("/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        logprobs_data = data["choices"][0]["logprobs"]
        token_logprobs = logprobs_data["token_logprobs"]

        # Filter out None values (usually the first token)
        values = [lp for lp in token_logprobs if lp is not None]
        if not values:
            return 0.0

        avg_neg_logprob = -sum(values) / len(values)
        return math.exp(avg_neg_logprob)


class AnthropicProvider:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.base_url = base_url or os.environ.get(
            "ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"
        )
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        if httpx is None:
            raise ImportError(
                "httpx is required for provider HTTP calls; install context-engineering[providers]"
            )
        if self._client is None or self._client.is_closed:
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            }
            self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=30)
        return self._client

    def generate(
        self,
        messages: List[LLMMessage],
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> LLMResult:
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")

        system_messages = [m.content for m in messages if m.role == "system"]
        system = "\n\n".join(system_messages) if system_messages else None
        user_messages = [m for m in messages if m.role != "system"]

        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in user_messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system

        client = self._get_client()
        response = client.post("/messages", json=payload)
        response.raise_for_status()
        data = response.json()

        content_blocks = data.get("content", [])
        text = "".join(block.get("text", "") for block in content_blocks)
        usage = data.get("usage", {})
        return LLMResult(
            text=text,
            model=data.get("model", model),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )


_DEFAULT_SUMMARIZE_PROMPT = (
    "Summarize the following conversation turns into a concise paragraph "
    "that preserves key facts, decisions, and action items. "
    "Omit pleasantries and filler."
)


class LLMProvider(Protocol):
    """Protocol for providers that can generate text."""

    def generate(
        self,
        messages: List[LLMMessage],
        model: str = ...,
        max_tokens: int = ...,
        temperature: float = ...,
    ) -> LLMResult: ...


def create_llm_summarizer(
    provider: LLMProvider,
    model: Optional[str] = None,
    max_output_tokens: int = 256,
    prompt: str = _DEFAULT_SUMMARIZE_PROMPT,
) -> Callable[[ContextItem, int], ContextItem | None]:
    """Create a synchronous LLM summarizer for use with compaction.

    Returns a callable (item, target_tokens) -> ContextItem | None.
    Returns None on provider errors.
    """

    def summarize(item: ContextItem, _target_tokens: int) -> ContextItem | None:
        try:
            result = provider.generate(
                messages=[
                    LLMMessage(role="system", content=prompt),
                    LLMMessage(role="user", content=item.content),
                ],
                model=model or "",
                max_tokens=max_output_tokens,
            )
            content = result.text
            if not content:
                return None
            tokens = estimate_tokens(content)
            return item.model_copy(update={"content": content, "tokens": tokens})
        except Exception:
            return None

    return summarize
