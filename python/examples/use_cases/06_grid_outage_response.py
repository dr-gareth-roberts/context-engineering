from __future__ import annotations

from _common import run_use_case


if __name__ == "__main__":
    run_use_case(
        use_case_id="grid_outage_response",
        default_scenario=(
            "A cascading substation failure cut power to 1.3M customers including "
            "hospitals and water treatment facilities during extreme heat."
        ),
    )
