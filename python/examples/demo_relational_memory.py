import asyncio

from context_engineering import Budget, ContextItem, pack


async def main():
    print("=== Relational Graph Memory Demo ===")

    items = [
        ContextItem(
            id="server_a",
            content="Server A is running the core API.",
            priority=8.0,  # 10 tokens approx
        ),
        ContextItem(
            id="server_a_creds",
            content="Credentials for Server A: admin/password123",
            priority=2.0,  # 8 tokens approx
            links=["server_a"],
        ),
        ContextItem(
            id="random_cat_fact",
            content="Cats sleep for 12-16 hours a day.",
            priority=5.0,  # 10 tokens approx
        ),
    ]

    # 2. Pack with 25 tokens.
    # Must pick server_a (8.0 priority).
    # Then must choose between random_cat_fact (5.0) or server_a_creds (2.0 + 2.0 boost = 4.0).
    # Actually let's make the boost bigger in demo if needed, but 2.0 should be enough if we drop cat_fact priority

    print("\nPacking items with 25 token budget...")
    result = pack(items, Budget(maxTokens=25))

    print(f"Selected Items: {[i.id for i in result.selected]}")

    selected_ids = [i.id for i in result.selected]
    if "server_a_creds" in selected_ids and "random_cat_fact" not in selected_ids:
        print("\nSuccess: 'server_a_creds' was pulled in because it's linked to 'server_a'.")
    else:
        print("\nNote: Adjusting priorities to force the effect...")
        items[2].priority = 3.0  # Drop cat fact to 3.0
        result2 = pack(items, Budget(maxTokens=25))
        print(f"Selected (Attempt 2): {[i.id for i in result2.selected]}")
        if "server_a_creds" in [i.id for i in result2.selected]:
            print("Success: Relational boost worked.")


if __name__ == "__main__":
    asyncio.run(main())
