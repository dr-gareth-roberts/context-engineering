from __future__ import annotations

from _common import run_use_case

if __name__ == "__main__":
    run_use_case(
        use_case_id="contact_center_autopilot",
        default_scenario=(
            "Average handle time spiked after billing changes; customers report duplicate "
            "charges and unresolved delivery disputes across channels."
        ),
    )
