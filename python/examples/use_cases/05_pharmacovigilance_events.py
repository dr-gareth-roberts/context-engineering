from __future__ import annotations

from _common import run_use_case

if __name__ == "__main__":
    run_use_case(
        use_case_id="pharmacovigilance_events",
        default_scenario=(
            "Recent call-center transcripts and physician notes suggest elevated severe "
            "adverse reactions after off-label dosage adjustments."
        ),
    )
