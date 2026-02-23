import asyncio
from context_engineering import pack, Budget, ContextItem

async def main():
    print("=== Information Negation & Delta Demo ===")
    
    items = [
        ContextItem(
            id="db_endpoint_v1",
            content="DATABASE_URL=postgres://old-cluster:5432",
            priority=8.0
        ),
        ContextItem(
            id="db_endpoint_v2",
            content="DATABASE_URL=postgres://new-production-cluster:5432",
            priority=9.0,
            supersedes="db_endpoint_v1"
        ),
        ContextItem(
            id="general_info",
            content="User is a senior developer.",
            priority=5.0
        )
    ]
    
    budget = Budget(maxTokens=100)
    
    print("\nPacking items where v2 supersedes v1...")
    result = pack(items, budget)
    
    print(f"\nSelected Items ({result.total_tokens} tokens):")
    for item in result.selected:
        tag = " [SUPERSERDER]" if item.supersedes else ""
        print(f"- {item.id}{tag}: {item.content}")
        
    print("\nDropped Items:")
    for item in result.dropped:
        print(f"- {item.id}")

    selected_ids = [i.id for i in result.selected]
    if "db_endpoint_v2" in selected_ids and "db_endpoint_v1" not in selected_ids:
        print("\nSuccess: The stale 'db_endpoint_v1' was automatically pruned.")

if __name__ == "__main__":
    asyncio.run(main())
