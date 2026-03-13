import asyncio

from context_engineering import ContextItem, simulate_budgets


async def main():
    print("=== Context 'Dry Run' Simulation Demo ===")

    # Large items to force drops
    items = [
        ContextItem(id="p1_sys", content="System instructions. " * 5, priority=10.0),  # ~15 tokens
        ContextItem(id="p2_task", content="Current user task. " * 10, priority=8.0),  # ~30 tokens
        ContextItem(id="p3_memo", content="Recent memory note. " * 10, priority=6.0),  # ~30 tokens
        ContextItem(
            id="p4_long", content="Background documentation. " * 20, priority=4.0
        ),  # ~60 tokens
        ContextItem(
            id="p5_low", content="Optional low-priority tip. " * 10, priority=2.0
        ),  # ~30 tokens
    ]

    print("\nRunning simulation from 20 to 150 tokens (step=20)...")
    results = simulate_budgets(items, min_budget=20, max_budget=150, step=20)

    print("\nBudget     | Selected Items")
    print("-" * 60)
    for budget, selected in sorted(results.items()):
        print(f"{budget:<10} | {selected}")


if __name__ == "__main__":
    asyncio.run(main())
