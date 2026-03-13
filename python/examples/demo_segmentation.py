import asyncio

from context_engineering import AgentContextManager, StructuralSegmenter


async def main():
    print("=== Context Segmentation & Boundary Demo ===")

    # 1. Initialize with a smaller chunk size to force multiple segments
    # and a budget that only fits 2 out of 4 segments.
    segmenter = StructuralSegmenter(max_tokens=20)
    agent = AgentContextManager(default_budget=60, segmenter=segmenter)

    large_doc = """# Project Alpha
Alpha is a high-speed engine.

## Component 1
The ingestor handles TCP streams.

## Component 2
The processor applies logic.

## Component 3
The exporter sends data.
"""

    print("\nAdding a large document (ID: 'alpha_spec')...")
    agent.add_document(large_doc, id="alpha_spec", priority=7.0)

    print(f"Total items in context after segmentation: {len(agent.temporary_items)}")

    # 2. Build messages
    print(f"\nBuilding context with budget: {agent.default_budget} tokens...")
    messages = agent.build_messages()

    for msg in messages:
        print(f"\n[{msg.role.upper()}]")
        print(msg.content)

    # 3. Trace the decision
    print("\n--- Boundary Decision Trace ---")
    trace = agent.build_context(trace=True)
    for step in trace.steps:
        status = "✅ INCLUDED" if step.decision == "include" else "❌ DROPPED"
        print(f"{status} - {step.id}")


if __name__ == "__main__":
    asyncio.run(main())
