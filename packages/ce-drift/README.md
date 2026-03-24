# @context-engineering/drift

Context drift monitor — tracks quality metrics over a sliding window and alerts when your context pipeline silently degrades.

## Why

Context quality doesn't fail catastrophically. It drifts. Retrieval sources go stale. Redundancy creeps in as you add new sources. Relevance drops when the conversation shifts topics. This package watches six quality dimensions over time and fires alerts when any of them deviate from baseline, so you catch degradation before users notice.

## Quick Start

```typescript
import { createDriftMonitor } from "@context-engineering/drift";

const monitor = createDriftMonitor({
  windowSize: 20,
  thresholds: { relevanceDrift: 0.15, redundancyCreep: 0.3 },
  onAlert: alert => {
    console.warn(`${alert.severity}: ${alert.message}`);
    console.warn(`Recommendation: ${alert.recommendation}`);
  },
});

// After each pack/compile cycle:
monitor.observe(packed, budget);

const report = monitor.report();
if (report.drifting) {
  console.log("Drift detected since", new Date(report.since!));
  console.log("Recommendations:", report.recommendations);
}
```

## Drift Dimensions

| Dimension     | What it tracks                                | Default Threshold | Direction    |
| ------------- | --------------------------------------------- | ----------------- | ------------ |
| `relevance`   | Overall quality score declining from baseline | `0.2`             | Lower = bad  |
| `redundancy`  | Content redundancy trending upward            | `0.4`             | Higher = bad |
| `diversity`   | Topic diversity falling from baseline         | `0.3`             | Lower = bad  |
| `density`     | Information density dropping                  | `0.25`            | Lower = bad  |
| `freshness`   | Stale item ratio increasing                   | `0.5`             | Higher = bad |
| `utilization` | Budget utilisation dropping                   | `0.5`             | Lower = bad  |

## API Reference

### `createDriftMonitor(config?): DriftMonitor`

| Config Field      | Type              | Default | Description                         |
| ----------------- | ----------------- | ------- | ----------------------------------- |
| `windowSize`      | `number`          | `10`    | Sliding window of observations      |
| `thresholds`      | `DriftThresholds` | (above) | Per-dimension alert thresholds      |
| `onAlert`         | `(alert) => void` | —       | Called when drift is detected       |
| `minObservations` | `number`          | `3`     | Minimum data points before alerting |

### `DriftMonitor` Methods

| Method                        | Description                                       |
| ----------------------------- | ------------------------------------------------- |
| `observe(packed, budget)`     | Feed a `ContextPack` result for analysis          |
| `observeItems(items, budget)` | Feed raw items (when not using `pack()` directly) |
| `report()`                    | Get the current `DriftReport`                     |
| `reset()`                     | Clear all observations and baselines              |
| `history()`                   | Get the raw observation window                    |
| `exportState()`               | Serialise for persistence                         |
| `importState(state)`          | Restore from a previous export                    |

### `DriftReport`

| Field              | Type                                      | Description                             |
| ------------------ | ----------------------------------------- | --------------------------------------- |
| `status`           | `'healthy' \| 'warning' \| 'critical'`    | Worst severity across all dimensions    |
| `drifting`         | `boolean`                                 | Whether any dimension is unhealthy      |
| `since`            | `number \| null`                          | Timestamp when drift was first detected |
| `observationCount` | `number`                                  | Number of observations in the window    |
| `dimensions`       | `Record<DriftDimension, DimensionReport>` | Per-dimension breakdown                 |
| `alerts`           | `DriftAlert[]`                            | Active alerts                           |
| `recommendations`  | `string[]`                                | Deduplicated remediation suggestions    |

### `DriftAlert`

| Field            | Type             | Description                                    |
| ---------------- | ---------------- | ---------------------------------------------- |
| `dimension`      | `DriftDimension` | Which dimension drifted                        |
| `severity`       | `DriftSeverity`  | `'warning'` or `'critical'`                    |
| `currentValue`   | `number`         | Latest value                                   |
| `baselineValue`  | `number`         | Baseline (mean of first third of observations) |
| `delta`          | `number`         | Current minus baseline                         |
| `trend`          | `string`         | `'improving'`, `'stable'`, or `'degrading'`    |
| `message`        | `string`         | Human-readable alert message                   |
| `recommendation` | `string`         | Actionable remediation step                    |

## Design Decisions

**Why a sliding window instead of all-time averages?** All-time averages are slow to react. A window of 10-20 observations catches recent degradation while being resistant to noise. The baseline is computed from the first third of the window, so it naturally recalibrates as conditions change.

**Why split-half trend detection?** Comparing the mean of the first half of the window to the second half is a simple, robust way to detect monotonic trends without requiring linear regression or curve fitting. The threshold of 0.02 prevents noisy oscillations from triggering false trend changes.

**Why configurable thresholds per dimension?** Different applications tolerate different kinds of drift. A chatbot might care deeply about freshness but tolerate some redundancy. A code assistant might prioritise relevance and density. Per-dimension thresholds let you tune the monitor to your use case.

## Integration with Other Packages

### ce-core

The monitor uses `analyzeContext()` from ce-core to compute quality metrics on each observation. It accepts both `ContextPack` results (from `pack()`) and raw `ContextItem[]` arrays.

### ce-compiler

Feed compiled context results into the drift monitor to track whether the compiler's output quality holds steady over time.

### ce-immune

When the drift monitor detects critical degradation, record a failure in the immune system to create an antibody that flags similar context configurations in the future.

## License

MIT
