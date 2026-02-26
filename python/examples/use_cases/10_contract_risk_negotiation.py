from __future__ import annotations

from _common import run_use_case

if __name__ == "__main__":
    run_use_case(
        use_case_id="contract_risk_negotiation",
        default_scenario=(
            "A strategic vendor insists on unlimited liability carve-outs and broad "
            "data use rights in a multiyear enterprise agreement."
        ),
    )
