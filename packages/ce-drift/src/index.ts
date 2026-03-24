export type {
  DriftThresholds,
  DriftMonitorConfig,
  DriftObservation,
  DriftDimension,
  DriftSeverity,
  DriftAlert,
  DriftReport,
  DimensionReport,
  DriftMonitorState,
} from "./types.js";

export {
  analyzeRelevanceDrift,
  analyzeRedundancyCreep,
  analyzeTopicDrift,
  analyzeStaleness,
  analyzeUtilization,
  analyzeDensityDrop,
  classifySeverity,
} from "./analyzers.js";

export { generateAlerts, generateRecommendation } from "./alerts.js";

export { createDriftMonitor } from "./monitor.js";
export type { DriftMonitor } from "./monitor.js";
