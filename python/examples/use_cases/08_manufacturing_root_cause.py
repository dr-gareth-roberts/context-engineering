from __future__ import annotations

from _common import run_use_case

if __name__ == "__main__":
    run_use_case(
        use_case_id="manufacturing_root_cause",
        default_scenario=(
            "Yield dropped by 18% on two lines after a firmware rollout; vibration and "
            "thermal telemetry are out of expected ranges."
        ),
    )
