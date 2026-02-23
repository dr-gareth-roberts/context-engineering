import asyncio
from context_engineering import pack, Budget, ContextItem

async def main():
    print("=== Hierarchical Context Tree Demo ===")
    
    items = [
        ContextItem(
            id="project_alpha",
            content="Project Alpha is a high-speed data processing system built in Rust.",
            priority=9.0,
        ),
        ContextItem(
            id="alpha_logic",
            content="The processing logic uses SIMD instructions for 10x throughput.",
            priority=7.0,
            parent_id="project_alpha"
        ),
        ContextItem(
            id="alpha_auth",
            content="Authentication is handled via OAuth2 and JWT tokens.",
            priority=7.0,
            parent_id="project_alpha"
        )
    ]
    
    print("\n--- Scenario 1: Parent fits budget ---")
    budget1 = Budget(maxTokens=100)
    res1 = pack(items, budget1)
    print(f"Selected: {[i.id for i in res1.selected]}")
    
    selected_ids = [i.id for i in res1.selected]
    if "project_alpha" in selected_ids and "alpha_logic" not in selected_ids:
        print("Success: Children were correctly omitted as parent summary covers the context.")

if __name__ == "__main__":
    asyncio.run(main())
