from __future__ import annotations

from _common import run_use_case


if __name__ == "__main__":
    run_use_case(
        use_case_id="emergency_operations_center",
        default_scenario=(
            "Wildfire fronts shifted overnight toward suburban zones while evacuation "
            "routes are partially blocked and shelters are near capacity."
        ),
    )
