import asyncio
from context_engineering import ContextItem
from context_engineering.eval import Backtester, EvalCase


async def main():
    print("=== Production Backtesting & Evaluation Demo ===")

    tester = Backtester(redundancy_threshold=0.9)

    # CASE 1: Conflict Resolution
    # Goal: Verify that the superseder logic works under pressure.
    case1_items = [
        ContextItem(id="old_val", content="Price is $10", priority=5.0),
        ContextItem(
            id="new_val", content="Price is $12", priority=9.0, supersedes="old_val"
        ),
        ContextItem(id="other", content="Store is open.", priority=5.0),
    ]
    tester.add_case(
        EvalCase(
            name="Conflict Resolution",
            items=case1_items,
            budget=100,
            ground_truth_ids={"new_val", "other"},  # 'old_val' should be purged
        )
    )

    # CASE 2: Hierarchy Coverage
    # Goal: Verify parent covers children.
    case2_items = [
        ContextItem(
            id="parent", content="Global security policy summary.", priority=10.0
        ),
        ContextItem(
            id="child1",
            content="Detail about passwords.",
            priority=5.0,
            parent_id="parent",
        ),
        ContextItem(
            id="child2",
            content="Detail about firewalls.",
            priority=5.0,
            parent_id="parent",
        ),
    ]
    tester.add_case(
        EvalCase(
            name="Hierarchy Coverage",
            items=case2_items,
            budget=100,
            ground_truth_ids={"parent"},  # children should be omitted
        )
    )

    # CASE 3: Impossible Budget (Forced Failure)
    # Goal: Prove the framework catches when we miss critical info.
    case3_items = [
        ContextItem(
            id="critical_1",
            content="Very long critical instruction. " * 10,
            priority=10.0,
        ),  # approx 20 tokens
        ContextItem(
            id="critical_2",
            content="Another very long critical rule. " * 10,
            priority=10.0,
        ),  # approx 20 tokens
    ]
    tester.add_case(
        EvalCase(
            name="Starvation Test",
            items=case3_items,
            budget=15,  # Too small for both!
            ground_truth_ids={"critical_1", "critical_2"},
        )
    )

    results = tester.run_all()
    tester.print_report(results)


if __name__ == "__main__":
    asyncio.run(main())
