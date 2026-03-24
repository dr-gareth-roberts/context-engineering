# Core Concepts

## Context Items

A `ContextItem` is the atomic unit — one piece of context that might go into a prompt.

```ts
interface ContextItem {
  id: string; // Unique identifier
  content: string; // The actual text
  priority?: number; // 0-10, higher = more important
  recency?: number; // 0-1, higher = more recent
  kind?: string; // Category: "system", "retrieval", "conversation", "query", "tool", etc.
  tokens?: number; // Pre-computed token count (estimated if omitted)
  score?: number; // Override computed score
  metadata?: Record<string, unknown>; // Arbitrary metadata
  embedding?: number[]; // Vector embedding for semantic operations
  taskId?: string; // For causal compaction — which task this belongs to
  isOutcome?: boolean; // For causal compaction — is this a task outcome?
  compressions?: Compression[]; // Pre-computed compressed versions
}
```

## Scoring

Every item gets a score that determines its selection priority:

```
score = priority * 1.0 + recency * 0.7 + salience * 0.5 + relevance * 0.0
```

- **priority** (0-10): How important is this item? System prompts are 10, old conversation turns might be 2.
- **recency** (0-1): How recent? 1.0 = just happened, 0.0 = ancient history.
- **salience** (from `metadata.salience`): Domain-specific importance signal.
- **relevance** (0-1): Activates when a query is provided. Uses BM25 or embedding similarity.

Weights are customisable via `createScorer({ priority: 2.0, recency: 0.0 })`.

## Budgets

A `Budget` defines the token constraint:

```ts
interface Budget {
  maxTokens: number; // Maximum tokens available
  reserveTokens?: number; // Reserve for model response (subtracted from max)
}
```

Effective budget = `maxTokens - reserveTokens`.

## Packing

`pack()` is the core algorithm: greedy score-based selection.

1. Score all items
2. Sort by score (descending)
3. Greedily select items until the budget is exhausted
4. If compression is enabled, try compressed versions of items that don't fit
5. Return `ContextPack` with `selected`, `dropped`, `totalTokens`, `stats`

## Token Estimation

By default, tokens are estimated with a word-count heuristic (`words * 1.3`). For accurate counts, use provider-specific estimators:

```ts
import { presets } from "@context-engineering/providers";

const result = pack(items, budget, {
  tokenEstimator: presets.openai.estimator, // tiktoken-based
});
```

## Kinds

The `kind` field categorizes items. Kinds are used by:

- **Cache Topology**: "system" → static prefix, "retrieval" → volatile suffix
- **Allocation**: Distribute budget across kinds with target ratios
- **Compiler**: Map items to declared slots by kind
- **Quality Analysis**: Diversity metrics track kind distribution

Common kinds: `"system"`, `"tool"`, `"retrieval"`, `"conversation"`, `"query"`, `"memory"`, `"example"`.

## Volatility

Items have three volatility levels for cache optimisation:

| Level     | Changes       | Examples                       | Cache behaviour                      |
| --------- | ------------- | ------------------------------ | ------------------------------------ |
| `static`  | Rarely        | System prompt, tools, schemas  | Stable prefix — maximises cache hits |
| `session` | Per session   | Conversation history, memories | Middle — changes between sessions    |
| `request` | Every request | User query, RAG results        | Volatile suffix — always different   |

## Quality Metrics

`analyzeContext()` returns five dimensions:

| Metric         | Measures                                     | Good                            |
| -------------- | -------------------------------------------- | ------------------------------- |
| **density**    | Information per token (unique words / total) | Higher = more information-dense |
| **diversity**  | Topic spread (unique bigrams / total)        | Higher = broader coverage       |
| **freshness**  | Recency distribution                         | Higher = more up-to-date        |
| **redundancy** | Content overlap between items                | Lower = less waste              |
| **overall**    | Weighted combination                         | Higher = better                 |

## Next

- [Your First Pipeline](./First-Pipeline.md) — compose these concepts
- [Package Overview](./Package-Overview.md) — see what's available
