# @ce/core

Core context engineering algorithms -- pack, diff, trace, score, and token estimation.

## Installation

```bash
npm install @ce/core
```

## Quick Start

```ts
import { pack } from '@ce/core';

const result = pack(
  [
    { id: 'docs', content: 'API reference...', priority: 8 },
    { id: 'history', content: 'Previous conversation...', priority: 3 },
  ],
  { maxTokens: 4096 }
);

console.log(result.selected); // items that fit the budget
console.log(result.totalTokens); // tokens used
```

## API Summary

### Core Functions

| Export | Description |
|---|---|
| `pack(items, budget, options?)` | Greedy score-based context packing into a token budget |
| `packStream(items, budget, options?)` | Async generator variant of `pack` -- yields items as selected |
| `tracePack(items, budget, options?)` | Pack with step-by-step decision trace for debugging |
| `diff(before, after)` | Compare two packs or item arrays (added/removed/kept/changed) |
| `estimateTokens(text, options?)` | Token count estimation (default: word heuristic) |
| `createScorer(weights?)` | Build a custom `ItemScorer` with priority/recency/salience weights |
| `createCachedEstimator(estimator, options?)` | LRU-cached wrapper around any `TokenEstimator` |
| `toContextItem(memory, options?)` | Convert a `MemoryItem` to a scored `ContextItem` |
| `memoryToContext(memories, options?)` | Batch convert `MemoryItem[]` to `ContextItem[]` |
| `placeItems(items, options?)` | Reorder items for optimal model attention placement |
| `effectiveBudget(tokens, model?)` | De-rate token budget based on model attention degradation |
| `analyzeContext(items)` | Quality metrics: density, diversity, freshness, redundancy |
| `analyzeContextPack(pack)` | Quality metrics for a `ContextPack` |
| `createContextManager(options)` | Automatic context compaction manager for multi-turn agents |

### Types

| Export | Description |
|---|---|
| `ContextItem` | Input item with `id`, `content`, `priority`, `recency`, `compressions` |
| `Budget` | `{ maxTokens, reserveTokens? }` |
| `ContextPack` | Pack result with `selected`, `dropped`, `totalTokens`, `stats` |
| `PackDiff` | Diff result with `added`, `removed`, `kept`, `changed` |
| `ContextTrace` | Trace result with `pack`, `steps[]`, `createdAt` |
| `PackOptions` | Options: `tokenEstimator`, `scorer`, `summarizer`, `weights`, `allowCompression` |
| `ScoringWeights` | `{ priority?, recency?, salience? }` -- defaults: 1.0, 0.7, 0.5 |
| `TokenEstimator` | `(text, options?) => number` |
| `ItemScorer` | `(item: ContextItem) => number` |
| `ContextQuality` | Quality metrics result with `density`, `diversity`, `freshness`, `redundancy`, `overall` |
| `AttentionProfile` | Model attention curve: `name`, `effectiveCapacity`, `positionWeights[]` |
| `ContextManager` | Compaction manager: `addTurn()`, `addItems()`, `compile()`, `getTokenUsage()` |
| `Turn` | Conversation turn: `role`, `content`, `tokens?`, `isSummary?` |
| `BridgeOptions` | Memory-to-item options: `priority?`, `recencyHalfLife?`, `now?`, `kind?` |

### Errors

| Export | Code |
|---|---|
| `ValidationError` | `VALIDATION_ERROR` -- invalid items or budget |
| `BudgetExceededError` | `BUDGET_EXCEEDED` -- reserve >= max |
| `EstimationError` | `ESTIMATION_ERROR` -- token estimator failure |

### Schemas (Zod)

`ContextItemSchema`, `BudgetSchema`, `CompressionSchema`, `PackOptionsSchema`

### Utilities

`noopLogger`, `defaultTokenEstimator`, `defaultItemScorer`, `ATTENTION_PROFILES`

## License

MIT
