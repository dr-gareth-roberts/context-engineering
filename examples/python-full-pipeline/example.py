"""
Full Context Engineering Pipeline Example (Python)

Demonstrates: memory -> bridge -> pack -> place -> analyze -> compact
"""
from datetime import datetime, timezone, timedelta

from context_engineering import (
    pack,
    Budget,
    MemoryItem,
    InMemoryStore,
    to_context_item,
    memory_to_context,
    place_items,
    effective_budget,
    analyze_context,
    create_context_manager,
    create_cached_estimator,
    estimate_tokens,
    ContextItem,
)


# -- 1. Store and retrieve memories --

store = InMemoryStore()
now = datetime.now(timezone.utc)

store.put([
    MemoryItem(
        id="arch",
        content="The system uses event sourcing with CQRS pattern",
        createdAt=now.isoformat(),
        salience=0.95,
    ),
    MemoryItem(
        id="perf",
        content="P99 latency must stay under 200ms for all API endpoints",
        createdAt=now.isoformat(),
        salience=0.80,
    ),
    MemoryItem(
        id="style",
        content="Team prefers functional style with immutability by default",
        createdAt=(now - timedelta(hours=2)).isoformat(),
        salience=0.50,
    ),
    MemoryItem(
        id="old",
        content="Discussed migrating to Rust but decided against it",
        createdAt=(now - timedelta(days=1)).isoformat(),
        salience=0.20,
    ),
])

memories = store.query()
print(f"Retrieved {len(memories)} memories\n")


# -- 2. Bridge memories to context items --

items = memory_to_context(memories)
print("Bridged items:")
for item in items:
    print(f"  {item.id}: recency={item.recency}, salience={item.metadata.get('salience')}")
print()


# -- 3. Pack within token budget --

budget_tokens = effective_budget(128000, "claude")
print(f"Effective budget for Claude 128K: {budget_tokens} tokens")

packed = pack(items, Budget(maxTokens=50))  # small budget for demo
print(f"Packed: {len(packed.selected)} selected, {len(packed.dropped)} dropped")
print()


# -- 4. Position-aware placement --

placed = place_items(packed.selected, strategy="attention-optimized", model="claude")
print("Placement order (attention-optimized for Claude):")
for i, item in enumerate(placed):
    print(f"  Position {i}: {item.id}")
print()


# -- 5. Quality metrics --

quality = analyze_context(packed.selected)
print("Context quality:")
print(f"  Density:    {quality.density}")
print(f"  Diversity:  {quality.diversity}")
print(f"  Redundancy: {quality.redundancy}")
print(f"  Overall:    {quality.overall}")
print()


# -- 6. Cached token estimator --

cached = create_cached_estimator(estimate_tokens, max_size=500)
tokens1 = cached("hello world this is a test")
tokens2 = cached("hello world this is a test")  # cached
print(f"Cached estimator: {tokens1} tokens (second call uses cache)")
print()


# -- 7. Context compaction manager --

mgr = create_context_manager(
    Budget(maxTokens=200),
    system_prompt="You are a code review assistant.",
    preserve_recent_turns=2,
    summarize_after_turns=3,
)

mgr.add_turn("user", "Review this pull request for the auth system")
mgr.add_turn("assistant", "I see several issues with the JWT validation...")
mgr.add_turn("user", "Can you focus on the token refresh logic?")
mgr.add_turn("tool", "File: auth/refresh.ts\nfunction refreshToken(token: string) {\n  // ... 50 lines\n}")
mgr.add_turn("assistant", "The refresh logic has a race condition at line 23...")

compiled = mgr.compile()
print("Compaction manager:")
print(f"  Total turns: {mgr.turn_count()}")
print(f"  Compiled turns: {len(compiled.turns)}")
print(f"  Token usage: {compiled.total_tokens}/{mgr.get_token_usage()['budget']}")
for i, t in enumerate(compiled.turns):
    summary_tag = "(summary) " if t.is_summary else ""
    print(f"  Turn {i}: [{t.role}] {summary_tag}{t.content[:60]}...")
