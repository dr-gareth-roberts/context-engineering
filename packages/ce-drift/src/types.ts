import type { ContextQuality } from "@context-engineering/core";

export interface DriftThresholds {
  /** Alert when relevance drops this much from baseline (0-1). Default: 0.2 */
  relevanceDrift?: number;
  /** Alert when redundancy increases by this much above the windowed baseline (0-1). Default: 0.4 */
  redundancyCreep?: number;
  /** Alert when topic diversity falls below baseline by this much. Default: 0.3 */
  topicDrift?: number;
  /** Alert when the stale-item ratio increases by this much above the windowed baseline. Default: 0.5 */
  staleRatio?: number;
  /** Alert when budget utilization drops by this much below the windowed baseline. Default: 0.5 */
  underutilization?: number;
  /** Alert when information density drops by this much. Default: 0.25 */
  densityDrop?: number;
}

export interface DriftMonitorConfig {
  /** Number of recent observations to analyze. Default: 10 */
  windowSize?: number;
  /** Thresholds for each drift dimension */
  thresholds?: DriftThresholds;
  /** Called when drift is detected */
  onAlert?: (alert: DriftAlert) => void;
  /** Minimum observations before alerting. Default: 3 */
  minObservations?: number;
}

export interface DriftObservation {
  timestamp: number;
  quality: ContextQuality;
  itemCount: number;
  totalTokens: number;
  budgetUtilization: number;
  staleItemCount: number;
  topKinds: Record<string, number>;
}

export type DriftDimension =
  | "relevance"
  | "redundancy"
  | "diversity"
  | "density"
  | "freshness"
  | "utilization";

export type DriftSeverity = "healthy" | "warning" | "critical";

export interface DriftAlert {
  dimension: DriftDimension;
  severity: DriftSeverity;
  currentValue: number;
  baselineValue: number;
  delta: number;
  trend: "improving" | "stable" | "degrading";
  message: string;
  recommendation: string;
  observationIndex: number;
}

export interface DriftReport {
  status: DriftSeverity;
  drifting: boolean;
  since: number | null;
  observationCount: number;
  dimensions: Record<DriftDimension, DimensionReport>;
  alerts: DriftAlert[];
  recommendations: string[];
}

export interface DimensionReport {
  current: number;
  baseline: number;
  delta: number;
  trend: "improving" | "stable" | "degrading";
  severity: DriftSeverity;
  history: number[];
}

export interface DriftMonitorState {
  observations: DriftObservation[];
  config: DriftMonitorConfig;
}
