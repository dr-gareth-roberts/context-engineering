import type {
  DimensionReport,
  DriftObservation,
  DriftSeverity,
} from "./types.js";

/**
 * Compute the average of a numeric array.
 */
function mean(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((sum, v) => sum + v, 0) / values.length;
}

/**
 * Determine the trend by comparing the first half of the window to the second half.
 * Returns "improving" if second half is better, "degrading" if worse,
 * "stable" otherwise. The `higherIsBetter` flag controls directionality.
 */
function computeTrend(
  values: number[],
  higherIsBetter: boolean
): "improving" | "stable" | "degrading" {
  if (values.length < 2) return "stable";
  const mid = Math.floor(values.length / 2);
  const firstHalf = mean(values.slice(0, mid));
  const secondHalf = mean(values.slice(mid));
  const diff = secondHalf - firstHalf;
  const threshold = 0.02;
  if (Math.abs(diff) < threshold) return "stable";
  if (higherIsBetter) {
    return diff > 0 ? "improving" : "degrading";
  }
  return diff < 0 ? "improving" : "degrading";
}

/**
 * Classify severity based on how far delta exceeds threshold.
 */
export function classifySeverity(
  delta: number,
  threshold: number
): DriftSeverity {
  const absDelta = Math.abs(delta);
  if (absDelta >= threshold) return "critical";
  if (absDelta >= threshold / 2) return "warning";
  return "healthy";
}

/**
 * Create a healthy dimension report when there are no observations.
 */
function emptyReport(): DimensionReport {
  return {
    current: 0,
    baseline: 0,
    delta: 0,
    trend: "stable",
    severity: "healthy",
    history: [],
  };
}

/**
 * Analyze relevance drift: overall quality score declining from baseline.
 */
export function analyzeRelevanceDrift(
  observations: DriftObservation[],
  threshold: number
): DimensionReport {
  if (observations.length === 0) return emptyReport();

  const values = observations.map(o => o.quality.overall);
  const baselineCount = Math.max(1, Math.floor(observations.length / 3));
  const baseline = mean(values.slice(0, baselineCount));
  const current = values[values.length - 1];
  const delta = current - baseline;
  const trend = computeTrend(values, true);
  const severity = delta < 0 ? classifySeverity(delta, threshold) : "healthy";

  return { current, baseline, delta, trend, severity, history: values };
}

/**
 * Analyze redundancy creep: redundancy score trending upward.
 */
export function analyzeRedundancyCreep(
  observations: DriftObservation[],
  threshold: number
): DimensionReport {
  if (observations.length === 0) return emptyReport();

  const values = observations.map(o => o.quality.redundancy);
  const baselineCount = Math.max(1, Math.floor(observations.length / 3));
  const baseline = mean(values.slice(0, baselineCount));
  const current = values[values.length - 1];
  const delta = current - baseline;
  const trend = computeTrend(values, false);
  const severity = delta > 0 ? classifySeverity(delta, threshold) : "healthy";

  return { current, baseline, delta, trend, severity, history: values };
}

/**
 * Analyze topic drift: diversity score declining from baseline.
 */
export function analyzeTopicDrift(
  observations: DriftObservation[],
  threshold: number
): DimensionReport {
  if (observations.length === 0) return emptyReport();

  const values = observations.map(o => o.quality.diversity);
  const baselineCount = Math.max(1, Math.floor(observations.length / 3));
  const baseline = mean(values.slice(0, baselineCount));
  const current = values[values.length - 1];
  const delta = current - baseline;
  const trend = computeTrend(values, true);
  const severity = delta < 0 ? classifySeverity(delta, threshold) : "healthy";

  return { current, baseline, delta, trend, severity, history: values };
}

/**
 * Analyze staleness: ratio of stale items (recency < 0.2) increasing.
 */
export function analyzeStaleness(
  observations: DriftObservation[],
  threshold: number
): DimensionReport {
  if (observations.length === 0) return emptyReport();

  const values = observations.map(o =>
    o.itemCount > 0 ? o.staleItemCount / o.itemCount : 0
  );
  const baselineCount = Math.max(1, Math.floor(observations.length / 3));
  const baseline = mean(values.slice(0, baselineCount));
  const current = values[values.length - 1];
  const delta = current - baseline;
  const trend = computeTrend(values, false);
  const severity = delta > 0 ? classifySeverity(delta, threshold) : "healthy";

  return { current, baseline, delta, trend, severity, history: values };
}

/**
 * Analyze utilization: budget utilization dropping below acceptable level.
 */
export function analyzeUtilization(
  observations: DriftObservation[],
  threshold: number
): DimensionReport {
  if (observations.length === 0) return emptyReport();

  const values = observations.map(o => o.budgetUtilization);
  const baselineCount = Math.max(1, Math.floor(observations.length / 3));
  const baseline = mean(values.slice(0, baselineCount));
  const current = values[values.length - 1];
  const delta = current - baseline;
  const trend = computeTrend(values, true);
  const severity = delta < 0 ? classifySeverity(delta, threshold) : "healthy";

  return { current, baseline, delta, trend, severity, history: values };
}

/**
 * Analyze density drop: information density declining from baseline.
 */
export function analyzeDensityDrop(
  observations: DriftObservation[],
  threshold: number
): DimensionReport {
  if (observations.length === 0) return emptyReport();

  const values = observations.map(o => o.quality.density);
  const baselineCount = Math.max(1, Math.floor(observations.length / 3));
  const baseline = mean(values.slice(0, baselineCount));
  const current = values[values.length - 1];
  const delta = current - baseline;
  const trend = computeTrend(values, true);
  const severity = delta < 0 ? classifySeverity(delta, threshold) : "healthy";

  return { current, baseline, delta, trend, severity, history: values };
}
