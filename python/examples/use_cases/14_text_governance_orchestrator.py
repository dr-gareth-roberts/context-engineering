from __future__ import annotations

from _common import run_use_case


if __name__ == "__main__":
    run_use_case(
        use_case_id="text_governance_orchestrator",
        default_scenario=(
            "A draft customer incident notification contains engineer emails, an internal ticket URL, "
            "and overly technical mitigation details that need compliant external phrasing."
        ),
    )
