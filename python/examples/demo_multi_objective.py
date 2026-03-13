import asyncio

from context_engineering import AgentContextManager, ScoringWeights


async def main():
    print("=== Multi-Objective Scoring Demo ===")

    agent = AgentContextManager(agent_id="mo_agent", default_budget=100)

    agent.add_temporary_context(
        "Complex financial analysis results.",
        id="expensive_data",
        priority=9.0,
        cost=1.0,
        latency=1.0,
    )

    agent.add_temporary_context(
        "Simple weather summary.", id="cheap_data", priority=6.0, cost=0.1, latency=0.1
    )

    print("\nScenario 1: Performance Focus (Weights: cost=0, latency=0)")
    perf_weights = ScoringWeights(cost=0.0, latency=0.0)
    res1 = agent.build_context(budget=50, weights=perf_weights)
    print(f"Selected: {[i.id for i in res1.selected]}")

    print("\nScenario 2: Efficiency Focus (Weights: cost=-10, latency=-10)")
    eff_weights = ScoringWeights(cost=-10.0, latency=-10.0)
    res2 = agent.build_context(budget=50, weights=eff_weights)
    print(f"Selected: {[i.id for i in res2.selected]}")

    if res1.selected[0].id == "expensive_data" and res2.selected[0].id == "cheap_data":
        print(
            "\nSuccess: Multi-objective scoring correctly toggled between relevance and efficiency."
        )


if __name__ == "__main__":
    asyncio.run(main())
