from __future__ import annotations

from _common import run_use_case


if __name__ == "__main__":
    run_use_case(
        use_case_id="soc_incident_commander",
        default_scenario=(
            "Multiple privileged logins from unusual geographies followed by mass token "
            "creation and abnormal outbound data transfer from two finance hosts."
        ),
    )
