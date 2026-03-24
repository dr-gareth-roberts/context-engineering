# Context Immune System

The Immune System (`ce-immune`) learns from past context configurations that caused failures and develops "antibodies" — rules that screen future packs automatically to prevent recurring failure patterns.

## Key Insight

Individual context items can be fine on their own, but certain _combinations_ are toxic. "API docs" is fine. "Code examples" is fine. "API docs from v1 + code examples from v2" is a known failure pattern that causes hallucinated endpoints. The immune system detects these combination-level patterns.

## How It Works

1. **Record** a failure: items + budget + what went wrong
2. **Fingerprint** extraction: the system extracts a feature vector from the context configuration
3. **Antibody** generation: a matching rule is created from the fingerprint
4. **Screening**: future packs are compared against all antibodies; similar configurations trigger warnings or blocks

## Fingerprints

A fingerprint captures the _shape_ of a context configuration, not the specific content:

| Feature              | What it captures                                          |
| -------------------- | --------------------------------------------------------- |
| `kindsPresent`       | Which item kinds are in the context                       |
| `kindRatios`         | Proportion of each kind (e.g., 60% retrieval, 30% system) |
| `priorityStats`      | Min/max/mean/std of priority scores                       |
| `recencyStats`       | Min/max/mean/std of recency scores                        |
| `tokenUtilization`   | How full the budget is (0-1)                              |
| `stalenessRatio`     | Fraction of items with recency < 0.2                      |
| `redundancyEstimate` | Fraction of item pairs with >0.8 word overlap             |
| `itemCount`          | Number of items                                           |

Two fingerprints are compared using weighted similarity (cosine for kind ratios, normalised Euclidean for stats, absolute difference for scalars).

## Usage

```ts
import { createImmuneSystem } from "@context-engineering/immune";

const immune = createImmuneSystem({ matchThreshold: 0.7 });

// Record a failure
immune.recordFailure({
  items: packedItems,
  budget: { maxTokens: 4000 },
  symptom: "Model hallucinated a non-existent API endpoint",
  diagnosis:
    "Stale API docs combined with new code examples created version mismatch",
  severity: "block",
});

// Screen future packs
const screening = immune.screen(newItems, { maxTokens: 4000 });

if (!screening.safe) {
  for (const alert of screening.blocked) {
    console.error(
      `BLOCKED: ${alert.symptom} (similarity: ${alert.similarity.toFixed(2)})`
    );
  }
  for (const alert of screening.warnings) {
    console.warn(
      `WARNING: ${alert.symptom} (similarity: ${alert.similarity.toFixed(2)})`
    );
  }
}
```

## Severity Levels

| Level     | Effect on `screening.safe` | When to use                                                    |
| --------- | -------------------------- | -------------------------------------------------------------- |
| `warning` | `safe` remains `true`      | First occurrence, minor quality issues                         |
| `block`   | `safe` becomes `false`     | Repeated failures, hallucinations, security-sensitive contexts |

## Integration with Adversarial Testing

The immune system pairs naturally with `ce-adversarial`:

```ts
const report = await tester.probe(items, budget, evaluator);

for (const attack of report.attacks) {
  if (attack.severity === "critical") {
    immune.recordFailure({
      items: attackedItems,
      budget,
      symptom: `Critically vulnerable to ${attack.attack}`,
      diagnosis: attack.description,
      severity: "block",
    });
  }
}
```

## State Management

```ts
// Export for persistence
const state = immune.exportState();
// state.antibodies — array of learned antibodies
// state.failureCount — total failures recorded

// Import later
immune.importState(state);

// Manage antibodies
immune.getAntibodies(); // list all
immune.removeAntibody("ab-3"); // remove one
immune.reset(); // clear all
```
