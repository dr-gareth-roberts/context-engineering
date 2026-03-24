# @context-engineering/core

Core context engineering algorithms — pack, diff, trace, place, quality analysis, cache-topology-aware packing, budget allocation, differential sessions, composable pipelines, cost estimation, and BEADS agent handoff.

## Installation

```bash
npm install @context-engineering/core
```

## Quick Start

```ts
import { pack } from "@context-engineering/core";

const result = pack(
  [
    { id: "docs", content: "API reference...", priority: 8 },
    { id: "history", content: "Previous conversation...", priority: 3 },
  ],
  { maxTokens: 4096 }
);

console.log(result.selected); // items that fit the budget
console.log(result.totalTokens); // tokens used
```

### Composable Pipeline

Chain operations in a fluent API:

```ts
import { pipeline } from "@context-engineering/core";

const result = pipeline(8000)
  .add(systemPrompt, tools, documents, query)
  .allocate([
    { kind: "system", targetRatio: 0.3 },
    { kind: "retrieval", targetRatio: 0.5 },
    { kind: "query", targetRatio: 0.2 },
  ])
  .cacheTopology({ provider: "anthropic" })
  .place("attention-optimized")
  .qualityGate({ minOverall: 0.5 })
  .session(mySession)
  .build();
```

### Cost Estimation

See what prefix caching saves you:

```ts
import {
  packWithCacheTopology,
  estimateCost,
  projectCosts,
} from "@context-engineering/core";

const pack = packWithCacheTopology(items, { maxTokens: 8000 });
const cost = estimateCost(pack, "claude-sonnet-4-6");
console.log(
  `Saving $${cost.savings.toFixed(4)} per request (${cost.savingsPercent}%)`
);

const monthly = projectCosts(pack, "claude-sonnet-4-6", 10000, {
  requestsPerDay: 500,
});
console.log(`Monthly savings: $${monthly.monthlyEstimate.monthlySavings}/mo`);
```

### Agent Handoff (BEADS)

Serialise context for agent-to-agent handoff via git:

```ts
import { createHandoff, pickupHandoff } from "@context-engineering/core";

// Agent A: hand off context
const handoff = createHandoff(pack, { agent: "agent-a", includeDropped: true });
fs.writeFileSync(".beads/issues.jsonl", handoff.jsonl);
// git add . && git push

// Agent B: pick up context
const jsonl = fs.readFileSync(".beads/issues.jsonl", "utf-8");
const pickup = pickupHandoff(jsonl);
session.setItems(pickup.items); // resume where Agent A left off
```

## API Summary

### Core Functions

| Export                                       | Description                                                        |
| -------------------------------------------- | ------------------------------------------------------------------ |
| `pack(items, budget, options?)`              | Greedy score-based context packing into a token budget             |
| `packStream(items, budget, options?)`        | Async generator variant of `pack` — yields items as selected       |
| `tracePack(items, budget, options?)`         | Pack with step-by-step decision trace for debugging                |
| `diff(before, after)`                        | Compare two packs or item arrays (added/removed/kept/changed)      |
| `estimateTokens(text, options?)`             | Token count estimation (default: word heuristic)                   |
| `createScorer(weights?)`                     | Build a custom `ItemScorer` with priority/recency/salience weights |
| `createCachedEstimator(estimator, options?)` | LRU-cached wrapper around any `TokenEstimator`                     |

### Placement & Quality

| Export                            | Description                                                |
| --------------------------------- | ---------------------------------------------------------- |
| `placeItems(items, options?)`     | Reorder items for optimal model attention placement        |
| `effectiveBudget(tokens, model?)` | De-rate token budget based on model attention degradation  |
| `analyzeContext(items)`           | Quality metrics: density, diversity, freshness, redundancy |
| `analyzeContextPack(pack)`        | Quality metrics for a `ContextPack`                        |

### Cache Topology

| Export                                                    | Description                             |
| --------------------------------------------------------- | --------------------------------------- |
| `packWithCacheTopology(items, budget, options?, config?)` | Pack with stable prefix for cache reuse |
| `classifyVolatility(item)`                                | Classify item as static/session/request |

### Budget Allocation

| Export                                                     | Description                                           |
| ---------------------------------------------------------- | ----------------------------------------------------- |
| `packWithAllocation(items, budget, allocations, options?)` | Per-kind budget allocation with min/max/target ratios |

### Sessions

| Export                                   | Description                                                                                                            |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `createSession(options: SessionOptions)` | Stateful context session with differential tracking (`SessionOptions = { budget: Budget; packOptions?: PackOptions }`) |

### Pipeline

| Export             | Description                                         |
| ------------------ | --------------------------------------------------- |
| `pipeline(budget)` | Composable pipeline builder chaining all operations |

### Cost Estimation

| Export                                               | Description                                               |
| ---------------------------------------------------- | --------------------------------------------------------- |
| `estimateCost(pack, model, outputTokens?, pricing?)` | Per-request cost with cache savings                       |
| `projectCosts(pack, model, count, options?)`         | Multi-request projection with monthly estimates           |
| `MODEL_PRICING`                                      | Built-in pricing for Claude, GPT-4.1, GPT-4o, o3, o4-mini |

### BEADS Agent Handoff

| Export                               | Description                              |
| ------------------------------------ | ---------------------------------------- |
| `createHandoff(pack, options?)`      | Serialise context pack to BEADS JSONL    |
| `pickupHandoff(jsonl)`               | Recover context items from BEADS JSONL   |
| `contextItemToBeads(item, options?)` | Convert ContextItem to BEADS issue       |
| `beadsToContextItem(issue)`          | Convert BEADS issue back to ContextItem  |
| `readBeadsJSONL(input)`              | Parse BEADS JSONL string                 |
| `writeBeadsJSONL(issues)`            | Serialise BEADS issues to JSONL          |
| `mergeBeadsJSONL(existing, updates)` | Merge BEADS JSONL by ID                  |
| `getReadyIssues(issues)`             | Filter to ready (open, unblocked) issues |

### Bridge

| Export                                | Description                                      |
| ------------------------------------- | ------------------------------------------------ |
| `toContextItem(memory, options?)`     | Convert a `MemoryItem` to a scored `ContextItem` |
| `memoryToContext(memories, options?)` | Batch convert `MemoryItem[]` to `ContextItem[]`  |

### Compaction

| Export                          | Description                                        |
| ------------------------------- | -------------------------------------------------- |
| `createContextManager(options)` | Automatic context compaction for multi-turn agents |

### Async Packing

| Export                               | Description                                     |
| ------------------------------------ | ----------------------------------------------- |
| `packAsync(items, budget, options?)` | Async version of `pack` with the same interface |

### Scoring

| Export                                                    | Description                                |
| --------------------------------------------------------- | ------------------------------------------ |
| `createCausalScorer(issues, activeTaskId?, baseWeights?)` | Causal-aware scoring for agent task graphs |
| `createQueryAwareScorer(query, options?)`                 | Query-relevance-boosted scoring            |

### Deduplication

| Export                    | Description                       |
| ------------------------- | --------------------------------- |
| `eliminateRedundancy`     | Async context deduplication       |
| `eliminateRedundancySync` | Synchronous context deduplication |

### Prompt Formatting

| Export               | Description                           |
| -------------------- | ------------------------------------- |
| `toMessages`         | Convert packed items to message array |
| `formatForAnthropic` | Format packed items for Anthropic API |
| `formatForOpenAI`    | Format packed items for OpenAI API    |

### Telemetry & Remote

| Export                      | Description                         |
| --------------------------- | ----------------------------------- |
| `createWebhookReporter`     | Telemetry webhook reporter          |
| `fetchBudgetRecommendation` | Fetch remote budget recommendations |

### Search

| Export            | Description                 |
| ----------------- | --------------------------- |
| `createBM25Index` | BM25 full-text search index |

### Types

| Export             | Description                                                                                                                                                                                                          |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ContextItem`      | Input item with `id`, `content`, `priority`, `recency`, `kind`, `tokens`, `score`, `metadata`, `embedding`, `taskId`, `isOutcome`, `dependsOn`, `compressions`, `supersedes`, `parentId`, `cost`, `latency`, `links` |
| `Budget`           | `{ maxTokens, reserveTokens? }`                                                                                                                                                                                      |
| `ContextPack`      | Pack result with `selected`, `dropped`, `totalTokens`, `stats`, `notes`                                                                                                                                              |
| `ContextPlan`      | Plan with `budget`, `items`, `strategy?`, `options?`                                                                                                                                                                 |
| `PackDiff`         | Diff result with `added`, `removed`, `kept`, `changed`                                                                                                                                                               |
| `ContextTrace`     | Trace result with `pack`, `steps[]`, `createdAt`                                                                                                                                                                     |
| `CacheAwarePack`   | Extends ContextPack with `cacheKey`, `cacheableTokens`, `cacheEfficiency`                                                                                                                                            |
| `AllocatedPack`    | Extends ContextPack with per-kind allocation results                                                                                                                                                                 |
| `SessionPack`      | Session compile result with differential `delta`                                                                                                                                                                     |
| `PipelineResult`   | Pipeline output with all stage metadata                                                                                                                                                                              |
| `CostEstimate`     | Per-request cost breakdown with cache savings                                                                                                                                                                        |
| `CostProjection`   | Multi-request projection with monthly estimates                                                                                                                                                                      |
| `BeadsIssue`       | BEADS issue type for agent handoff                                                                                                                                                                                   |
| `ContextQuality`   | Quality metrics: `density`, `diversity`, `freshness`, `redundancy`, `overall`                                                                                                                                        |
| `AttentionProfile` | Model attention curve: `name`, `effectiveCapacity`, `positionWeights[]`                                                                                                                                              |
| `KindAllocation`   | Per-kind budget: `kind`, `targetRatio`, `minRatio?`, `maxRatio?`                                                                                                                                                     |

### Errors

| Export                    | Code                                         |
| ------------------------- | -------------------------------------------- |
| `ContextEngineeringError` | Base class for all ce-core errors            |
| `ValidationError`         | `VALIDATION_ERROR` — invalid items or budget |
| `BudgetExceededError`     | `BUDGET_EXCEEDED` — reserve >= max           |
| `EstimationError`         | `ESTIMATION_ERROR` — token estimator failure |

### Schemas (Zod)

`ContextItemSchema`, `BudgetSchema`, `CompressionSchema`, `ContextPlanSchema`, `KindAllocationSchema`, `CacheConfigSchema`, `PlacementOptionsSchema`, `CompactionOptionsSchema`

### Schema Utilities

| Export               | Description                                                       |
| -------------------- | ----------------------------------------------------------------- |
| `validateWithSchema` | Validate any value against a Zod schema, returning a typed result |
| `validatePackInputs` | Validate `items` and `budget` before packing                      |

### Utilities

`noopLogger`, `defaultTokenEstimator`, `defaultItemScorer`, `ATTENTION_PROFILES`, `MODEL_PRICING`

## License

MIT
