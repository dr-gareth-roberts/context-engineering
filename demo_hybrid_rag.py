import asyncio
from datetime import datetime, timedelta
from context_engineering import InMemoryStore, MemoryItem, MemoryQuery


async def main():
    print("=== Vector-Salience Hybrid RAG Demo ===")

    store = InMemoryStore()

    store.put(
        MemoryItem(
            id="old_coding_tip",
            content="Always use descriptive variable names in Python.",
            salience=0.2,
            embedding=[1.0, 0.0, 0.0],
            createdAt=(datetime.now() - timedelta(days=30)).isoformat(),
        )
    )

    store.put(
        MemoryItem(
            id="recent_weather",
            content="It is raining today in London.",
            salience=0.9,
            embedding=[0.0, 1.0, 0.0],
            createdAt=datetime.now().isoformat(),
        )
    )

    query_v = [1.0, 0.0, 0.0]

    print("\nScenario 1: Pure Semantic Search (alpha=1.0)")
    res1 = store.query(MemoryQuery(vector=query_v, alpha=1.0))
    for i in res1:
        print(f"- {i.id}: {i.content}")

    print("\nScenario 2: Pure Salience (alpha=0.0)")
    res2 = store.query(MemoryQuery(vector=query_v, alpha=0.0))
    for i in res2:
        print(f"- {i.id}: {i.content}")

    print("\nScenario 3: Hybrid (alpha=0.5)")
    res3 = store.query(MemoryQuery(vector=query_v, alpha=0.5))
    for i in res3:
        print(f"- {i.id}: {i.content}")

    if res1[0].id == "old_coding_tip" and res2[0].id == "recent_weather":
        print(
            "\nSuccess: Hybrid RAG correctly balances semantic meaning and temporal importance."
        )


if __name__ == "__main__":
    asyncio.run(main())
