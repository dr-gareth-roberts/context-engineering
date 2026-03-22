# @context-engineering/adaptive

Adaptive context learning for LLM applications. This package observes which context items correlate with good model outputs and automatically adjusts scoring weights over time, creating a feedback loop that improves context selection without manual tuning.

## Install

```bash
pnpm add @context-engineering/adaptive
```

## Quick Start

Three steps: create an optimizer, pack context, report outcomes.

```typescript
import { createContextOptimizer } from "@context-engineering/adaptive";

// 1. Create an optimizer
const optimizer = createContextOptimizer({
  feedback: "explicit",
  minSamples: 20,
  learningRate: 0.1,
});

// 2. Pack items — weights adapt automatically over time
const result = await optimizer.pack(items, { maxTokens: 4000 });

// Send result.selected to your LLM...
const response = await llm.complete(result.selected);

// 3. Report the outcome so the optimizer can learn
await optimizer.reportOutcome(result.optimizerId, {
  quality: 0.85,
  accepted: true,
});
```

After enough feedback cycles (default: 20), the optimizer begins shifting scoring weights toward dimensions that correlate with higher quality outcomes.

## API Reference

### `createContextOptimizer(config: OptimizerConfig): ContextOptimizer`

Factory function to create an optimizer instance.

#### `OptimizerConfig`

| Field            | Type                                   | Default                 | Description                                            |
| ---------------- | -------------------------------------- | ----------------------- | ------------------------------------------------------ |
| `feedback`       | `'implicit' \| 'explicit' \| 'metric'` | required                | How feedback is collected                              |
| `qualityMetric`  | `(response, context) => number`        | —                       | Custom quality function (required for `'metric'` mode) |
| `minSamples`     | `number`                               | `20`                    | Minimum observations before adjusting weights          |
| `learningRate`   | `number`                               | `0.1`                   | How aggressively to shift weights (0-1)                |
| `regularization` | `number`                               | `0.01`                  | Pulls weights toward defaults to prevent overfitting   |
| `baseWeights`    | `ScoringWeights`                       | all `1.0`               | Starting weights and regularization target             |
| `store`          | `FeedbackStore`                        | `InMemoryFeedbackStore` | Where to persist feedback data                         |
| `segment`        | `string`                               | `'default'`             | Isolate learning by application/scenario               |

### `ContextOptimizer`

#### `pack(items, budget, options?): Promise<OptimizedPack>`

Packs items using learned weights. Records feedback for later analysis. Returns an `OptimizedPack` extending `ContextPack` with `optimizerId` and `weightsUsed`.

#### `reportOutcome(optimizerId, outcome): Promise<void>`

Reports the quality outcome of a previous pack operation.

```typescript
interface Outcome {
  quality: number; // 0-1 score
  accepted?: boolean; // Did user accept the output?
  latency?: number; // Response latency in ms
  response?: string; // Model's response text
  metadata?: Record<string, unknown>;
}
```

#### `getInsights(): Promise<WeightInsights>`

Returns current learning state: correlations, recommended weights, per-kind insights, and confidence level.

#### `reset(): Promise<void>`

Clears all feedback data for the current segment and returns to base weights.

#### `exportState(): Promise<OptimizerState>`

Exports current optimizer state for persistence or sharing between instances.

#### `importState(state: OptimizerState): Promise<void>`

Imports previously exported state, restoring learned weights without replaying feedback.

### `WeightOptimizer`

Lower-level class for direct weight computation from feedback records.

```typescript
import { WeightOptimizer } from "@context-engineering/adaptive";

const wo = new WeightOptimizer({
  learningRate: 0.1,
  regularization: 0.01,
  baseWeights: { priority: 1, recency: 1, salience: 1, relevance: 1 },
  minSamples: 20,
});

const weights = wo.optimize(feedbackRecords);
const correlations = wo.computeCorrelations(feedbackRecords);
const kindInsights = wo.computeKindInsights(feedbackRecords);
const confidence = wo.computeConfidence(feedbackRecords);
```

### Feedback Stores

#### `InMemoryFeedbackStore`

Array-backed store for testing and development. Data is lost on process exit.

#### `FileFeedbackStore`

JSON-lines file store for local development. Uses advisory file locking for safety.

```typescript
import { FileFeedbackStore } from "@context-engineering/adaptive";

const store = new FileFeedbackStore("./feedback.jsonl");
const optimizer = createContextOptimizer({
  feedback: "explicit",
  store,
});
```

### Types

All types are exported: `OptimizerConfig`, `Outcome`, `FeedbackRecord`, `ItemFeature`, `WeightInsights`, `OptimizedPack`, `OptimizerState`, `FeedbackStore`.

## Design Decisions

### Why EMA over gradient descent

Exponential moving average is simpler, works well with small sample sizes, and produces interpretable weight updates. Gradient descent requires careful hyperparameter tuning and can oscillate with sparse feedback. EMA provides stable, monotonic convergence that practitioners can reason about.

### Why regularization

L2 regularization pulls weights back toward base values, preventing the optimizer from overfitting to small or unrepresentative samples. Without it, a few lucky outcomes could push weights to extremes that perform poorly on the next batch of inputs.

### Why a minSamples threshold

Statistical correlations computed from fewer than ~20 samples are unreliable. The threshold prevents the optimizer from making premature adjustments based on noise. Below this threshold, the optimizer returns base weights unchanged.

### Why per-kind insights

Different item types (code, documentation, conversation history, tool results) contribute differently to output quality. Per-kind analysis surfaces which categories of context help most, enabling users to adjust their context pipelines or pre-filtering strategies beyond just weight tuning.

## Integration with Other Packages

### ce-core

The adaptive optimizer wraps `pack()` from `@context-engineering/core`, adding feedback tracking and weight learning on top. All `PackOptions` are forwarded transparently.

```typescript
import { createContextOptimizer } from "@context-engineering/adaptive";

// The optimizer calls pack() internally with learned weights
const result = await optimizer.pack(items, budget, {
  allowCompression: true,
  query: "user question",
});
```

### ce-memory

Use a memory store to provide context items, then let the adaptive optimizer learn which items matter most.

```typescript
import { FileStore } from "@context-engineering/memory";
import { createContextOptimizer } from "@context-engineering/adaptive";

const memory = new FileStore("./memory.jsonl");
const items = await memory.query({ limit: 100 });

const optimizer = createContextOptimizer({ feedback: "explicit" });
const packed = await optimizer.pack(items, { maxTokens: 4000 });
```
