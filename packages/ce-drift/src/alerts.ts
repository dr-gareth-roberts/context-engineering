import type {
  DimensionReport,
  DriftAlert,
  DriftDimension,
  DriftObservation,
  DriftSeverity,
  DriftThresholds,
} from "./types.js";
import {
  analyzeRelevanceDrift,
  analyzeRedundancyCreep,
  analyzeTopicDrift,
  analyzeStaleness,
  analyzeUtilization,
  analyzeDensityDrop,
} from "./analyzers.js";

const DEFAULT_THRESHOLDS: Required<DriftThresholds> = {
  relevanceDrift: 0.2,
  redundancyCreep: 0.4,
  topicDrift: 0.3,
  staleRatio: 0.5,
  underutilization: 0.5,
  densityDrop: 0.25,
};

/**
 * Map from dimension name to threshold key and analyzer function.
 */
const DIMENSION_CONFIG: Array<{
  dimension: DriftDimension;
  thresholdKey: keyof DriftThresholds;
  analyze: (obs: DriftObservation[], threshold: number) => DimensionReport;
}> = [
  {
    dimension: "relevance",
    thresholdKey: "relevanceDrift",
    analyze: analyzeRelevanceDrift,
  },
  {
    dimension: "redundancy",
    thresholdKey: "redundancyCreep",
    analyze: analyzeRedundancyCreep,
  },
  {
    dimension: "diversity",
    thresholdKey: "topicDrift",
    analyze: analyzeTopicDrift,
  },
  {
    dimension: "freshness",
    thresholdKey: "staleRatio",
    analyze: analyzeStaleness,
  },
  {
    dimension: "utilization",
    thresholdKey: "underutilization",
    analyze: analyzeUtilization,
  },
  {
    dimension: "density",
    thresholdKey: "densityDrop",
    analyze: analyzeDensityDrop,
  },
];

/**
 * Generate a human-readable recommendation for a given dimension and severity.
 */
export function generateRecommendation(
  dimension: DriftDimension,
  severity: DriftSeverity
): string {
  const urgency = severity === "critical" ? "Immediately" : "Consider";
  const recommendations: Record<DriftDimension, string> = {
    relevance: `${urgency} re-score and re-rank context items to restore relevance`,
    redundancy: `${urgency} deduplicate overlapping context items to reduce redundancy`,
    diversity: `${urgency} broaden retrieval sources to restore topic diversity`,
    freshness: `${urgency} prune stale retrieval items and refresh context sources`,
    utilization: `${urgency} increase budget or add more context to improve utilization`,
    density: `${urgency} compress or summarize low-density items to improve information density`,
  };
  return recommendations[dimension];
}

/**
 * Generate a human-readable message for a drift alert.
 */
function generateMessage(
  dimension: DriftDimension,
  severity: DriftSeverity,
  delta: number
): string {
  const direction =
    dimension === "redundancy" || dimension === "freshness"
      ? delta > 0
        ? "increased"
        : "decreased"
      : delta < 0
        ? "decreased"
        : "increased";

  const severityLabel = severity === "critical" ? "Critical" : "Warning";
  const dimensionLabels: Record<DriftDimension, string> = {
    relevance: "overall relevance",
    redundancy: "content redundancy",
    diversity: "topic diversity",
    freshness: "stale item ratio",
    utilization: "budget utilization",
    density: "information density",
  };

  return `${severityLabel}: ${dimensionLabels[dimension]} has ${direction} by ${Math.abs(delta).toFixed(3)}`;
}

/**
 * Run all analyzers and generate alerts for dimensions that exceed thresholds.
 */
export function generateAlerts(
  observations: DriftObservation[],
  thresholds?: DriftThresholds
): {
  dimensions: Record<DriftDimension, DimensionReport>;
  alerts: DriftAlert[];
} {
  const resolved = { ...DEFAULT_THRESHOLDS, ...thresholds };
  const dimensions = {} as Record<DriftDimension, DimensionReport>;
  const alerts: DriftAlert[] = [];

  for (const { dimension, thresholdKey, analyze } of DIMENSION_CONFIG) {
    const threshold = resolved[thresholdKey];
    const report = analyze(observations, threshold);
    dimensions[dimension] = report;

    if (report.severity !== "healthy") {
      const alert: DriftAlert = {
        dimension,
        severity: report.severity,
        currentValue: report.current,
        baselineValue: report.baseline,
        delta: report.delta,
        trend: report.trend,
        message: generateMessage(dimension, report.severity, report.delta),
        recommendation: generateRecommendation(dimension, report.severity),
        observationIndex: observations.length - 1,
      };
      alerts.push(alert);
    }
  }

  return { dimensions, alerts };
}

export { DEFAULT_THRESHOLDS };
