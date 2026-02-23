from __future__ import annotations

import math
from typing import Protocol


class TokenCounter(Protocol):
    def count(self, text: str) -> int:
        ...


class ApproxTokenCounter:
    """
    Fast approximate token counting based on chars/token.
    Useful when you do not need exact tokenizer parity.
    """

    def __init__(self, chars_per_token: float = 4.0, min_tokens: int = 1) -> None:
        if chars_per_token <= 0:
            raise ValueError("chars_per_token must be > 0")
        if min_tokens < 1:
            raise ValueError("min_tokens must be >= 1")
        self._chars_per_token = chars_per_token
        self._min_tokens = min_tokens

    def count(self, text: str) -> int:
        body = text.strip()
        if not body:
            return self._min_tokens
        return max(self._min_tokens, math.ceil(len(body) / self._chars_per_token))


class TiktokenCounter:
    """
    Exact-ish token counting for OpenAI-style models via `tiktoken`.
    """

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        try:
            import tiktoken  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "tiktoken is not installed. Install with: pip install context-framework[tiktoken]"
            ) from exc

        self._encoder = tiktoken.encoding_for_model(model)

    def count(self, text: str) -> int:
        return max(1, len(self._encoder.encode(text)))
