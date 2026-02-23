from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Set, Optional
from .core import ContextItem, ContextPack, pack, Budget, ScoringWeights


@dataclass
class EvalCase:
    name: str
    items: List[ContextItem]
    budget: int
    required_ids: Set[str] # Must be present
    disallowed_ids: Set[str] = field(default_factory=set) # Must NOT be present
    weights: Optional[ScoringWeights] = None


@dataclass
class EvalResult:
    name: str
    missing_required: Set[str]
    included_disallowed: Set[str]
    budget_usage: float
    passed: bool


class Backtester:
    def __init__(self, redundancy_threshold: float = 0.95):
        self.cases: List[EvalCase] = []
        self.redundancy_threshold = redundancy_threshold

    def add_case(self, case: EvalCase):
        self.cases.append(case)

    def run_all(self) -> List[EvalResult]:
        results = []
        for case in self.cases:
            packed = pack(
                case.items, 
                Budget(maxTokens=case.budget),
                weights=case.weights,
                redundancy_threshold=self.redundancy_threshold
            )
            results.append(self._calculate_metrics(case, packed))
        return results

    def _calculate_metrics(self, case: EvalCase, packed: ContextPack) -> EvalResult:
        selected_ids = {i.id for i in packed.selected}
        
        missing = case.required_ids - selected_ids
        forbidden = selected_ids.intersection(case.disallowed_ids)
        
        usage = packed.total_tokens / case.budget if case.budget > 0 else 0.0
        passed = len(missing) == 0 and len(forbidden) == 0
        
        return EvalResult(
            name=case.name,
            missing_required=missing,
            included_disallowed=forbidden,
            budget_usage=round(usage, 2),
            passed=passed
        )

    def print_report(self, results: List[EvalResult]):
        print("\nCASE NAME                 | USAGE | STATUS")
        print("-" * 50)
        for r in results:
            status = "OK" if r.passed else "FAIL"
            print(f"{r.name:<25} | {r.budget_usage:<5} | {status}")
            if not r.passed:
                if r.missing_required: print(f"   - MISSING REQUIRED: {r.missing_required}")
                if r.included_disallowed: print(f"   - INCLUDED FORBIDDEN: {r.included_disallowed}")
