# Your First Pipeline

The `pipeline()` API chains context engineering operations into a single fluent builder. It composes packing, allocation, cache topology, placement, quality gates, sessions, and templating.

## Basic Pipeline

```ts
import { pipeline } from "@context-engineering/core";

const result = pipeline(4096)
  .add(
    {
      id: "sys",
      content: "You are a helpful assistant.",
      priority: 10,
      kind: "system",
    },
    {
      id: "query",
      content: "How do I use the API?",
      priority: 9,
      kind: "query",
    }
  )
  .addMany(retrievedDocs, { kind: "retrieval" })
  .build();

console.log(result.selected); // items that fit
console.log(result.totalTokens); // tokens used
console.log(result.stages); // ["pack"]
```

## With Budget Allocation

Distribute budget across categories instead of flat greedy packing:

```ts
const result = pipeline(8000)
  .add(systemPrompt)
  .addMany(ragResults, { kind: "retrieval" })
  .addMany(chatHistory, { kind: "conversation" })
  .allocate([
    { kind: "system", targetRatio: 0.15, minTokens: 500 },
    { kind: "retrieval", targetRatio: 0.5 },
    { kind: "conversation", targetRatio: 0.35 },
  ])
  .build();

console.log(result.allocations); // per-kind breakdown
console.log(result.allocationEfficiency); // how close to target ratios
```

## With Cache Topology

Maximise prefix cache hits by ordering items by volatility:

```ts
const result = pipeline(8000)
  .add(systemPrompt, toolDefs) // static — stable prefix
  .addMany(ragResults, { kind: "retrieval" }) // volatile — suffix
  .cacheTopology({ provider: "anthropic" })
  .build();

console.log(result.cacheKey); // stable hash of prefix
console.log(result.cacheEfficiency); // 0-1
console.log(result.cacheableTokens); // tokens in stable prefix
```

## Full Pipeline

```ts
const result = pipeline({ maxTokens: 8000, reserveTokens: 500 })
  .add(systemPrompt)
  .addMemories(await store.search("topic"), { kind: "memory" })
  .addMany(ragDocs, { kind: "retrieval" })
  .addMany(conversation, { kind: "conversation" })
  .allocate([
    { kind: "system", targetRatio: 0.15 },
    { kind: "memory", targetRatio: 0.1 },
    { kind: "retrieval", targetRatio: 0.5 },
    { kind: "conversation", targetRatio: 0.25 },
  ])
  .cacheTopology({ provider: "anthropic" })
  .place("attention-optimized", "claude")
  .withQuery("user question", { embeddingProvider })
  .qualityGate({ minOverall: 0.6 })
  .session(mySession)
  .template()
  .build();

// result.selected      — packed, placed, cache-optimized items
// result.quality        — quality metrics
// result.cacheKey       — stable prefix cache key
// result.delta          — what changed since last compile
// result.messages       — formatted for API
// result.stages         — ["bridge", "query", "allocate", "cacheTopology", "place", "quality", "session", "template"]
```

## Stage Execution Order

Regardless of the order you chain methods, stages execute in this order:

1. **Query** — set relevance scoring
2. **Allocation** / **Cache Topology** / **Pack** — select items (allocation and topology are mutually exclusive primary strategies; standard pack is the fallback)
3. **Placement** — reorder for model attention patterns
4. **Quality Gate** — drop lowest-scored items until quality threshold is met
5. **Session** — compute differential from previous compile
6. **Template** — format into API messages

## Async Pipeline

For pipelines that need embedding-based operations:

```ts
const result = await pipeline(8000)
  .add(systemPrompt)
  .addMany(items)
  .withQuery("search term", { embeddingProvider })
  .options({ redundancyConfig: { embeddingProvider, threshold: 0.85 } })
  .buildAsync();
```

`buildAsync()` has full parity with `build()` but supports async pack variants.

## Python Equivalent

```python
from context_engineering import create_pipeline

result = create_pipeline(8000) \
    .add(system_prompt) \
    .add_many(rag_docs, defaults={"kind": "retrieval"}) \
    .allocate([
        {"kind": "system", "target_ratio": 0.15},
        {"kind": "retrieval", "target_ratio": 0.50},
    ]) \
    .cache_topology({"provider": "anthropic"}) \
    .quality_gate({"min_overall": 0.6}) \
    .build()
```
