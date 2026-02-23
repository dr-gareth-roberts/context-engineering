from __future__ import annotations

from _common import run_use_case


if __name__ == "__main__":
    run_use_case(
        use_case_id="supply_chain_control_tower",
        default_scenario=(
            "Two major ports report labor action and weather disruptions while a tier-2 "
            "supplier in Southeast Asia halts production for 10 days."
        ),
    )
