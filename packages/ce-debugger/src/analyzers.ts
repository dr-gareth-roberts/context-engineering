import type {
  ContextItem,
  ContextPack,
  QueryInput,
} from "@context-engineering/core";
import type { ContextQuality } from "@context-engineering/core";
import { computeRelevance, normalizeQuery } from "@context-engineering/core";
import type {
  DiagnosticIssue,
  Recommendation,
  QualityThresholds,
  DroppedAnalysis,
} from "./types.js";

const DEFAULT_THRESHOLDS: Required<QualityThresholds> = {
  minDensity: 0.3,
  minDiversity: 0.4,
  maxRedundancy: 0.3,
  minFreshness: 0.2,
  minUtilization: 0.5,
  maxUtilization: 0.95,
};

interface AnalyzerResult {
  issue?: DiagnosticIssue;
  recommendation?: Recommendation;
}

export function resolveThresholds(
  custom?: QualityThresholds
): Required<QualityThresholds> {
  return { ...DEFAULT_THRESHOLDS, ...custom };
}

export function analyzeRedundancy(
  quality: ContextQuality,
  thresholds: Required<QualityThresholds>
): AnalyzerResult {
  if (quality.redundancy > thresholds.maxRedundancy) {
    return {
      issue: {
        severity: "warning",
        category: "redundancy",
        message: `High content redundancy detected (${quality.redundancy} > ${thresholds.maxRedundancy} threshold)`,
        evidence: {
          redundancy: quality.redundancy,
          threshold: thresholds.maxRedundancy,
        },
      },
      recommendation: {
        action: "enable-redundancy-filter",
        description:
          "Enable redundancy filtering to remove overlapping content before packing",
        suggestedChange: { redundancyConfig: { threshold: 0.7 } },
        estimatedImpact: `Could reduce redundancy from ${quality.redundancy} to below ${thresholds.maxRedundancy}`,
      },
    };
  }
  return {};
}

export function analyzeFreshness(
  quality: ContextQuality,
  thresholds: Required<QualityThresholds>
): AnalyzerResult {
  if (quality.freshness < thresholds.minFreshness) {
    return {
      issue: {
        severity: "warning",
        category: "stale-context",
        message: `Context is stale — freshness ${quality.freshness} is below ${thresholds.minFreshness} threshold`,
        evidence: {
          freshness: quality.freshness,
          threshold: thresholds.minFreshness,
        },
      },
      recommendation: {
        action: "adjust-weights",
        description:
          "Increase recency weight to prioritize more recent context items",
        suggestedChange: { weights: { recency: 1.5 } },
        estimatedImpact:
          "More recent items will be selected, improving freshness",
      },
    };
  }
  return {};
}

export function analyzeDiversity(
  quality: ContextQuality,
  thresholds: Required<QualityThresholds>
): AnalyzerResult {
  if (quality.diversity < thresholds.minDiversity) {
    return {
      issue: {
        severity: "warning",
        category: "low-diversity",
        message: `Low content diversity (${quality.diversity} < ${thresholds.minDiversity} threshold) — context may be too narrow`,
        evidence: {
          diversity: quality.diversity,
          threshold: thresholds.minDiversity,
        },
      },
      recommendation: {
        action: "add-kind",
        description:
          "Add items from different kinds to broaden the context window",
        suggestedChange: { diversifyKinds: true },
        estimatedImpact:
          "Broader topic coverage should improve model reasoning",
      },
    };
  }
  return {};
}

export function analyzeUtilization(
  pack: ContextPack,
  thresholds: Required<QualityThresholds>
): AnalyzerResult {
  const utilization =
    pack.budget.maxTokens > 0 ? pack.totalTokens / pack.budget.maxTokens : 0;

  if (utilization < thresholds.minUtilization) {
    return {
      issue: {
        severity: "info",
        category: "budget-waste",
        message: `Low budget utilization (${Math.round(utilization * 100)}%) — ${pack.budget.maxTokens - pack.totalTokens} tokens unused`,
        evidence: {
          utilization,
          totalTokens: pack.totalTokens,
          maxTokens: pack.budget.maxTokens,
        },
      },
      recommendation: {
        action: "increase-budget",
        description:
          "Budget is underutilized — consider adding more context or reducing the budget",
        suggestedChange: { maxTokens: Math.ceil(pack.totalTokens * 1.2) },
        estimatedImpact: "Right-sizing the budget avoids wasted allocation",
      },
    };
  }

  if (utilization > thresholds.maxUtilization) {
    return {
      issue: {
        severity: "info",
        category: "budget-waste",
        message: `Very tight budget utilization (${Math.round(utilization * 100)}%) — important items may be getting dropped`,
        evidence: {
          utilization,
          totalTokens: pack.totalTokens,
          maxTokens: pack.budget.maxTokens,
        },
      },
      recommendation: {
        action: "increase-budget",
        description:
          "Budget is nearly exhausted — increase to accommodate more context",
        suggestedChange: { maxTokens: Math.ceil(pack.budget.maxTokens * 1.5) },
        estimatedImpact:
          "More headroom reduces risk of dropping important items",
      },
    };
  }

  return {};
}

export function analyzeDropped(
  pack: ContextPack,
  query?: QueryInput
): DroppedAnalysis {
  const dropped = pack.dropped ?? [];
  const droppedByKind: Record<string, number> = {};

  for (const item of dropped) {
    const kind = item.kind ?? "unknown";
    droppedByKind[kind] = (droppedByKind[kind] ?? 0) + 1;
  }

  const highPriorityDropped = dropped.filter(item => (item.priority ?? 0) > 7);

  let potentiallyRelevant: ContextItem[] = [];
  if (query) {
    const normalized = normalizeQuery(query);
    potentiallyRelevant = dropped.filter(item => {
      const relevance = computeRelevance(normalized, item, {
        scoringMethod: "keyword",
      });
      return relevance > 0.3;
    });
  }

  return {
    totalDropped: dropped.length,
    droppedByKind,
    highPriorityDropped,
    potentiallyRelevant,
  };
}

export function analyzeDroppedPriorities(
  droppedAnalysis: DroppedAnalysis
): AnalyzerResult {
  if (droppedAnalysis.highPriorityDropped.length > 0) {
    return {
      issue: {
        severity: "critical",
        category: "wrong-priorities",
        message: `${droppedAnalysis.highPriorityDropped.length} high-priority item(s) were dropped — model is missing critical context`,
        evidence: {
          droppedIds: droppedAnalysis.highPriorityDropped.map(i => i.id),
          droppedCount: droppedAnalysis.highPriorityDropped.length,
        },
      },
      recommendation: {
        action: "increase-budget",
        description:
          "Increase the token budget to accommodate high-priority items that were dropped",
        suggestedChange: { increaseBudget: true },
        estimatedImpact:
          "Critical context items will be included, improving answer quality",
      },
    };
  }
  return {};
}

export function analyzeMissingContext(
  droppedAnalysis: DroppedAnalysis
): AnalyzerResult {
  if (droppedAnalysis.potentiallyRelevant.length > 0) {
    return {
      issue: {
        severity: "warning",
        category: "missing-context",
        message: `${droppedAnalysis.potentiallyRelevant.length} dropped item(s) appear relevant to the query`,
        evidence: {
          relevantDroppedIds: droppedAnalysis.potentiallyRelevant.map(
            i => i.id
          ),
          count: droppedAnalysis.potentiallyRelevant.length,
        },
      },
      recommendation: {
        action: "adjust-weights",
        description:
          "Increase relevance weight so query-relevant items score higher during packing",
        suggestedChange: { weights: { relevance: 2.0 } },
        estimatedImpact:
          "Relevant items will be prioritized over less relevant ones",
      },
    };
  }
  return {};
}
