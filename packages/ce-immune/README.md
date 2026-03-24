# @context-engineering/immune

Context Immune System — learns from past context failures and screens future packs against known toxic patterns.

## Why

When a context configuration causes a bad LLM response, you want to make sure it never happens again. The immune system fingerprints failed context configurations (kind distribution, priority/recency statistics, redundancy, staleness) and creates "antibodies." Future context packs are screened against these antibodies before being sent to a model, catching similar toxic patterns with configurable similarity thresholds.

## Quick Start

```typescript
import { createImmuneSystem } from "@context-engineering/immune";

const immune = createImmuneSystem({
  matchThreshold: 0.75,
  onAlert: result => {
    if (!result.safe) {
      console.error(
        "Blocked:",
        result.blocked.map(a => a.diagnosis)
      );
    }
  },
});

// Record a failure (creates an antibody)
immune.recordFailure({
  items: failedContextItems,
  budget: { maxTokens: 4000 },
  symptom: "Model hallucinated API endpoints",
  diagnosis: "Too many stale documentation items crowded out current API spec",
  severity: "block",
});

// Screen future packs
const result = immune.screen(newContextItems, { maxTokens: 4000 });
if (!result.safe) {
  // Context matches a known failure pattern — don't send it
  console.log(result.blocked[0].diagnosis);
  console.log(result.blocked[0].similarity); // 0.82
}
```

## How Fingerprinting Works

Each context configuration is reduced to a feature vector:

| Feature              | What it captures                                      |
| -------------------- | ----------------------------------------------------- |
| `kindRatios`         | Distribution of item kinds (e.g., 40% code, 30% docs) |
| `priorityStats`      | Min, max, mean, std of priority values                |
| `recencyStats`       | Min, max, mean, std of recency values                 |
| `tokenUtilization`   | Ratio of tokens used to budget                        |
| `itemCount`          | Number of items                                       |
| `stalenessRatio`     | Fraction of items with recency < 0.2                  |
| `redundancyEstimate` | Fraction of item pairs with >0.8 Jaccard overlap      |

Fingerprints are compared using a weighted combination of cosine similarity (for kind ratios), Euclidean distance (for stats), and absolute differences (for scalar features).

## API Reference

### `createImmuneSystem(config?): ImmuneSystem`

| Config Field     | Type               | Default | Description                             |
| ---------------- | ------------------ | ------- | --------------------------------------- |
| `matchThreshold` | `number`           | `0.7`   | Similarity threshold for antibody match |
| `maxAntibodies`  | `number`           | `100`   | Max antibodies retained (oldest pruned) |
| `onAlert`        | `(result) => void` | —       | Called when screening finds issues      |

### `ImmuneSystem` Methods

| Method                            | Description                                                     |
| --------------------------------- | --------------------------------------------------------------- |
| `recordFailure(record)`           | Create an antibody from a failure. Returns `Antibody`.          |
| `screen(items, budget?)`          | Screen items against known patterns. Returns `ScreeningResult`. |
| `getAntibodies()`                 | List all antibodies                                             |
| `removeAntibody(id)`              | Remove a specific antibody                                      |
| `reset()`                         | Clear all antibodies                                            |
| `exportState()` / `importState()` | Serialize/restore for persistence                               |

### `FailureRecord`

| Field       | Type                   | Default     | Description                       |
| ----------- | ---------------------- | ----------- | --------------------------------- |
| `items`     | `ContextItem[]`        | required    | The items that caused the failure |
| `budget`    | `Budget`               | required    | Budget at time of failure         |
| `symptom`   | `string`               | required    | What went wrong                   |
| `diagnosis` | `string`               | `'Unknown'` | Why it went wrong                 |
| `severity`  | `'warning' \| 'block'` | `'warning'` | Whether to warn or hard-block     |

### `ScreeningResult`

| Field             | Type               | Description                                |
| ----------------- | ------------------ | ------------------------------------------ |
| `safe`            | `boolean`          | `true` if no blocking antibodies fired     |
| `warnings`        | `ScreeningAlert[]` | Matched antibodies with `warning` severity |
| `blocked`         | `ScreeningAlert[]` | Matched antibodies with `block` severity   |
| `antibodiesFired` | `Antibody[]`       | All antibodies that matched                |

## Design Decisions

**Why fingerprint-based matching instead of exact item comparison?** Context configurations are rarely identical between requests. The same failure pattern manifests with different specific items but the same structural signature — too many stale docs, extreme priority skew, heavy redundancy. Fingerprinting captures these structural properties so antibodies generalize across specific item sets.

**Why weighted multi-dimension similarity?** Kind distribution matters more than item count for predicting failures. The weight vector (kind ratios 0.2, priority/recency stats 0.15 each, token utilization 0.15, redundancy 0.15, staleness 0.1, item count 0.1) reflects empirical importance. The 0.7 default threshold is conservative — it catches clear matches without false positives on structurally different configurations.

**Why two severity levels (warning vs. block)?** Warnings flag potentially problematic configurations without stopping the pipeline. Blocks prevent known-bad patterns from reaching the model. This separation lets you be aggressive with warnings while keeping blocks for confirmed, reproducible failure patterns.

## Integration with Other Packages

### ce-core

Fingerprinting uses `ContextItem` properties (kind, priority, recency, tokens) and budget information. Works with both raw items and packed results.

### ce-adversarial

When adversarial probes reveal vulnerabilities, record the attacked context as a failure to create protective antibodies that catch similar patterns in production.

### ce-drift

When the drift monitor detects critical degradation, create an immune system antibody from the degraded context snapshot so the pattern is recognized if it recurs.

## License

MIT
