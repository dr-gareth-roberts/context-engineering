from __future__ import annotations

from _common import run_use_case

if __name__ == "__main__":
    run_use_case(
        use_case_id="catastrophe_claims_pipeline",
        default_scenario=(
            "After a major hurricane, 48k claims arrived in 36 hours; many include "
            "partial documentation, geolocation mismatches, and potential duplicate filings."
        ),
    )
