import asyncio
from context_engineering import AgentContextManager, SqliteStore
import os


async def main():
    print("=== Agent Context Manager Demo ===")

    # 1. Initialize with a persistent SQLite store and a small budget
    if os.path.exists("demo_agent.db"):
        os.remove("demo_agent.db")

    store = SqliteStore("demo_agent.db")
    agent = AgentContextManager(memory_store=store, default_budget=100)

    # 2. Set permanent system instructions
    agent.set_system_prompt("You are a helpful assistant that summarizes code.")

    # 3. Add some long-term memory (e.g. user preferences)
    await agent.add_memory(
        "User prefers Python over Java.", id="pref_lang", salience=8.0
    )
    await agent.add_memory("User is a senior engineer.", id="user_level", salience=5.0)

    # 4. Add temporary context for this specific run
    agent.add_temporary_context(
        "CURRENT TASK: Fix the bug in the context packing algorithm where tokens were miscounted.",
        id="current_task",
        priority=9.0,
    )

    # 5. Build messages
    print(f"\nBuilding messages with budget: {agent.default_budget} tokens...")
    messages = agent.build_messages()

    for msg in messages:
        print(f"\n[{msg.role.upper()}]")
        print(msg.content)

    # 6. Show what happens with a TINY budget
    print("\n--- Shrinking budget to 40 tokens ---")
    messages_tiny = agent.build_messages(budget=40)
    for msg in messages_tiny:
        print(f"[{msg.role.upper()}] {msg.content[:50]}...")

    # 7. Trace the decision
    print("\n--- Decision Trace (40 tokens) ---")
    trace = agent.build_context(budget=40, trace=True)
    for step in trace.steps:
        print(f"- {step.id}: {step.decision} (Reason: {step.reason})")


if __name__ == "__main__":
    asyncio.run(main())
