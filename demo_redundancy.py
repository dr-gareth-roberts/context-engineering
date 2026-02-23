import asyncio
from context_engineering import pack, Budget, ContextItem

async def main():
    print("=== Semantic Redundancy Elimination Demo ===")
    
    items = [
        ContextItem(
            id="intro_a",
            content="The user is a software engineer living in New York.",
            priority=8.0,
            embedding=[1.0, 0.1, 0.0]
        ),
        ContextItem(
            id="intro_b",
            content="User is a developer based in NYC.",
            priority=7.0,
            embedding=[0.95, 0.12, 0.0]
        ),
        ContextItem(
            id="hobbies",
            content="They enjoy cycling and photography.",
            priority=5.0,
            embedding=[0.0, 0.0, 1.0]
        )
    ]
    
    budget = Budget(maxTokens=200)
    
    print("\n--- Packing WITHOUT redundancy check ---")
    res1 = pack(items, budget)
    print(f"Selected: {[i.id for i in res1.selected]}")

    print("\n--- Packing WITH redundancy check (threshold=0.9) ---")
    res2 = pack(items, budget, redundancy_threshold=0.9)
    print(f"Selected: {[i.id for i in res2.selected]}")
    
    selected_ids = [i.id for i in res2.selected]
    if "intro_a" in selected_ids and "intro_b" not in selected_ids:
        print("\nSuccess: Redundant item 'intro_b' was automatically eliminated.")

if __name__ == "__main__":
    asyncio.run(main())
