# @context-engineering/router

Model Router that analyzes context complexity and routes to the cheapest model that can handle it, saving 40-60% on API costs.

## How It Works

Instead of always sending requests to your most capable (and expensive) model, the router:

1. Analyzes the **complexity** of your context across six dimensions
2. Routes to the **cheapest model** whose complexity threshold covers the request
3. Optionally **learns from outcomes** to refine routing over time
4. Supports **quality-based fallback** to upgrade on the fly when the cheap model underperforms

## Quick Start

```typescript
import { createContextRouter } from "@context-engineering/router";
import type { ModelTier } from "@context-engineering/router";

const models: ModelTier[] = [
  {
    model: "gpt-4.1-mini",
    maxComplexity: 0.3,
    costPer1kInput: 0.0004,
    costPer1kOutput: 0.0016,
    maxTokens: 16000,
  },
  {
    model: "gpt-4.1",
    maxComplexity: 0.6,
    costPer1kInput: 0.002,
    costPer1kOutput: 0.008,
    maxTokens: 128000,
    capabilities: ["tool-calling"],
  },
  {
    model: "claude-opus-4-6",
    maxComplexity: 1.0,
    costPer1kInput: 0.015,
    costPer1kOutput: 0.075,
    maxTokens: 200000,
    capabilities: ["tool-calling", "vision"],
  },
];

const router = createContextRouter({ models });

const decision = router.route(contextItems, { maxTokens: 4000 });
console.log(decision.model); // 'gpt-4.1-mini' for simple context
console.log(decision.reasoning); // explains the routing decision
console.log(decision.complexity); // 0.15
```

## Adaptive Router

The adaptive router learns from past outcomes and promotes to higher tiers when a model consistently underperforms.

```typescript
import { createAdaptiveRouter } from "@context-engineering/router";

const router = createAdaptiveRouter({
  models,
  minSamples: 20, // learn after 20 decisions
  learningRate: 0.1,
});

// Route as normal
const decision = router.route(items, budget);

// After getting a response, report quality (0-1)
router.reportOutcome(decision, 0.85);

// Check what the router has learned
const insights = router.getInsights();
console.log(insights.modelStats);
console.log(`Potential savings: $${insights.potentialSavings}`);
```

## Fallback

Route to the cheap model first, then automatically retry with a more capable model if quality is too low.

```typescript
import {
  routeWithFallback,
  createContextRouter,
} from "@context-engineering/router";

const router = createContextRouter({ models });

const result = await routeWithFallback(
  router,
  items,
  budget,
  async model => {
    // Your model call logic here
    const response = await callLLM(model, prompt);
    return response.text;
  },
  {
    qualityThreshold: 0.7,
    qualityCallback: response => evaluateQuality(response),
    maxRetries: 1,
  }
);

console.log(result.finalModel); // the model that actually produced the result
console.log(result.fellBack); // true if the primary model was insufficient
console.log(result.attempts); // number of model calls made
```

## Standalone Complexity Analysis

Use the complexity analyzer directly without routing.

```typescript
import { analyzeComplexity } from "@context-engineering/router";

const breakdown = analyzeComplexity(items);
console.log(breakdown.overall); // 0.42
console.log(breakdown.dimensions.diversity); // 0.65
console.log(breakdown.dimensions.toolCallCount); // 0.3
console.log(breakdown.dimensions.dependencyDepth); // 0.2

// Custom weights to emphasize what matters for your use case
const weighted = analyzeComplexity(items, {
  toolCallCount: 0.4, // heavily weight tool usage
  diversity: 0.1, // de-emphasize topic diversity
});
```

## Complexity Dimensions

| Dimension           | What it measures                               | Normalization        |
| ------------------- | ---------------------------------------------- | -------------------- |
| `diversity`         | Topic diversity via unique bigram ratio        | 0-1 from ce-core     |
| `density`           | Information density via unique words per token | 0-1 from ce-core     |
| `dependencyDepth`   | Max depth of `dependsOn` chains                | depth / 10, clamped  |
| `toolCallCount`     | Fraction of items with tool-related kinds      | count / total        |
| `multilinguality`   | Distinct Unicode script blocks in content      | (scripts - 1) / 4    |
| `averageItemLength` | Mean token count per item                      | mean / 2000, clamped |

## Model Tier Configuration Guide

When configuring model tiers, set `maxComplexity` thresholds based on what each model can handle well:

- **0.0 - 0.3**: Simple retrieval, single-topic Q&A, short responses. Use your cheapest model.
- **0.3 - 0.6**: Multi-step reasoning, moderate tool usage, cross-topic synthesis. Use a mid-tier model.
- **0.6 - 1.0**: Complex multi-lingual tasks, deep dependency chains, heavy tool orchestration. Use your most capable model.

Set `capabilities` to ensure models with specific features (vision, tool-calling) are selected when the context requires them.

## Design Decisions

**Why heuristic complexity analysis (no ML)?** Fast, deterministic, and zero-dependency. Runs in microseconds with no model calls, making it suitable for the hot path of every request. The six dimensions capture the signals that correlate with model difficulty in practice.

**Why configurable weights?** Different applications have different complexity profiles. A coding assistant cares more about dependency depth; a translation service cares more about multilinguality. Weights let you tune without forking.

**Why cheapest-first selection?** The router sorts by cost ascending and picks the first model that meets all constraints. This guarantees minimum cost for any given complexity level.
