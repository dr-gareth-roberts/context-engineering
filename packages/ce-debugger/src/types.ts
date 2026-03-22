import type {
  ContextItem,
  ContextPack,
  ContextTrace,
  Budget,
  QueryInput,
  PackOptions,
} from "@context-engineering/core";
import type { ContextQuality } from "@context-engineering/core";

export interface DebuggerConfig {
  qualityThresholds?: QualityThresholds;
}

export interface QualityThresholds {
  minDensity?: number; // default 0.3
  minDiversity?: number; // default 0.4
  maxRedundancy?: number; // default 0.3
  minFreshness?: number; // default 0.2
  minUtilization?: number; // default 0.5
  maxUtilization?: number; // default 0.95
}

export interface Diagnosis {
  overallHealth: "good" | "warning" | "critical";
  quality: ContextQuality;
  issues: DiagnosticIssue[];
  recommendations: Recommendation[];
  droppedAnalysis: DroppedAnalysis;
}

export type IssueSeverity = "info" | "warning" | "critical";

export type IssueCategory =
  | "missing-context"
  | "redundancy"
  | "stale-context"
  | "budget-waste"
  | "wrong-priorities"
  | "low-diversity";

export interface DiagnosticIssue {
  severity: IssueSeverity;
  category: IssueCategory;
  message: string;
  evidence: Record<string, unknown>;
}

export type RecommendationAction =
  | "adjust-weights"
  | "increase-budget"
  | "add-kind"
  | "remove-kind"
  | "enable-compression"
  | "enable-redundancy-filter";

export interface Recommendation {
  action: RecommendationAction;
  description: string;
  suggestedChange: Record<string, unknown>;
  estimatedImpact: string;
}

export interface DroppedAnalysis {
  totalDropped: number;
  droppedByKind: Record<string, number>;
  highPriorityDropped: ContextItem[];
  potentiallyRelevant: ContextItem[];
}

export interface DiagnoseOptions {
  query?: QueryInput;
  responseQuality?: number; // 0-1, optional quality score of model response
}

export interface ComparisonResult {
  packAQuality: ContextQuality;
  packBQuality: ContextQuality;
  itemDiff: {
    onlyInA: string[];
    onlyInB: string[];
    shared: string[];
  };
  qualityDelta: number;
  insights: string[];
}

export interface ContextDebugger {
  diagnose(
    pack: ContextPack | ContextTrace,
    options?: DiagnoseOptions
  ): Diagnosis;
  proactiveCheck(
    items: ContextItem[],
    budget: Budget,
    options?: DiagnoseOptions & { packOptions?: PackOptions }
  ): Diagnosis;
  compareResponses(
    packA: ContextPack,
    responseQualityA: number,
    packB: ContextPack,
    responseQualityB: number
  ): ComparisonResult;
}
