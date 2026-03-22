import type {
  ContextPack,
  ContextTrace,
  ContextItem,
  Budget,
  PackOptions,
} from "@context-engineering/core";
import { analyzeContext, pack } from "@context-engineering/core";
import type {
  ContextDebugger,
  DebuggerConfig,
  Diagnosis,
  DiagnoseOptions,
  DiagnosticIssue,
  Recommendation,
} from "./types.js";
import {
  resolveThresholds,
  analyzeRedundancy,
  analyzeFreshness,
  analyzeDiversity,
  analyzeUtilization,
  analyzeDropped,
  analyzeDroppedPriorities,
  analyzeMissingContext,
} from "./analyzers.js";
import { compareResponses } from "./compare.js";

function isContextTrace(
  input: ContextPack | ContextTrace
): input is ContextTrace {
  return "steps" in input && "pack" in input && "createdAt" in input;
}

function extractPack(input: ContextPack | ContextTrace): ContextPack {
  return isContextTrace(input) ? input.pack : input;
}

export function createContextDebugger(
  config?: DebuggerConfig
): ContextDebugger {
  const thresholds = resolveThresholds(config?.qualityThresholds);

  function diagnose(
    input: ContextPack | ContextTrace,
    options?: DiagnoseOptions
  ): Diagnosis {
    const contextPack = extractPack(input);
    const quality = analyzeContext(contextPack.selected);
    const droppedAnalysis = analyzeDropped(contextPack, options?.query);

    const issues: DiagnosticIssue[] = [];
    const recommendations: Recommendation[] = [];

    const analyzers = [
      analyzeRedundancy(quality, thresholds),
      analyzeFreshness(quality, thresholds),
      analyzeDiversity(quality, thresholds),
      analyzeUtilization(contextPack, thresholds),
      analyzeDroppedPriorities(droppedAnalysis),
      analyzeMissingContext(droppedAnalysis),
    ];

    for (const result of analyzers) {
      if (result.issue) issues.push(result.issue);
      if (result.recommendation) recommendations.push(result.recommendation);
    }

    const hasCritical = issues.some(i => i.severity === "critical");
    const hasWarning = issues.some(i => i.severity === "warning");
    const overallHealth = hasCritical
      ? "critical"
      : hasWarning
        ? "warning"
        : "good";

    return {
      overallHealth,
      quality,
      issues,
      recommendations,
      droppedAnalysis,
    };
  }

  function proactiveCheck(
    items: ContextItem[],
    budget: Budget,
    options?: DiagnoseOptions & { packOptions?: PackOptions }
  ): Diagnosis {
    const packResult = pack(items, budget, options?.packOptions);
    return diagnose(packResult, options);
  }

  return {
    diagnose,
    proactiveCheck,
    compareResponses,
  };
}
