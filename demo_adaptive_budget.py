import asyncio
from context_engineering import AgentContextManager

async def main():
    print("=== Adaptive Token Budget Demo ===")
    
    agent = AgentContextManager(agent_id="adaptive_agent", default_budget=512)
    
    for i in range(10):
        agent.add_temporary_context(f"Background info chunk #{i}. " * 5, id=f"info_{i}", priority=5.0)

    user_input_1 = "Hello, how are you?"
    new_budget_1 = agent.adapt_budget(user_input_1)
    print("\n[Scenario 1] Input: '" + user_input_1 + "'")
    print(f"Adapted Budget: {new_budget_1} tokens")
    
    packed_1 = agent.build_context()
    print(f"Selected Items: {len(packed_1.selected)}")

    user_input_2 = "Please analyze the logs and compare the performance metrics."
    new_budget_2 = agent.adapt_budget(user_input_2)
    print("\n[Scenario 2] Input: '" + user_input_2 + "'")
    print(f"Adapted Budget: {new_budget_2} tokens")
    
    packed_2 = agent.build_context()
    print(f"Selected Items: {len(packed_2.selected)}")

    if new_budget_2 > new_budget_1:
        print("\nSuccess: Budget dynamically expanded for the complex request.")

if __name__ == "__main__":
    asyncio.run(main())
