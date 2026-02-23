from __future__ import annotations

from _common import run_use_case


if __name__ == "__main__":
    run_use_case(
        use_case_id="aml_kyc_fincrime",
        default_scenario=(
            "A newly onboarded corporate account executed circular transfers through "
            "multiple jurisdictions with high-velocity cash-out behavior."
        ),
    )
