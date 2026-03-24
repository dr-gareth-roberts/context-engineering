# Drift Detection in Production

The Drift Detector (`ce-drift`) is the "check engine light" for context windows. It monitors quality degradation over time in long-running conversations and alerts before the model starts hallucinating.

## The Problem

In long-running agent sessions, context quality degrades silently:

- Relevant items get pushed out by noise
- Retrieval results become stale
- Redundancy creeps in as similar items accumulate
- Budget utilisation drops as items are removed but not replaced

By the time you notice (the model gives a wrong answer), the degradation has been happening for many turns.

## Setup

```ts
import { createDriftMonitor } from "@context-engineering/drift";

const monitor = createDriftMonitor({
  windowSize: 10,
  minObservations: 3,
  thresholds: {
    relevanceDrift: 0.2,
    redundancyCreep: 0.4,
    topicDrift: 0.3,
    staleRatio: 0.5,
    underutilization: 0.5,
    densityDrop: 0.25,
  },
  onAlert: alert => {
    console.warn(`[DRIFT] ${alert.dimension}: ${alert.message}`);
  },
});
```

## Feeding Observations

After each context pack/compile, feed the result to the monitor:

```ts
monitor.observe(packed, budget);
// or from raw items:
monitor.observeItems(selectedItems, budget);
```

## Reading the Report

```ts
const report = monitor.report();

console.log(report.status); // "healthy" | "warning" | "critical"
console.log(report.drifting); // boolean
console.log(report.since); // timestamp when drift started

for (const [dim, detail] of Object.entries(report.dimensions)) {
  console.log(`${dim}: ${detail.current.toFixed(2)} (trend: ${detail.trend})`);
}

for (const rec of report.recommendations) {
  console.log(`Recommendation: ${rec}`);
}
```

## Six Dimensions

| Dimension       | What degrades                   | Signal                               |
| --------------- | ------------------------------- | ------------------------------------ |
| **relevance**   | Overall quality drops           | `quality.overall` trending down      |
| **redundancy**  | Overlapping content accumulates | `quality.redundancy` trending up     |
| **diversity**   | Topic coverage narrows          | `quality.diversity` trending down    |
| **density**     | Information per token drops     | `quality.density` trending down      |
| **freshness**   | Stale items accumulate          | Fraction of items with recency < 0.2 |
| **utilisation** | Budget goes underused           | `totalTokens / maxTokens` dropping   |

## Trend Detection

Each dimension tracks a trend by comparing the first half of the observation window to the second half:

- **improving**: second half is better than first half
- **stable**: delta < 5%
- **degrading**: second half is worse than first half

## Severity

| Level      | Condition                               | Meaning                          |
| ---------- | --------------------------------------- | -------------------------------- |
| `healthy`  | Delta < threshold/2                     | Normal operation                 |
| `warning`  | Delta between threshold/2 and threshold | Starting to degrade              |
| `critical` | Delta >= threshold                      | Active degradation — take action |

## Production Pattern

```ts
while (true) {
  const items = await gatherContext();
  const packed = pack(items, budget);
  monitor.observe(packed, budget);

  const report = monitor.report();
  if (report.status === "critical") {
    await refreshRetrieval();
    await pruneStaleItems();
  }

  const response = await llm.generate(packed.selected);
}
```
