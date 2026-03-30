# Adaptive Weights — Learn Optimal Scoring from Feedback

Demonstrates how the adaptive optimizer learns which scoring dimensions (priority, recency, salience, relevance) matter most for your use case by analysing correlations between item features and outcome quality.

## What it demonstrates

A customer support bot scenario where recency matters more than priority:

1. **Equal weights baseline:** All four scoring dimensions start at 1.0 — no preference.
2. **30-cycle training loop:** Each cycle generates support items (tickets, docs, conversation), packs them under a tight budget, simulates quality based on whether recent tickets were included, and reports the outcome.
3. **Learned insights:** After training, the optimizer reports correlations, recommended weights, and per-kind impact analysis showing which content types improve response quality.
4. **Before vs after comparison:** Same items packed with original equal weights versus learned weights, showing measurable quality improvement.
5. **State persistence:** Exports optimizer state and imports it into a fresh instance, demonstrating production persistence patterns.

## Key concepts

- **Feedback loop:** `pack()` → send to model → evaluate quality → `reportOutcome()` → weights shift
- **Pearson correlation:** The optimizer correlates each scoring dimension with outcome quality to determine which matters most
- **Kind insights:** "Including ticket items raises quality by +0.15" — actionable data about your content types
- **Segment isolation:** Multiple optimizers can share a store with different segments (e.g., per-customer, per-use-case)

## Packages used

- `@context-engineering/core` — `pack`, `ContextItem`
- `@context-engineering/adaptive` — `createContextOptimizer`, `InMemoryFeedbackStore`, weight insights

## Running

```bash
# From the repository root
pnpm install
pnpm run build:packages
npx tsx examples/adaptive-weights/index.ts
```

## Output

The script prints a training narrative with quality metrics per round, learned weight values, correlation analysis, per-kind impact tables, and a before/after comparison. No external APIs are called — quality is simulated based on item freshness to demonstrate the learning loop.
