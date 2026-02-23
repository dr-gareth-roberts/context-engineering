import asyncio
from context_engineering import InMemoryStore, MemoryItem

async def mock_summarizer(text: str) -> str:
    words = text.split()
    summary = " ".join(words[:3]) + "..."
    return f"Summary of: {summary}"

async def main():
    print("=== Memory Flashcards (Consolidation) Demo ===")
    
    store = InMemoryStore()
    
    store.put(MemoryItem(
        id="current_task",
        content="Fixing the production bug in the payment gateway.",
        salience=0.9,
        createdAt="2026-02-20T10:00:00Z"
    ))
    
    store.put(MemoryItem(
        id="old_note",
        content="Random observation about the coffee machine in the breakroom being slightly loud today.",
        salience=0.1,
        createdAt="2026-02-10T10:00:00Z"
    ))
    
    print("\nBefore consolidation:")
    for item in store.query():
        status = "[SUMMARY]" if item.is_summary else "[RAW]"
        print(f"- {item.id} {status} (Salience: {item.salience}): {item.content}")
        
    print("\nRunning maintenance (Consolidating items with salience < 0.3)...")
    count = await store.consolidate(mock_summarizer, salience_threshold=0.3)
    print(f"Items consolidated: {count}")
    
    print("\nAfter consolidation:")
    for item in store.query():
        status = "[SUMMARY]" if item.is_summary else "[RAW]"
        print(f"- {item.id} {status} (Salience: {item.salience}): {item.content}")

    items = {i.id: i for i in store.query()}
    if items["old_note"].is_summary and not items["current_task"].is_summary:
        print("\nSuccess: Only low-salience items were converted to flashcards.")

if __name__ == "__main__":
    asyncio.run(main())
