from __future__ import annotations

from _common import run_use_case

if __name__ == "__main__":
    run_use_case(
        use_case_id="legacy_modern_migration",
        default_scenario=(
            "A monolithic COBOL-based claims platform must be decomposed to services "
            "without downtime during quarterly reporting season."
        ),
    )
