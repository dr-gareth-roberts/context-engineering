"""Custom error hierarchy for context engineering.

Mirrors the TypeScript error types in @ce/core for cross-language parity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


class ContextEngineeringError(Exception):
    """Base error for all context engineering operations."""

    code: str

    def __init__(self, message: str, code: str = "CONTEXT_ENGINEERING_ERROR"):
        super().__init__(message)
        self.code = code


@dataclass
class ValidationDetail:
    path: str
    message: str


class ValidationError(ContextEngineeringError):
    """Raised when input fails validation (items, budget, schema)."""

    details: List[ValidationDetail]

    def __init__(self, message: str, details: List[ValidationDetail] | None = None):
        super().__init__(message, "VALIDATION_ERROR")
        self.details = details or []


class BudgetExceededError(ContextEngineeringError):
    """Raised when reserve tokens exceed max tokens or budget is invalid."""

    def __init__(self, message: str):
        super().__init__(message, "BUDGET_EXCEEDED")


class EstimationError(ContextEngineeringError):
    """Raised when token estimation fails (unknown model, bad pricing)."""

    def __init__(self, message: str):
        super().__init__(message, "ESTIMATION_ERROR")
