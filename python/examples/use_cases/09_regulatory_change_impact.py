from __future__ import annotations

from _common import run_use_case

if __name__ == "__main__":
    run_use_case(
        use_case_id="regulatory_change_impact",
        default_scenario=(
            "New regional AI governance requirements mandate model inventory, "
            "risk-tier controls, and annual audit attestations within 120 days."
        ),
    )
