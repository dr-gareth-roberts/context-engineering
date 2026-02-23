from context_engineering.core import Budget, ContextItem, pack
from context_engineering.memory import InMemoryStore, MemoryItem

items = [
    ContextItem(id="system", content="You are a helpful assistant.", priority=10, tokens=12),
    ContextItem(id="policy", content="Always cite sources.", priority=6, tokens=10),
    ContextItem(id="notes", content="User prefers concise answers.", priority=4, tokens=8),
]

result = pack(items, Budget(maxTokens=24))
print("Pack result", result.model_dump(by_alias=True))

memory = InMemoryStore()
memory.put(MemoryItem(id="m1", content="Project uses PNPM", createdAt="2026-02-06T00:00:00"))
print("Memory query", memory.query())
