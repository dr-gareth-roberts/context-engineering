# @context-engineering/debugger

Context Debugger diagnoses bad model outputs by tracing them back to context problems. It answers: "Why did the model give this answer? What was missing or wrong in the context?"

## Quick Start

```typescript
import { pack } from "@context-engineering/core";
import { createContextDebugger } from "@context-engineering/debugger";

const items = [
  /* your context items */
];
const budget = { maxTokens: 4096 };

const packed = pack(items, budget);
const debugger_ = createContextDebugger();
const diagnosis = debugger_.diagnose(packed);

console.log(diagnosis.overallHealth); // 'good' | 'warning' | 'critical'
console.log(diagnosis.issues); // what went wrong
console.log(diagnosis.recommendations); // how to fix it
```

## Proactive Check (Before Sending to Model)

Check your context quality before it reaches the model:

```typescript
const diagnosis = debugger_.proactiveCheck(items, budget, {
  query: "How do I configure TypeScript strict mode?",
});

if (diagnosis.overallHealth !== "good") {
  console.warn("Context issues detected:", diagnosis.issues);
  // Apply recommendations before sending
}
```

## Compare Responses (A/B Testing)

Compare two different context packs to understand which produced better results:

```typescript
const packA = pack(items, budget, { weights: { priority: 2.0 } });
const packB = pack(items, budget, { weights: { relevance: 2.0 } });

const comparison = debugger_.compareResponses(packA, 0.6, packB, 0.85);

console.log(comparison.qualityDelta); // positive = B is better
console.log(comparison.itemDiff); // what items differ between packs
console.log(comparison.insights); // human-readable analysis
```

## Issue Categories

| Category           | Meaning                                         |
| ------------------ | ----------------------------------------------- |
| `missing-context`  | Dropped items appear relevant to the query      |
| `redundancy`       | Too much overlapping content wastes tokens      |
| `stale-context`    | Most items have low recency scores              |
| `budget-waste`     | Budget is significantly under- or over-utilized |
| `wrong-priorities` | High-priority items were dropped                |
| `low-diversity`    | Context is too narrow in topic coverage         |

## Recommendation Actions

| Action                     | When Triggered                                                                  |
| -------------------------- | ------------------------------------------------------------------------------- |
| `adjust-weights`           | Stale context (increase recency) or missing relevant items (increase relevance) |
| `increase-budget`          | High-priority items dropped or budget is nearly exhausted                       |
| `add-kind`                 | Low diversity — need items from different categories                            |
| `remove-kind`              | Reserved for future use                                                         |
| `enable-compression`       | Reserved for future use                                                         |
| `enable-redundancy-filter` | High content overlap detected between items                                     |

## Custom Thresholds

```typescript
const debugger_ = createContextDebugger({
  qualityThresholds: {
    minDensity: 0.3, // minimum information density
    minDiversity: 0.4, // minimum topic diversity
    maxRedundancy: 0.3, // maximum allowed content overlap
    minFreshness: 0.2, // minimum freshness score
    minUtilization: 0.5, // minimum budget usage
    maxUtilization: 0.95, // maximum budget usage
  },
});
```

## Design Decisions

- **Threshold-based analysis**: Configurable thresholds rather than ML-based detection. Simple, predictable, and no external dependencies.
- **Reuses `quality.ts` from ce-core**: Consistent quality metrics across the ecosystem. The debugger adds diagnostic interpretation on top of the raw metrics.
- **Pure functions internally**: All analyzers are stateless pure functions, making them easy to test and compose.
- **Works with both `ContextPack` and `ContextTrace`**: Pass either format — traces are unwrapped automatically.

## Optional Integration with ce-adaptive

The debugger pairs well with `@context-engineering/adaptive` for closed-loop optimization: use the debugger to identify issues, then feed the recommendations into adaptive weight tuning.
