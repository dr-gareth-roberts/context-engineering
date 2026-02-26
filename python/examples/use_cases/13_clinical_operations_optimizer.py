from __future__ import annotations

from _common import run_use_case

if __name__ == "__main__":
    run_use_case(
        use_case_id="clinical_operations_optimizer",
        default_scenario=(
            "ED boarding times exceeded thresholds, ICU beds are constrained, and staffing "
            "gaps are expected during a regional respiratory surge."
        ),
    )
